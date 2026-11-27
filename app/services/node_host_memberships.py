"""Saved host participation by node ID, including non-recursive composite sources."""

from collections import defaultdict
from dataclasses import dataclass
from time import monotonic

from sqlalchemy import select
from sqlalchemy.orm import Session, load_only, selectinload

from app import logger
from app.db.models import Bot, CascadeRoute, Node, ProxyHost
from app.models.host_injection import SELECTION_SECONDS
from app.models.node import NodeHostInventory, NodeHostMembership, NodeHostRole, NodeHostSource, NodeRole
from app.services.xray_templates import build_template_lookup, get_active_bodies
from app.subscription.host_candidates import compose_endpoints
from app.xray.host_addresses import entry_nodes_by_address, host_allowed_for_bot, resolve_host_addresses
from app.xray.host_injection import InjectionError, resolve_host_injection, select_injected_hosts


@dataclass
class _Endpoint:
    source_id: int
    roles: set[NodeHostRole]


def _entry_roles(node_id, entry_ids, tag, selected, exits) -> set[NodeHostRole]:
    roles: set[NodeHostRole] = set()
    if node_id in entry_ids:
        roles.add("entry" if selected or exits.get((node_id, tag)) else "direct")
    if any(node_id in exits.get((entry, tag), ()) for entry in entry_ids):
        roles.add("exit")
    return roles


def _candidate(host, node_id, exits, lookup, incomplete):
    linked_ids = set(host.node_ids)
    selected = host.balancer_nodes_source == "selected"
    by_address = entry_nodes_by_address(host)
    if selected:
        entries = set(host.balancer_node_ids)
    elif host.address:
        # A static domain can hide an unrelated first hop.
        entries = {node.id for node in by_address.values()}
    else:
        entries = linked_ids

    tag = host.inbound_tag
    linked: set[NodeHostRole] = {"linked"} if node_id in linked_ids and (selected or node_id not in entries) else set()
    configured = _entry_roles(node_id, entries, tag, selected, exits) | linked
    endpoints = []
    for address in resolve_host_addresses(host):
        if not address:
            continue
        entry = by_address.get(address)
        endpoint_roles = _entry_roles(node_id, (entry.id,), tag, selected, exits) if entry is not None else set()
        endpoints.append(_Endpoint(host.id, endpoint_roles | linked))
    try:
        injection = resolve_host_injection(host.host_injection, lookup(host.client_config_id))
    except ValueError:
        logger.warning("Node host inventory: invalid composition for host %s", host.id)
        incomplete.add(host.id)
        injection = None
        endpoints = []
    return {
        "host": {key: getattr(host, key) for key in ("id", "remark", "group_tag", "order", "is_hidden", "is_disabled")},
        "injection": injection,
        "inbound": tag,
        "bots": host.bot_usernames,
        "blocked": False,  # The configured pool precedes per-user usage limits and pins.
        "endpoints": endpoints,
        "configured": configured,
        "explicit": node_id in entries or node_id in linked_ids,
    }


def _compose_sources(catalog, usernames, active_inbounds, malformed):
    sources: dict[int, dict[int, set[NodeHostRole]]] = defaultdict(lambda: defaultdict(set))
    incomplete = set(malformed)
    for username in usernames or [None]:
        allowed = [
            item
            for item in catalog
            if item["inbound"] in active_inbounds
            and host_allowed_for_bot(item["bots"], username, panel_bot_count=len(usernames))
        ]
        valid = [item for item in allowed if item["host"]["id"] not in malformed]
        invalid = [item["host"] for item in allowed if item["host"]["id"] in malformed]
        for item in valid:
            if not item["injection"]:
                continue
            recipient_id = item["host"]["id"]
            try:
                endpoints, _, _ = compose_endpoints(item, valid)
            except InjectionError as exc:
                logger.warning("Node host inventory: composition for host %s failed: %s", recipient_id, exc.code)
                incomplete.add(recipient_id)
                continue
            for _, endpoint in endpoints:
                if endpoint.roles and endpoint.source_id != recipient_id:
                    sources[recipient_id][endpoint.source_id].update(endpoint.roles)
            if invalid:
                # Diagnose only after composing valid sources. Broken hosts must
                # not reserve outbound tags or consume the pool's endpoint limit.
                deadline = monotonic() + SELECTION_SECONDS
                try:
                    if any(
                        select_injected_hosts(group, item["host"], invalid, deadline=deadline)
                        for group in item["injection"].injectHosts
                    ):
                        incomplete.add(recipient_id)
                except InjectionError:
                    incomplete.add(recipient_id)
    return sources, incomplete


def get_node_host_memberships(db: Session, node_id: int, active_inbounds: set[str]) -> NodeHostInventory:
    hosts = (
        db.query(ProxyHost)
        .options(
            load_only(
                ProxyHost.id,
                ProxyHost.remark,
                ProxyHost.inbound_tag,
                ProxyHost.is_disabled,
                ProxyHost.address,
                ProxyHost.is_hidden,
                ProxyHost.group_tag,
                ProxyHost.order,
                ProxyHost.host_injection,
                ProxyHost.client_config_id,
                ProxyHost.balancer_nodes_source,
            ),
            selectinload(ProxyHost.nodes).load_only(Node.id, Node.address, Node.status),
            selectinload(ProxyHost.balancer_nodes).load_only(Node.id, Node.address, Node.status),
            selectinload(ProxyHost.bots).load_only(Bot.username),
        )
        .filter(ProxyHost.is_placeholder.is_(False))
        .order_by(ProxyHost.is_disabled.is_(True), ProxyHost.id)
        .all()
    )
    exits: dict[tuple[int, str], set[int]] = defaultdict(set)
    for entry, inbound, exit_id in db.execute(
        select(CascadeRoute.entry_node_id, CascadeRoute.entry_inbound_tag, CascadeRoute.exit_node_id)
        .join(Node, Node.id == CascadeRoute.entry_node_id)
        .where(Node.role == NodeRole.entry)
    ):
        exits[entry, inbound].add(exit_id)
    lookup = build_template_lookup(get_active_bodies(db))
    malformed: set[int] = set()
    catalog = [_candidate(host, node_id, exits, lookup, malformed) for host in hosts]
    usernames = list(db.scalars(select(Bot.username))) if any(item["injection"] for item in catalog) else []
    sources, incomplete = _compose_sources(catalog, usernames, active_inbounds, malformed)

    result = []
    remarks = {host.id: host.remark for host in hosts}
    for item in catalog:
        meta = item["host"]
        host_id = meta["id"]
        own: set[NodeHostRole] = set()
        if host_id not in malformed and (not item["injection"] or item["injection"].addVirtualHostAsOutbound):
            own = item["configured"]
        elif host_id in incomplete and item["explicit"]:
            own = {"linked"}
        details = [
            NodeHostSource(host_id=i, remark=remarks[i], roles=sorted(roles))
            for i, roles in sorted(sources.get(host_id, {}).items())
        ]
        combined = own.union(*(s.roles for s in details))
        if combined:
            result.append(
                NodeHostMembership(
                    host_id=host_id,
                    remark=meta["remark"],
                    inbound_tag=item["inbound"],
                    is_disabled=bool(meta["is_disabled"]),
                    roles=sorted(combined),
                    sources=details,
                )
            )
    return NodeHostInventory(hosts=result, incomplete_host_ids=sorted(incomplete))
