"""Чистая генерация xray-балансировщика для multi-address хостов подписки (NPVPN-1596).

Хост, связанный с несколькими нодами (или со статическим address через запятую),
в формате v2ray-json отдаётся одним конфигом с N proxy-outbound (теги proxy, proxy-1, …)
и балансировщиком strategy=leastPing + observatory.

Стратегия leastPing (а не random): проверено вживую — RandomStrategy в xray-core observatory
ИГНОРИРУЕТ (прозвон идёт, но мёртвая нода остаётся в пуле → ~1/N коннектов падает). observatory
реально учитывает только leastPing/leastLoad (как в app/xray/cascade_config.py). leastPing
выбирает живую ноду с наименьшим пингом и автоматически обходит мёртвую (бесконечный пинг).
Трейд-офф: это «лучшая живая нода + failover», а не равномерный разброс — но отсев мёртвых
xray даёт только так.

Проба идёт ЧЕРЕЗ ноду до probeUrl: у живой ноды (VPN-выход) google/generate_204 доступен →
низкий пинг; мёртвая → проба падает → выпадает из пула.

Без импортов БД/шаблонов — покрывается pytest без окружения (как cascade_config/routing_profiles).
"""

from __future__ import annotations

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


def apply_host_balancer(config: dict) -> dict:
    """Дописать в собранный v2ray-json конфиг балансировщик, catch-all rule и observatory.

    Вызывается только когда proxy-outbound'ов >1 (см. V2rayJsonConfig.add_balanced).

    ВАЖНО: не мутирует config["routing"] на месте — select_routing()
    (app/xray/routing_profiles.py) может отдавать ОДИН И ТОТ ЖЕ routing-объект (без копии)
    во все серверные конфиги подписки (_assemble_config в app/subscription/v2ray.py).
    Мутация на месте протекла бы между конфигами: одноадресные хосты получали бы
    чужой balancer, а при 2+ multi-address хостах — по несколько одинаковых
    балансировщиков с одним и тем же тегом. Поэтому здесь строится новый dict
    routing (с новыми списками balancers/rules) и присваивается обратно в
    config["routing"], не трогая переданный в config исходный shared-объект.
    """
    routing = dict(config.get("routing") or {})
    routing["balancers"] = list(routing.get("balancers", [])) + [build_balancer()]
    routing["rules"] = list(routing.get("rules", [])) + [build_balancer_rule()]
    config["routing"] = routing
    config["observatory"] = build_observatory()
    return config
