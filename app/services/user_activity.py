"""Лёгкое пакетное наблюдение первого подключения, без ORM-графа и записей."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from sqlalchemy import Row
from sqlalchemy.orm import Query, Session

from app.db.models import Admin, User


def get_users_activity(
    db: Session, usernames: list[str], *, admin_username: str | None
) -> list[dict[str, str | datetime | None]]:
    """None admin_username используется только для sudo вызывающего API."""
    query = cast(
        Query[Row[str, datetime | None]], db.query(User.username, User.online_at).filter(User.username.in_(usernames))
    )
    if admin_username is not None:
        query = query.join(User.admin).filter(Admin.username == admin_username)
    return [{"username": username, "online_at": online_at} for username, online_at in query.all()]
