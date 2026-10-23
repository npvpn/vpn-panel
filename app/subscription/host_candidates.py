"""Подготовка доступных пользователю подключений; общий путь обычной выдачи и инжекта."""

from __future__ import annotations

import logging
import random
import secrets
from dataclasses import dataclass

from app.subscription.address_context import AddressContext, settings_from_host
from app.subscription.bs_context import ZERO_STUB, BsContext
from app.xray.host_addresses import host_allowed_for_bot
from app.xray.host_injection import resolve_host_injection

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Endpoint:
    host_id: int | None
    address: str
    inbound: dict
    settings: dict


def prepare_candidates(
    inbounds: dict,
    proxies,
    format_variables,
    *,
    inbounds_by_tag,
    hosts_by_tag,
    is_json,
    template_for,
    bs=None,
    stub=None,
    subset=None,
) -> list[dict]:
    bs = bs or BsContext.empty()
    stub = stub or ZERO_STUB
    subset = subset or AddressContext.disabled()
    _inbounds = []
    for protocol, tags in inbounds.items():
        for tag in tags:
            _inbounds.append((protocol, [tag]))
    index_dict = {proxy: index for index, proxy in enumerate(inbounds_by_tag.keys())}
    ordered_inbounds = sorted(_inbounds, key=lambda x: index_dict.get(x[1][0], float("inf")))
    user_bot_username = format_variables.get("BOT_USERNAME")

    candidates: list[dict] = []

    for protocol, tags in ordered_inbounds:
        settings = proxies.get(protocol)
        if not settings:
            continue

        format_variables.update({"PROTOCOL": protocol.name})
        for tag in tags:
            inbound = inbounds_by_tag.get(tag)
            if not inbound:
                continue

            format_variables.update({"TRANSPORT": inbound["network"]})
            for host in hosts_by_tag.get(tag, []):
                allowed_bot_usernames = host.get("bot_usernames") or []
                if not host_allowed_for_bot(allowed_bot_usernames, user_bot_username):
                    continue

                if host.get("is_disabled"):
                    continue
                try:
                    injection = resolve_host_injection(host.get("host_injection"), template_for(host))
                except ValueError:
                    logger.warning("Host %s: invalid_injection", host.get("id"))
                    continue
                host_inbound = inbound.copy()

                sni = ""
                sni_list = host["sni"] or inbound["sni"]
                if sni_list:
                    salt = secrets.token_hex(8)
                    sni = random.choice(sni_list).replace("*", salt)

                if sids := inbound.get("sids"):
                    host_inbound["sid"] = random.choice(sids)

                req_host = ""
                req_host_list = host["host"] or inbound["host"]
                if req_host_list:
                    salt = secrets.token_hex(8)
                    req_host = random.choice(req_host_list).replace("*", salt)

                address = ""
                address_list = host["address"]
                if not injection and host.get("balancer_nodes_source") == "selected" and not address_list:
                    continue
                # Сужение — ДО расчёта balanced, который зависит от длины списка.
                # Отдельного исключения для БС-хостов не требуется: заблокированный
                # БС-хост уходит в ветку bs.is_blocked() ниже, где адрес подменяется
                # на заглушку и суженный список не используется вовсе; а у
                # незаблокированного БС-хоста сужение лишь концентрирует расход на
                # меньшем числе нод — БС-лимит считается агрегатом по юзеру
                # (aggregate_bs_usage), а не по ноде, поэтому учёт не ломается.
                if address_list and not injection:
                    address_list = subset.pick(
                        address_list,
                        host.get("node_ids") or [],
                        addresses_from_nodes=bool(host.get("addresses_from_nodes")),
                        host_id=host.get("id"),
                        # NPVPN-2072: размер подмножества и период ротации — свойства ХОСТА:
                        # у локаций разное число нод, и один размер на всего бота этого не
                        # выражал.
                        settings=settings_from_host(host),
                    )
                balanced = is_json and address_list and (len(address_list) > 1 or host.get("balancing") is not None)
                if address_list and not balanced:
                    salt = secrets.token_hex(8)
                    address = random.choice(address_list).replace("*", salt)

                if host["path"] is not None:
                    path = host["path"].format_map(format_variables)
                else:
                    path = inbound.get("path", "").format_map(format_variables)

                if host.get("use_sni_as_host", False) and sni:
                    req_host = sni

                host_inbound.update(
                    {
                        "port": host["port"] or inbound["port"],
                        "sni": sni,
                        "host": req_host,
                        "tls": inbound["tls"] if host["tls"] is None else host["tls"],
                        "alpn": host["alpn"] if host["alpn"] else None,
                        "path": path,
                        "fp": host["fingerprint"] or inbound.get("fp", ""),
                        "ais": host["allowinsecure"] or inbound.get("allowinsecure", ""),
                        "mux_enable": host["mux_enable"],
                        "fragment_setting": host["fragment_setting"],
                        "noise_setting": host["noise_setting"],
                        "random_user_agent": host["random_user_agent"],
                        "xhttp_extra": host["xhttp_extra"] or inbound.get("xhttp_extra"),
                    }
                )

                # Пер-серверный конфиг только для v2ray-json: привязка лежит на самом
                # хосте. Другие форматы про документы конфига не знают.
                add_kwargs = {}
                if is_json:
                    config_id = host.get("client_config_id")
                    if config_id is not None:
                        add_kwargs["client_config_id"] = config_id

                candidate = {
                    "order": host.get("order", 0),
                    "blocked": bs.is_blocked(host),
                    "host": host,
                    "injection": injection,
                    "host_inbound": host_inbound,
                    "settings": settings.model_dump(),
                    "add_kwargs": add_kwargs,
                    "remark": host["remark"].format_map(format_variables),
                    "balanced": balanced and is_json,
                    "balancing": host.get("balancing"),
                }
                if candidate["balanced"]:
                    candidate["addresses"] = [
                        addr.replace("*", secrets.token_hex(8)).format_map(format_variables) for addr in address_list
                    ]
                else:
                    candidate["address"] = address.format_map(format_variables)
                resolved = candidate.get("addresses", [candidate.get("address", "")])
                if injection:
                    resolved = [
                        addr.replace("*", secrets.token_hex(8)).format_map(format_variables) for addr in address_list
                    ]
                candidate["endpoints"] = [
                    Endpoint(host.get("id"), addr, host_inbound, settings.model_dump()) for addr in resolved if addr
                ]
                candidates.append(candidate)

    return candidates


def compose_endpoints(recipient, candidates):
    """Не рекурсивный инжект: только разрешённые endpoints, без чужих шаблонов."""
    from time import monotonic

    from app.models.host_injection import MAX_ENDPOINTS, SELECTION_SECONDS
    from app.xray.host_injection import InjectionError, select_injected_hosts

    injection = recipient["injection"]
    deadline = monotonic() + SELECTION_SECONDS
    by_id = {item["host"].get("id"): item for item in candidates}
    catalog = [item["host"] for item in candidates]
    selected = []
    counts = {}
    used = set()
    has_bs = False
    blocked = False
    unavailable = False

    def add_source(item, prefix=None, name=None):
        nonlocal blocked, has_bs, unavailable
        if item["blocked"]:
            blocked = True
            return
        if not item["endpoints"]:
            unavailable = True
            return
        has_bs = has_bs or item["host"].get("is_bs", False)
        for index, endpoint in enumerate(item["endpoints"]):
            if prefix is not None:
                count = counts.get(prefix, 0) + 1
                counts[prefix] = count
                tag = prefix if count == 1 else f"{prefix}-{count}"
            else:
                tag = name if index == 0 else f"{name}-{index + 1}"
            if not tag or not tag.strip() or tag in used:
                raise InjectionError("outbound_tag_collision")
            used.add(tag)
            selected.append((tag, endpoint))
            if len(selected) > MAX_ENDPOINTS:
                raise InjectionError("too_many_endpoints")

    if injection.addVirtualHostAsOutbound:
        add_source(recipient, prefix="proxy")
    prefixes = set()
    for group in injection.injectHosts:
        if group.tagPrefix in prefixes:
            raise InjectionError("duplicate_group_prefix")
        if group.tagPrefix is not None:
            prefixes.add(group.tagPrefix)
        hosts = select_injected_hosts(group, recipient["host"], catalog, deadline=deadline)
        if not hosts:
            logger.warning("Host %s: empty_injection_group", recipient["host"].get("id"))
        for host in hosts:
            item = by_id[host["id"]]
            if item["injection"] and not item["injection"].addVirtualHostAsOutbound:
                logger.warning("Host %s: virtual_source_skipped source=%s", recipient["host"].get("id"), host["id"])
                continue
            name = host.get("group_tag") if group.useHostTagAsTag else None
            add_source(item, prefix=group.tagPrefix, name=name or host.get("remark"))
    return selected, has_bs, blocked and not unavailable
