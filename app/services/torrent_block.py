"""Вебхук tblocker: кто заблокирован, на какой ноде и до какого времени.

Нода узнаётся по IP входящего запроса, пользователь — по email из лога Xray
`{id}.{username}`. Срок хранится в torrent_user_blocks и сам снимает заглушку
подписки, когда blocked_until проходит. unblock удаляет строку раньше срока.
"""

from __future__ import annotations

import ipaddress
from datetime import datetime, timedelta
from typing import cast

from sqlalchemy.orm import Session

from app.db.models import Node, TorrentUserBlock, User


class TorrentBlockRejected(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def parse_log_email(raw: str) -> tuple[int, str] | None:
    """`{id}.{username}` из поля email лога Xray. Username может содержать точки."""
    user_id, separator, username = (raw or "").strip().partition(".")
    if not separator or not user_id.isdigit() or not username:
        return None
    return int(user_id), username


def normalize_ip(value: str | None) -> str | None:
    if not value:
        return None
    try:
        ip = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        return str(ip.ipv4_mapped)
    return str(ip)


def node_ids_for_source_ip(db: Session, source_ip: str) -> list[int]:
    wanted = normalize_ip(source_ip)
    if wanted is None:
        return []
    rows = cast(list[tuple[int, str | None]], db.query(Node.id, Node.address).all())
    return [node_id for node_id, address in rows if normalize_ip(address) == wanted]


def active_blocked_node_ids(db: Session, user_id: int, now: datetime) -> set[int]:
    # Сравнение Column > datetime mypy видит как bool; в запросе это условие SQL.
    rows = cast(
        list[tuple[int]],
        db.query(TorrentUserBlock.node_id)
        .filter(
            TorrentUserBlock.user_id == user_id,
            TorrentUserBlock.blocked_until > now,  # type: ignore[arg-type]
        )
        .all(),
    )
    return {node_id for (node_id,) in rows}


def apply_torrent_event(
    db: Session,
    *,
    source_ip: str,
    identity: str,
    action: str,
    duration_minutes: int,
    now: datetime,
) -> None:
    parsed = parse_log_email(identity)
    if parsed is None:
        raise TorrentBlockRejected(422, "username must be '{id}.{username}'")
    user_id, username = parsed
    user = db.query(User.id).filter(User.id == user_id, User.username == username).one_or_none()
    if user is None:
        raise TorrentBlockRejected(404, "user not found")
    node_ids = node_ids_for_source_ip(db, source_ip)
    if not node_ids:
        raise TorrentBlockRejected(404, "node not found")

    if action == "unblock":
        (
            db.query(TorrentUserBlock)
            .filter(TorrentUserBlock.user_id == user_id, TorrentUserBlock.node_id.in_(node_ids))
            .delete(synchronize_session=False)
        )
        db.commit()
        return

    if duration_minutes <= 0:
        raise TorrentBlockRejected(422, "duration must be positive")
    until = now + timedelta(minutes=duration_minutes)
    existing = {
        row.node_id: row
        for row in db.query(TorrentUserBlock)
        .filter(TorrentUserBlock.user_id == user_id, TorrentUserBlock.node_id.in_(node_ids))
        .all()
    }
    for node_id in node_ids:
        row = existing.get(node_id)
        if row is None:
            db.add(TorrentUserBlock(node_id=node_id, user_id=user_id, blocked_until=until))
        else:
            row.blocked_until = until
    db.commit()
