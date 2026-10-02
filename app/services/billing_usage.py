"""Сбор данных для ручного выставления счёта партнёрам (NPVPN-2044).

Логика живёт в сервисе, а не в роутере: роутер тянет FastAPI-стек (app.db,
app.models.admin, app.utils.responses), из-за чего его нельзя импортировать в
тестовой песочнице панели, где пакет `app` заглушён (tests/conftest.py). Здесь
только SQLAlchemy — и сбор проверяется тестами без поднятия приложения.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Bot, BotBsDaily, ProxyHost, User, UserDevice, host_bot_association


class BillingPeriodError(ValueError):
    """Неверный расчётный период."""


def validate_period(period_from: datetime, period_to: datetime) -> None:
    """Период — полуинтервал [from, to); пустой или перевёрнутый недопустим.

    Молча вернуть пустой ответ нельзя: ноль трафика читается как «не жёг», и
    счёт уйдёт на меньшую сумму.
    """
    if period_from >= period_to:
        raise BillingPeriodError("'from' must be earlier than 'to'")


def collect_bot_usage(db: Session, period_from: datetime, period_to: datetime) -> list[dict[str, Any]]:
    """Четыре величины по каждому боту, у которого есть хоть что-то.

    Бот без данных в ответ НЕ попадает: отличить «ноль» от «нет записи» должен
    вызывающий — ноль, выданный за отсутствие данных, читается как «трафика не
    было» и даёт счёт на меньшую сумму.

    Хосты и устройства — срез на сейчас, трафик — накопление за [from, to).
    """
    rented_rows = db.execute(
        select(Bot.username, ProxyHost.remark)
        .select_from(host_bot_association)
        .join(Bot, Bot.id == host_bot_association.c.bot_id)
        .join(ProxyHost, ProxyHost.id == host_bot_association.c.host_id)
        .where(host_bot_association.c.rented_at.isnot(None))
    ).all()

    devices_rows = db.execute(
        select(Bot.username, func.count(UserDevice.id))
        .select_from(UserDevice)
        .join(User, User.id == UserDevice.user_id)
        .join(Bot, Bot.id == User.bot_id)
        .where(UserDevice.status == "active")
        .group_by(Bot.username)
    ).all()

    bs_rows = db.execute(
        select(Bot.username, func.coalesce(func.sum(BotBsDaily.used_bytes), 0))
        .select_from(BotBsDaily)
        .join(Bot, Bot.id == BotBsDaily.bot_id)
        .where(BotBsDaily.day >= period_from.date(), BotBsDaily.day < period_to.date())
        .group_by(Bot.username)
    ).all()

    usage: dict[str, dict[str, Any]] = {}

    def row_for(username: str) -> dict[str, Any]:
        return usage.setdefault(
            username,
            {
                "bot_username": username,
                "rented_hosts": 0,
                "rented_host_remarks": [],
                "devices_active": 0,
                "bs_bytes": 0,
            },
        )

    for username, remark in rented_rows:
        row = row_for(username)
        row["rented_hosts"] += 1
        row["rented_host_remarks"].append(remark)

    for username, count in devices_rows:
        row_for(username)["devices_active"] = int(count or 0)

    for username, used in bs_rows:
        row_for(username)["bs_bytes"] = int(used or 0)

    for row in usage.values():
        row["rented_host_remarks"].sort()

    return [usage[name] for name in sorted(usage)]
