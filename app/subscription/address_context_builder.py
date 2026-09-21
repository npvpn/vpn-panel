"""Сборка AddressContext из БД — отдельно от чистого address_context.py."""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime
from typing import cast

from app.db import Session, crud
from app.db.models import User
from app.subscription.address_context import AddressContext
from app.xray.address_policy import epoch_start_day

logger = logging.getLogger(__name__)

_EPOCH_ORIGIN = datetime(2026, 1, 1, tzinfo=UTC)

# Порог исчерпания считается по СВЕЖИМ nodes.hosting_used_bytes, а не по суточному снимку:
# смысл порога — не дать хостеру выставить счёт, и запаздывание на сутки его убивает.
# Рендер подписки — горячий путь, поэтому список держится в процессе TTL-кэшем. Окно равно
# периоду, с которым скрипт-мост обновляет расход (60 с): чаще ходить незачем, данные всё
# равно не изменятся.
_EXHAUSTED_TTL_SECONDS = 60
_exhausted_lock = threading.Lock()
_exhausted_cache: tuple[float, frozenset[int]] | None = None


def day_index(now: datetime) -> int:
    """Номер суток от фиксированного начала отсчёта."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return (now - _EPOCH_ORIGIN).days


def reset_exhausted_cache() -> None:
    """Сбрасывает TTL-кэш исчерпанных нод (тесты, ручная проверка после правки лимита)."""
    global _exhausted_cache
    with _exhausted_lock:
        _exhausted_cache = None


def get_exhausted_nodes(db: Session) -> frozenset[int]:
    """Ноды, перешагнувшие порог месячного лимита. Кэш на _EXHAUSTED_TTL_SECONDS."""
    global _exhausted_cache
    now = time.monotonic()
    with _exhausted_lock:
        cached = _exhausted_cache
        if cached is not None and now - cached[0] < _EXHAUSTED_TTL_SECONDS:
            return cached[1]
    exhausted = crud.get_exhausted_node_ids(db)
    with _exhausted_lock:
        _exhausted_cache = (now, exhausted)
    return exhausted


def build_address_context(
    db: Session,
    dbuser: User,
    *,
    is_revoked: bool,
    is_expired: bool,
    rotation_periods: set[int],
) -> AddressContext:
    """Контекст сужения адресов и закреплений (NPVPN-2072).

    Для revoked/expired ни автовыбор, ни закрепления не применяются — своя логика
    выдачи, пин туда не лезет.

    Закрепление же работает НЕЗАВИСИМО от настроек сужения: это явное ручное действие
    саппорта/отладки (адресно, со сроком годности, с автором), а не автоматика —
    выключенное на хосте сужение не должно его глушить. Иначе инструмент бесполезен
    именно там, где нужен: фича ещё не раскатана.

    `rotation_periods` — периоды ротации ВКЛЮЧЁННЫХ хостов (настройка живёт на хосте,
    см. HostSubsetSettings). Снимок весов нужен на начало эпохи каждого периода: у хостов
    с разными периодами эпохи стартуют в разные сутки. Пустое множество = сужение не
    включено нигде, и в БД за весами не ходим вовсе.
    """
    if is_revoked or is_expired:
        return AddressContext.disabled()

    user_id = cast(int, dbuser.id)
    today = day_index(datetime.now(UTC))
    # Один дешёвый индексный запрос на каждый рендер подписки — вне зависимости от
    # настроек хостов, закрепления могут быть выставлены и при выключенной фиче.
    pins = crud.get_active_pins(db, user_id, datetime.now(UTC))
    base = AddressContext(
        user_id=user_id,
        day_index=today,
        offset=int(dbuser.address_rotation_offset or 0),
        enabled=True,
        pins=pins,
    )
    if not rotation_periods:
        return base

    weights_by_day: dict[int, dict[int, float]] = {}
    for period in rotation_periods:
        # Вес берётся на начало эпохи ЭТОГО периода, а не на сегодня: внутри эпохи он
        # обязан быть постоянным, иначе подмножество поплывёт между рендерами.
        snapshot_day = epoch_start_day(user_id, today, period)
        if snapshot_day in weights_by_day:
            continue
        weights_by_day[snapshot_day] = crud.get_weight_snapshot(db, snapshot_day)

    if not any(weights_by_day.values()):
        # Сужение включено хотя бы на одном хосте, а снимка весов нет: выбор адресов
        # идёт равномерный, а не по остатку трафика — фича уже один раз тихо обрывалась
        # на allowlist'е (NPVPN-2072), молчать про этот случай второй раз нельзя.
        # Не горячий путь (срабатывает только при пустых весах, не на каждом рендере).
        logger.warning(
            "address subset enabled but weight snapshot is empty: user_id=%s days=%s",
            user_id,
            sorted(weights_by_day),
        )

    return AddressContext(
        user_id=user_id,
        day_index=today,
        offset=base.offset,
        weights_by_day=weights_by_day,
        exhausted=get_exhausted_nodes(db),
        enabled=True,
        pins=pins,
    )
