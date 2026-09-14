"""Чистые функции выбора клиентского routing по профилю хоста (NPVPN-2024).

Пришли на смену bs_routing.py: осью выбора стал профиль (произвольный именованный
документ), привязанный к хосту, а не булев признак БС-ноды. Резолва здесь нет —
профиль лежит прямо в словаре хоста из кэша xray.hosts. Без зависимостей от
БД/окружения — тестируются как bs_limit/inbound_filter.
"""

import json


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


def select_routing(
    template_routing: dict,
    profile_routing: dict | None,
    default_routing: dict | None,
) -> dict:
    """Секция routing для конфига одного сервера.

    Двухступенчатый фолбэк: профиль хоста → профиль `default` → routing шаблона.

    Профиль хоста не задан (у хоста NULL в routing_profile_id, либо у назначенного
    профиля пустое тело) — берётся тело
    документа `default`. Так сохраняется дореформенное поведение, где обычный
    хост получал sub_routing_json_default, а routing шаблона был последним
    рубежом. Пустое тело на любой ступени означает «падать дальше по цепочке»,
    а не «пустой routing».
    """
    if profile_routing is not None:
        return profile_routing
    if default_routing is not None:
        return default_routing
    return template_routing
