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
    *,
    profile_assigned: bool,
) -> dict:
    """Секция routing для конфига одного сервера.

    Развилка — НЕ «есть ли тело профиля», а «назначен ли хосту профиль вообще»
    (profile_assigned: routing_profile_id хоста указывает на существующий документ).
    Аргумент обязателен и keyword-only намеренно: забытый флаг молча вернул бы
    назначенному пустому профилю фолбэк на `default` — ровно тот дефект, ради
    которого развилка и появилась.

    * профиль назначен → его тело, а при пустом теле — routing общего шаблона.
      Пустое тело назначенного профиля означает «этой группе серверов routing из
      шаблона», как до переезда пустой sub_routing_json_bs уводил БС-хост на
      routing шаблона, а не на sub_routing_json_default;
    * профиля нет (routing_profile_id IS NULL) → тело документа `default`, а при
      пустом теле `default` — routing шаблона. Так обычный хост сохраняет
      дореформенное поведение sub_routing_json_default.

    Пустое тело на любой ступени означает «падать дальше по цепочке», а не «пустой
    routing»; пустой routing задаётся только тем, что документ назначенного профиля
    не пуст.
    """
    if profile_assigned:
        return profile_routing if profile_routing is not None else template_routing
    if default_routing is not None:
        return default_routing
    return template_routing
