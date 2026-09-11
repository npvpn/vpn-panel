"""Чистые функции выбора клиентского routing по профилю ноды (NPVPN-2024).

Пришли на смену bs_routing.py: осью выбора стал профиль (произвольный
именованный документ), а не булев признак БС-ноды. Без зависимостей от
БД/окружения — тестируются как bs_limit/inbound_filter.
"""

import json
from collections.abc import Mapping


def parse_json_object(raw: str | None) -> dict | None:
    """Распарсить JSON-строку в объект.

    '' / пробелы / None → None (поле не задано, использовать фолбэк).
    Валидный JSON-объект → dict.
    Невалидный JSON или не-объект (массив/строка/число) → ValueError.
    """
    if raw is None or not str(raw).strip():
        return None
    try:
        value = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


def resolve_routing_profile(host: Mapping, node_profiles: Mapping[int, int]) -> int | None:
    """Профиль хоста по привязанным нодам.

    ANY-семантика: хватает одной ноды с профилем среди привязанных. Профиль
    определяется ТОЛЬКО по host_nodes → host["node_ids"], а не по совпадению
    адреса хоста с Node.address: хост может быть доменом (маскировка TLS/SNI),
    тогда как нода подключена по IP (NPVPN-1652).
    """
    if not node_profiles:
        return None
    for node_id in host.get("node_ids") or ():
        profile_id = node_profiles.get(node_id)
        if profile_id is not None:
            return profile_id
    return None


def select_routing(template_routing: dict, profile_routing: dict | None) -> dict:
    """Секция routing для конфига одного сервера.

    Профиль не задан (нода без профиля либо у профиля пустое тело) — фолбэк на
    routing из общего шаблона, как было до разделения.
    """
    return profile_routing if profile_routing is not None else template_routing
