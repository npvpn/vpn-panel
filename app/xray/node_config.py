"""Кэш пер-нодного xray-конфига (NPVPN-1727).

Волна переподключения нод заставляла панель сериализовать полный конфиг со всеми
активными пользователями заново на каждую ноду; 20 таких to_json параллельно душили GIL
и роняли p99 /sub. Здесь пайплайн сборки конфига под конкретную ноду и кэш готовой
JSON-строки по «сигнатуре» ноды (инбаунды + cascade + блокировки), общий на волну.

Без тяжёлых импортов (app.db, config, xray_api) — тестируется как inbound_filter/cascade.
"""

from __future__ import annotations

import json
from collections.abc import Iterable

from app.xray.bs_limit import strip_blocked_clients
from app.xray.cascade_config import cascade_config
from app.xray.inbound_filter import apply_inbound_filter


def node_signature(
    node_inbound_tags: Iterable[str] | None,
    cascade_kwargs: dict,
    blocked_user_ids: Iterable[int] | None,
) -> tuple:
    """Детерминированный хэшируемый ключ пер-нодного конфига.

    Всё, что различает итоговый конфиг ноды: набор инбаундов, cascade-параметры и
    множество заблокированных user_id. Ноды с одинаковой сигнатурой получают один
    и тот же JSON из кэша; direct-ноды без блокировок → общий ключ.
    """
    return (
        tuple(sorted(node_inbound_tags or ())),
        json.dumps(cascade_kwargs or {}, sort_keys=True, default=str),
        tuple(sorted(blocked_user_ids or ())),
    )


def build_node_config_json(
    base_config,
    node_inbound_tags: Iterable[str] | None,
    cascade_kwargs: dict,
    blocked_user_ids: Iterable[int] | None,
) -> str:
    """Собрать конфиг под ноду и сериализовать в JSON (без кэша)."""
    cfg = strip_blocked_clients(
        cascade_config(apply_inbound_filter(base_config, node_inbound_tags), **(cascade_kwargs or {})),
        blocked_user_ids,
    )
    return cfg.to_json()
