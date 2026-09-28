"""Сборка BsContext из БД — отдельно от чистого bs_context.py, который про БД не знает."""

from datetime import datetime
from typing import cast

from app.db import Session, crud
from app.db.models import User
from app.subscription.bs_context import BsContext
from app.xray.bs_limit import bs_stub_remark, format_bs_usage_suffix, monthly_effective_limit, period_keys


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


def load_bs_usage_suffix(db: Session, user_id: int, monthly_limit: int) -> str:
    """Суффикс имени БС-хоста. Вызывать только если лимит > 0 и хост реально выдаётся."""
    yyyymm = period_keys(datetime.utcnow())
    pool = crud.normalize_bs_extra_period(db, user_id, monthly_limit, yyyymm, persist=False)
    used = crud.get_bs_usage_totals(db, user_id, yyyymm)
    return format_bs_usage_suffix(used, monthly_effective_limit(monthly_limit, pool))
