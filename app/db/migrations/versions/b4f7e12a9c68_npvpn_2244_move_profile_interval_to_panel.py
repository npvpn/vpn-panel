"""NPVPN-2244 move profile update interval to panel settings

Revision ID: b4f7e12a9c68
Revises: c7e4a91b2366
Create Date: 2026-11-23 14:00:00.000000

The interval is shared by every subscription in a panel and comes from
SUB_UPDATE_INTERVAL when the panel setting is empty. This migration only
removes the old per-service copies. It does not write an hour into panel
settings: a fresh install must keep the environment default.
"""

import json
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision = "b4f7e12a9c68"
down_revision = "c7e4a91b2366"
branch_labels = None
depends_on = None

PANEL_SETTINGS_KEY = "panel"
UPDATE_INTERVAL_KEY = "sub_update_interval"
DEFAULT_UPDATE_INTERVAL = "12"


def _parse_json(data):
    if data is None:
        return {}
    if isinstance(data, (bytes, bytearray)):
        data = data.decode("utf-8")
    if isinstance(data, str):
        return json.loads(data) if data.strip() else {}
    return dict(data)


def _dump_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _global_settings_table():
    return sa.table(
        "global_settings",
        sa.column("key"),
        sa.column("data"),
        sa.column("created_at"),
        sa.column("updated_at"),
    )


def _strip_interval(payload: dict) -> dict:
    cleaned = dict(payload)
    cleaned.pop(UPDATE_INTERVAL_KEY, None)
    return cleaned


def upgrade() -> None:
    bind = op.get_bind()
    for bot_id, data in bind.execute(sa.text("SELECT bot_id, data FROM bot_settings")).fetchall():
        payload = _parse_json(data)
        cleaned = _strip_interval(payload)
        if cleaned != payload:
            bind.execute(
                sa.text("UPDATE bot_settings SET data = :data WHERE bot_id = :bot_id"),
                {"data": _dump_json(cleaned), "bot_id": bot_id},
            )


def downgrade() -> None:
    bind = op.get_bind()
    now = datetime.utcnow()
    gs = _global_settings_table()
    row = bind.execute(sa.select(gs.c.data).where(gs.c.key == PANEL_SETTINGS_KEY)).fetchone()
    panel = _parse_json(row[0]) if row else {}
    if not isinstance(panel, dict):
        panel = {}
    if UPDATE_INTERVAL_KEY not in panel:
        return
    interval = str(panel.get(UPDATE_INTERVAL_KEY) or DEFAULT_UPDATE_INTERVAL)

    for bot_id, data in bind.execute(sa.text("SELECT bot_id, data FROM bot_settings")).fetchall():
        payload = _parse_json(data)
        payload[UPDATE_INTERVAL_KEY] = interval
        bind.execute(
            sa.text("UPDATE bot_settings SET data = :data WHERE bot_id = :bot_id"),
            {"data": _dump_json(payload), "bot_id": bot_id},
        )

    if row is not None:
        bind.execute(
            sa.update(gs)
            .where(gs.c.key == PANEL_SETTINGS_KEY)
            .values(data=_dump_json(_strip_interval(panel)), updated_at=now)
        )
