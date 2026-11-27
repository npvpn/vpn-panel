"""Сборка TorrentContext из БД. Чистый матч хостов — в torrent_context.py."""

from datetime import UTC, datetime

from app.db import Session
from app.services.torrent_block import active_blocked_node_ids
from app.subscription.torrent_context import TorrentContext
from app.xray.bs_limit import bs_stub_remark


def build_torrent_context(
    db: Session,
    user_id: int,
    *,
    is_revoked: bool,
    is_expired: bool,
    bot_settings: dict,
    now: datetime | None = None,
) -> TorrentContext:
    """Для отозванной и истёкшей подписки заглушка статуса и так заменяет серверы."""
    if is_revoked or is_expired:
        return TorrentContext.empty()
    blocked_node_ids = frozenset(active_blocked_node_ids(db, user_id, now or datetime.now(UTC).replace(tzinfo=None)))
    return TorrentContext(
        blocked_node_ids=blocked_node_ids,
        stub_text=bs_stub_remark(bot_settings.get("sub_torrent_block_server_text")) if blocked_node_ids else "",
    )
