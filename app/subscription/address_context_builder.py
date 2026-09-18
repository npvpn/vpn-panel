"""Сборка AddressContext из БД — отдельно от чистого address_context.py."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import cast

from app.db import Session, crud
from app.db.models import User
from app.subscription.address_context import AddressContext
from app.xray.address_policy import epoch_for, epoch_start_day

logger = logging.getLogger(__name__)

_EPOCH_ORIGIN = datetime(2026, 1, 1, tzinfo=UTC)


def day_index(now: datetime) -> int:
    """Номер суток от фиксированного начала отсчёта."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return (now - _EPOCH_ORIGIN).days


def build_address_context(
    db: Session,
    dbuser: User,
    *,
    is_revoked: bool,
    is_expired: bool,
    bot_settings: dict,
) -> AddressContext:
    """Контекст сужения адресов и закреплений (NPVPN-2072).

    Для revoked/expired ни автовыбор, ни закрепления не применяются — своя логика
    выдачи, пин туда не лезет.

    Закрепление же работает НЕЗАВИСИМО от `sub_address_subset_enabled`: это явное
    ручное действие саппорта/отладки (адресно, со сроком годности, с автором), а
    не автоматика — выключенный флаг сужения не должен его глушить. Иначе
    инструмент бесполезен именно там, где нужен: фича ещё не раскатана.
    """
    if is_revoked or is_expired:
        return AddressContext.disabled()

    user_id = cast(int, dbuser.id)
    # Один дешёвый индексный запрос на каждый рендер подписки — вне зависимости от
    # флага сужения, закрепления могут быть выставлены и при выключенной фиче.
    pins = crud.get_active_pins(db, user_id, datetime.now(UTC))

    if not bot_settings.get("sub_address_subset_enabled"):
        return AddressContext(user_id=user_id, size=0, epoch=0, weights={}, enabled=False, pins=pins)

    size = int(bot_settings.get("sub_address_subset_size") or 0)
    if size <= 0:
        return AddressContext(user_id=user_id, size=0, epoch=0, weights={}, enabled=False, pins=pins)

    period_days = max(1, int(bot_settings.get("sub_address_rotation_days") or 1))
    offset = int(dbuser.address_rotation_offset or 0)
    today = day_index(datetime.now(UTC))

    epoch = epoch_for(user_id, today, period_days, offset)
    # Вес берётся на начало ЕГО эпохи, а не на сегодня: внутри эпохи он обязан быть
    # постоянным, иначе подмножество поплывёт между рендерами.
    snapshot_day = epoch_start_day(user_id, today, period_days)
    weights = crud.get_weight_snapshot(db, snapshot_day)
    if not weights:
        # Флаг включён, а снимка весов нет: выбор адресов идёт равномерный, а не по
        # остатку трафика — фича уже один раз тихо обрывалась на allowlist'е
        # (NPVPN-2072), молчать про этот случай второй раз нельзя. Не горячий путь
        # (срабатывает только при пустых весах, не на каждом рендере).
        logger.warning(
            "address subset enabled but weight snapshot is empty: user_id=%s snapshot_day=%s",
            user_id,
            snapshot_day,
        )

    return AddressContext(
        user_id=user_id,
        size=size,
        epoch=epoch,
        weights=weights,
        enabled=True,
        pins=pins,
    )
