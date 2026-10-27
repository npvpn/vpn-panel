"""Чистые правила выбора хостов, без пользовательских ключей, БД и app runtime."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from time import monotonic

from pydantic import ValidationError

from app.models.host_injection import (
    SELECTION_SECONDS,
    HostInjection,
    IdSelector,
    InjectionDiagnostic,
    InjectionGroup,
    InjectionGroupPreview,
    InjectionPreview,
    RegexSelector,
    compile_selector,
)


class InjectionError(ValueError):
    def __init__(self, code: str, host_id: int | None = None):
        self.code = code
        self.host_id = host_id
        super().__init__(code)


def template_injection(template: Mapping) -> HostInjection | None:
    keys = [key for key in ("npvpn", "remnawave") if key in template]
    if len(keys) > 1:
        raise InjectionError("conflicting_directives")
    if not keys:
        return None
    value = template[keys[0]]
    if not isinstance(value, dict) or "enabled" in value:
        raise InjectionError("invalid_directive")
    return HostInjection.model_validate(value)


def resolve_host_injection(host_override: dict | None, template: Mapping) -> HostInjection | None:
    # Validate both even when the form overrides a malformed document.
    inherited = template_injection(template)
    value = HostInjection.model_validate(host_override) if host_override is not None else inherited
    return value if value is not None and value.enabled else None


def strip_injection_directives(template: dict) -> dict:
    result = deepcopy(template)
    result.pop("npvpn", None)
    result.pop("remnawave", None)
    return result


def select_injected_hosts(
    group: InjectionGroup, recipient: Mapping, hosts: Sequence[Mapping], *, deadline: float
) -> list[Mapping]:
    if monotonic() >= deadline:
        raise InjectionError("selector_timeout")
    candidates = [
        host
        for host in hosts
        if host.get("id") != recipient.get("id")
        and not host.get("is_disabled")
        and (group.selectFrom == "ALL" or bool(host.get("is_hidden")) == (group.selectFrom == "HIDDEN"))
    ]
    if isinstance(group.selector, IdSelector):
        by_id = {host["id"]: host for host in candidates}
        return [by_id[id_] for id_ in group.selector.values if id_ in by_id]
    candidates.sort(key=lambda host: (host.get("order") or 0, host["id"]))
    if not isinstance(group.selector, RegexSelector):
        tag = recipient.get("group_tag")
        return [host for host in candidates if tag and host.get("group_tag") == tag]
    pattern = compile_selector(group.selector.pattern)
    key = "remark" if group.selector.type == "remarkRegex" else "group_tag"
    result = []
    for host in candidates:
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise InjectionError("selector_timeout")
        value = host.get(key) or ""
        if len(value) > 512:
            raise InjectionError("selector_input_too_long")
        try:
            if pattern.search(value, timeout=remaining):
                result.append(host)
        except TimeoutError as exc:
            raise InjectionError("selector_timeout") from exc
    return result


def validate_composed_tag_graph(config: dict) -> None:
    """Проверка ссылок после managed rewrite, до выдачи готового документа."""
    outbounds = config.get("outbounds", [])
    tags = {item["tag"] for item in outbounds if item.get("tag")}
    routing = config.get("routing") or {}
    balancers = routing.get("balancers", [])
    balancer_tags = [item.get("tag") for item in balancers]
    if len(balancer_tags) != len(set(balancer_tags)):
        raise InjectionError("duplicate_balancer_tag")

    def require_tag(tag):
        if tag and tag not in tags:
            raise InjectionError("unresolved_outbound_tag")

    for rule in routing.get("rules", []):
        require_tag(rule.get("outboundTag"))
        if rule.get("balancerTag") and rule["balancerTag"] not in balancer_tags:
            raise InjectionError("unresolved_balancer_tag")
    for balancer in balancers:
        require_tag(balancer.get("fallbackTag"))
        if not any(tag.startswith(prefix) for prefix in balancer.get("selector", []) for tag in tags):
            raise InjectionError("empty_balancer_selector")
    for outbound in outbounds:
        require_tag((outbound.get("proxySettings") or {}).get("tag"))
        stream = outbound.get("streamSettings") or {}
        require_tag((stream.get("sockopt") or {}).get("dialerProxy"))


def diagnose_injection(
    recipient: Mapping, hosts: Sequence[Mapping], template_for: Callable, active_inbounds: set[str]
) -> InjectionPreview:
    """Read-only source selection preview, not a per-user endpoint/render check."""
    result = InjectionPreview()

    def issue(code, *, group=None, host_id=None, path="", level="warning"):
        result.issues.append(InjectionDiagnostic(code=code, group=group, host_id=host_id, path=path, level=level))

    try:
        injection = resolve_host_injection(
            recipient.get("host_injection"), template_for(recipient.get("client_config_id"))
        )
    except ValidationError as exc:
        for error in exc.errors(include_input=False, include_url=False):
            issue("invalid_directive", level="error", path=".".join(map(str, error["loc"])))
        return result
    except ValueError as exc:
        issue(exc.code if isinstance(exc, InjectionError) else "invalid_template", level="error")
        return result
    if injection is None:
        return result
    result.active = True
    if recipient.get("is_disabled"):
        issue("recipient_disabled")
    if recipient.get("is_hidden"):
        issue("recipient_hidden")
    by_id = {host.get("id"): host for host in hosts}
    eligible = [host for host in hosts if host.get("inbound_tag") in active_inbounds]
    prefixes = set()
    deadline = monotonic() + SELECTION_SECONDS
    for index, group in enumerate(injection.injectHosts, 1):
        preview = InjectionGroupPreview(group=index, pattern=getattr(group.selector, "pattern", ""))
        result.groups.append(preview)
        if group.tagPrefix is not None:
            if group.tagPrefix in prefixes:
                issue("duplicate_group_prefix", group=index, level="error")
            prefixes.add(group.tagPrefix)
        if group.selector.type == "sameTagAsRecipient" and not recipient.get("group_tag"):
            issue("recipient_tag_missing", group=index)
        if isinstance(group.selector, IdSelector):
            for id_ in group.selector.values:
                host = by_id.get(id_)
                reason = None
                if id_ == recipient.get("id"):
                    reason = "self_source"
                elif host is None:
                    reason = "missing_source"
                elif host.get("is_disabled"):
                    reason = "disabled_source"
                elif host.get("inbound_tag") not in active_inbounds:
                    reason = "inactive_inbound"
                elif group.selectFrom != "ALL" and bool(host.get("is_hidden")) != (group.selectFrom == "HIDDEN"):
                    reason = "visibility_mismatch"
                if reason:
                    issue(reason, group=index, host_id=id_)
        try:
            selected = select_injected_hosts(group, recipient, eligible, deadline=deadline)
        except InjectionError as exc:
            issue(exc.code, group=index, level="error")
            break
        for host in selected:
            try:
                source = resolve_host_injection(host.get("host_injection"), template_for(host.get("client_config_id")))
            except ValueError:
                issue("invalid_source", group=index, host_id=host.get("id"))
                continue
            if source is not None and not source.addVirtualHostAsOutbound:
                issue("virtual_source", group=index, host_id=host.get("id"))
                continue
            preview.host_ids.append(host["id"])
        if not preview.host_ids:
            issue("empty_group", group=index)
    if not injection.addVirtualHostAsOutbound and not any(group.host_ids for group in result.groups):
        issue("empty_injection", level="error")
    return result
