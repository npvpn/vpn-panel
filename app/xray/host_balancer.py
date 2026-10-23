"""Клиентская балансировка: стратегия хоста либо совместимое поведение шаблона.

Явный режим заменяет балансировщики и наблюдатели в копии клиентского документа.
Без настройки сохраняется шаблон; для multi-address без своего балансировщика
добавляется прежний leastPing. Серверные каскады и HAProxy здесь не изменяются.
"""

from __future__ import annotations

from copy import deepcopy

PROXY_OUTBOUND_TAG = "proxy"
HOST_BALANCER_TAG = "proxy-balancer"
HOST_BALANCER_STRATEGY = "leastPing"

OBSERVATORY_PROBE_URL = "https://www.google.com/generate_204"
OBSERVATORY_INTERVAL = "15s"


def proxy_outbound_tag(index: int) -> str:
    """Тег proxy-outbound: первый — 'proxy' (обратная совместимость с явным
    outboundTag:'proxy' в пользовательском routing), остальные — 'proxy-<i>'."""
    return PROXY_OUTBOUND_TAG if index == 0 else f"{PROXY_OUTBOUND_TAG}-{index}"


def build_balancer() -> dict:
    """Балансировщик по всем proxy-outbound (селектор по префиксу тега)."""
    return {
        "tag": HOST_BALANCER_TAG,
        "selector": [PROXY_OUTBOUND_TAG],
        "strategy": {"type": HOST_BALANCER_STRATEGY},
    }


def build_balancer_rule() -> dict:
    """Catch-all: весь оставшийся tcp/udp-трафик → балансировщик.

    Ставится ПОСЛЕДНИМ в rules — xray матчит сверху вниз, first-match-wins, так что
    правила block/direct должны отработать раньше. Раньше этот трафик уходил в первый
    outbound (proxy) как дефолт xray; теперь его перехватывает balancerTag."""
    return {
        "type": "field",
        "network": "tcp,udp",
        "balancerTag": HOST_BALANCER_TAG,
    }


def build_observatory() -> dict:
    """Health-check proxy-outbound'ов: по нему leastPing выбирает живую ноду с мин. пингом."""
    return {
        "subjectSelector": [PROXY_OUTBOUND_TAG],
        "probeUrl": OBSERVATORY_PROBE_URL,
        "probeInterval": OBSERVATORY_INTERVAL,
    }


def _catch_all(rule: dict) -> bool:
    return (
        rule.get("balancerTag") == HOST_BALANCER_TAG
        and rule.get("network") in ("tcp,udp", "udp,tcp")
        and not (set(rule) - {"type", "network", "balancerTag", "ruleTag"})
    )


def apply_host_balancer(config: dict, balancing: dict | None = None, *, participants: list[str] | None = None) -> dict:
    """Шаблон владеет балансировкой до явного выбора стратегии хоста.

    Управляемый режим заменяет секции балансировки только в копии документа.
    Условия/порядок routing сохраняются; shared routing никогда не мутируется.
    """
    routing = deepcopy(config.get("routing") or {})
    if balancing is None:
        if routing.get("balancers"):
            return config
        routing["balancers"] = [build_balancer()]
        routing["rules"] = list(routing.get("rules", [])) + [build_balancer_rule()]
        config["routing"] = routing
        if "observatory" not in config and "burstObservatory" not in config:
            config["observatory"] = build_observatory()
        return config

    selectors = participants if participants is not None else [PROXY_OUTBOUND_TAG]
    strategy = {"type": balancing["strategy"]}
    if balancing.get("settings") is not None:
        strategy["settings"] = deepcopy(balancing["settings"])
    routing["balancers"] = [{"tag": HOST_BALANCER_TAG, "selector": selectors, "strategy": strategy}]
    rules = []
    has_catch_all = False
    for rule in routing.get("rules", []):
        if rule.get("balancerTag") or rule.get("outboundTag") == PROXY_OUTBOUND_TAG:
            rule.pop("outboundTag", None)
            rule["balancerTag"] = HOST_BALANCER_TAG
        if _catch_all(rule):
            if has_catch_all:
                continue
            has_catch_all = True
        rules.append(rule)
    if not has_catch_all:
        rules.append(build_balancer_rule())
    routing["rules"] = rules
    config["routing"] = routing
    config.pop("observatory", None)
    config.pop("burstObservatory", None)
    probe = balancing.get("probe") or {}
    if balancing["strategy"] == "leastPing":
        config["observatory"] = {
            "subjectSelector": selectors,
            "probeUrl": probe["url"],
            "probeInterval": probe["interval"],
            "enableConcurrency": probe["enableConcurrency"],
        }
    elif balancing["strategy"] == "leastLoad":
        config["burstObservatory"] = {
            "subjectSelector": selectors,
            "pingConfig": {
                "destination": probe["url"],
                "interval": probe["interval"],
                "timeout": probe["timeout"],
                "sampling": probe["sampling"],
                "connectivity": probe["connectivity"],
            },
        }
    return config
