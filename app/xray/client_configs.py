"""Чистые функции выбора клиентского конфига хоста (NPVPN-2024).

Пришли на смену bs_routing.py: осью выбора стал именованный документ клиентского
конфига, привязанный к хосту, а не булев признак БС-ноды. Документ самодостаточен —
это ПОЛНЫЙ v2ray-json конфиг, а не вклеиваемая в шаблон секция routing. Резолва
здесь нет — id документа лежит прямо в словаре хоста из кэша xray.hosts. Без
зависимостей от БД/окружения — тестируются как bs_limit/inbound_filter.
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


def select_config(
    configs: dict[int, dict],
    default_id: int | None,
    config_id: int | None,
) -> dict | None:
    """Полный клиентский конфиг одного сервера, либо None.

    Документы самодостаточны: подмены секций больше нет, фолбэк идёт ЦЕЛЫМИ
    документами. Пустое тело документа в `configs` не попадает и означает
    «документ не заполнен», а не «пустой конфиг».

    1. выбранный документ с непустым телом → он;
    2. иначе (NULL, удалённый документ, пустое тело) → дефолтный документ;
    3. ни того, ни другого → None, и вызывающий берёт файловый шаблон.

    Третья ступень возвращает None, а не сам файловый шаблон, намеренно: рендер
    jinja-шаблона стоит денег на горячем /sub/, а нужен он только на свежей
    установке панели, где документы ещё не заполнены.
    """
    body = configs.get(config_id) if config_id is not None else None
    if body is not None:
        return body
    if default_id is not None:
        return configs.get(default_id)
    return None
