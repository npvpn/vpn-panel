"""Лёгкий срез состояния юзеров для сверки с ботом (NPVPN-1643).

Только три колонки, никаких ORM-объектов, ссылок и ensure_subscription_token:
эндпоинт вызывается по всей базе (десятки тысяч строк) и не должен ни писать
в БД, ни грузить прокси с инбаундами.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.crud import _normalize_bot_username
from app.db.models import Admin, Bot, User


def get_users_digest(
    db: Session,
    *,
    admins: list[str] | None = None,
    bot_username: str | None = None,
    offset: int | None = None,
    limit: int | None = None,
) -> tuple[list[dict], int]:
    """Возвращает (список из {username, status, expire}, общее количество)."""
    query = db.query(User.username, User.status, User.expire)

    if bot_username:
        normalized = _normalize_bot_username(bot_username)
        if normalized:
            query = query.join(User.bot).filter(Bot.username == normalized)

    if admins:
        query = query.join(User.admin).filter(Admin.username.in_(admins))

    total = query.count()

    query = query.order_by(User.id)
    if offset is not None:
        query = query.offset(offset)
    if limit is not None:
        query = query.limit(limit)

    users = [
        {"username": username, "status": str(status), "expire": expire} for username, status, expire in query.all()
    ]
    return users, total
