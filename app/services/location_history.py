"""Observed validity intervals for the configured location pool of each bot."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.models import Bot, LocationMembership
from app.services.address_history import _audience_locations, _location_catalog
from app.xray.address_policy import ARCHIVE_RETENTION_DAYS


def refresh_membership(db: Session, tags=None, *, now=None):
    # Serialize before reading topology so a slower worker cannot restore a stale pool.
    if db.get_bind().dialect.name == "mysql":
        db.execute(text("SELECT id FROM location_refresh_lock WHERE id = 1 FOR UPDATE")).one()
    elif db.get_bind().dialect.name == "sqlite":
        db.execute(text("UPDATE location_refresh_lock SET id = id WHERE id = 1"))
    now = now or datetime.now(UTC).replace(tzinfo=None)
    if tags is None:
        from app import xray

        tags = set(xray.config.inbounds_by_tag)
    catalog = _location_catalog(db, tags)
    by_id = {item["host"]["id"]: item for item in catalog}
    current = {
        (r.bot_id, r.host_id, r.source_host_id, r.address): r
        for r in db.query(LocationMembership).filter_by(valid_until=None)
    }
    bots: list[tuple[int, str | None]] = list(db.execute(select(Bot.id, Bot.username)).tuples())
    for bot_id, username in bots or [(0, None)]:
        for location in _audience_locations(catalog, username, set(), len(bots)):
            parent = by_id[location.host_id]
            if parent["host"]["is_hidden"]:
                continue
            for entry in location.entries:
                key = (bot_id, location.host_id, entry.source_host_id, entry.address)
                values = dict(
                    node_id=entry.node_id,
                    remark=location.remark,
                    source_name=entry.source_name,
                    inbound=parent["inbound"],
                    source_inbound=by_id[entry.source_host_id]["inbound"],
                    composite=location.composite,
                )
                old = current.pop(key, None)
                if old is not None:
                    if all(getattr(old, k) == v for k, v in values.items()):
                        continue
                    old.valid_until = now
                db.add(
                    LocationMembership(
                        bot_id=bot_id,
                        host_id=location.host_id,
                        source_host_id=entry.source_host_id,
                        address=entry.address,
                        valid_from=now,
                        **values,
                    )
                )
    for old in current.values():
        old.valid_until = now
    db.query(LocationMembership).filter(
        LocationMembership.valid_until < now - timedelta(days=ARCHIVE_RETENTION_DAYS)
    ).delete(synchronize_session=False)
    db.flush()


def record_membership():
    from app.db import GetDB

    with GetDB() as db:
        refresh_membership(db)
        db.commit()


def topology_changed():
    from app import scheduler

    if scheduler.running:
        from app import logger

        try:
            record_membership()
        except Exception:
            logger.exception("Location history refresh failed, scheduled snapshot will retry")
