import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request

from app import logger
from app.db import Session, get_db
from app.models.torrent_block import TorrentBlockAccepted, TorrentBlockWebhook
from app.services.torrent_block import TorrentBlockRejected, apply_torrent_event
from app.utils.client_ip import get_client_ip
from config import TORRENT_WEBHOOK_TOKEN

router = APIRouter(prefix="/api", tags=["Torrent block"])


def _authorized(header: str | None) -> bool:
    token = TORRENT_WEBHOOK_TOKEN
    if not token:
        return False
    presented = (header or "").strip()
    scheme, _, rest = presented.partition(" ")
    if scheme.lower() == "bearer":
        presented = rest.strip()
    if len(presented) != len(token):
        return False
    return secrets.compare_digest(presented, token)


@router.post("/torrent-block", response_model=TorrentBlockAccepted)
def torrent_block(
    body: TorrentBlockWebhook,
    request: Request,
    db: Session = Depends(get_db),
):
    """Событие tblocker: заблокировать или снять блокировку пользователя на ноде-источнике."""
    if not TORRENT_WEBHOOK_TOKEN:
        raise HTTPException(status_code=503, detail="Torrent webhook is not configured")
    if not _authorized(request.headers.get("Authorization")):
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not body.identity:
        raise HTTPException(status_code=422, detail="username is required")
    try:
        apply_torrent_event(
            db,
            source_ip=get_client_ip(request),
            identity=body.identity,
            action=body.action,
            duration_minutes=body.duration,
            now=datetime.now(UTC).replace(tzinfo=None),
        )
    except TorrentBlockRejected as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    logger.info("torrent webhook action=%s identity=%s", body.action, body.identity)
    return TorrentBlockAccepted()
