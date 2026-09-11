"""Сборка BsContext из БД — отдельно от чистого bs_context.py, который про БД не знает."""

from typing import cast

from app.db import Session, crud
from app.db.models import User
from app.subscription.bs_context import BsContext
from app.xray.bs_limit import bs_stub_remark


def build_bs_context(
    db: Session,
    dbuser: User,
    *,
    is_revoked: bool,
    is_expired: bool,
    bot_settings: dict,
) -> BsContext:
    """БС-контекст подписки. Для revoked/expired БС-логика не применяется вовсе."""
    if is_revoked or is_expired:
        return BsContext.empty()
    blocked_node_ids = frozenset(crud.get_blocked_bs_node_ids(db, cast(int, dbuser.id)))
    return BsContext(
        blocked_node_ids=blocked_node_ids,
        # Имя сервера-заглушки нужно только при наличии блоков (и считается от
        # node-id-пути, а не от адресов: доменный БС-хост тоже должен получить имя).
        stub_text=bs_stub_remark(bot_settings["sub_bs_limit_server_text"]) if blocked_node_ids else "",
    )
