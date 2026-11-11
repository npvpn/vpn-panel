"""npvpn_2365 panel hard stub

Revision ID: f3c8a91e2b47
Revises: 2c56a4b408b4
Create Date: 2026-11-11 15:55:43.651040

Жёсткая заглушка становится общей на всю панель.
Берём значение первого бота (минимальный bots.id); если ботов нет — выключено.
Ключ вычищается из всех bot_settings. Существующий JSON `panel` дополняется,
не перезаписывается целиком.
"""

import json
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision = "f3c8a91e2b47"
down_revision = "2c56a4b408b4"
branch_labels = None
depends_on = None

PANEL_SETTINGS_KEY = "panel"
HARD_MODE_KEY = "sub_device_limit_hard_mode"


def _parse_json(data):
    if data is None:
        return None
    if isinstance(data, (bytes, bytearray)):
        data = data.decode("utf-8")
    if isinstance(data, str):
        return json.loads(data) if data.strip() else {}
    return dict(data)


def _dump_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def pick_hard_mode(rows) -> bool:
    if not rows:
        return False
    _bot_id, payload = min(rows, key=lambda row: row[0])
    if isinstance(payload, dict) and HARD_MODE_KEY in payload:
        return bool(payload[HARD_MODE_KEY])
    return False


def strip_hard_mode(payload: dict) -> dict:
    cleaned = dict(payload)
    cleaned.pop(HARD_MODE_KEY, None)
    return cleaned


def _load_bot_rows(bind):
    rows = bind.execute(
        sa.text("SELECT b.id, s.data FROM bots b LEFT JOIN bot_settings s ON s.bot_id = b.id ORDER BY b.id")
    ).fetchall()
    return [(bot_id, _parse_json(data)) for bot_id, data in rows]


def _global_settings_table():
    return sa.table(
        "global_settings",
        sa.column("key"),
        sa.column("data"),
        sa.column("created_at"),
        sa.column("updated_at"),
    )


def upgrade() -> None:
    bind = op.get_bind()
    enabled = pick_hard_mode(_load_bot_rows(bind))
    now = datetime.utcnow()
    gs = _global_settings_table()
    row = bind.execute(sa.select(gs.c.data).where(gs.c.key == PANEL_SETTINGS_KEY)).fetchone()
    panel = _parse_json(row[0]) if row else {}
    if panel is None:
        panel = {}
    panel[HARD_MODE_KEY] = enabled
    dumped = _dump_json(panel)

    if row is None:
        bind.execute(
            sa.insert(gs).values(
                {
                    "key": PANEL_SETTINGS_KEY,
                    "data": dumped,
                    "created_at": now,
                    "updated_at": now,
                }
            )
        )
    else:
        bind.execute(sa.update(gs).where(gs.c.key == PANEL_SETTINGS_KEY).values(data=dumped, updated_at=now))

    settings_rows = bind.execute(sa.text("SELECT bot_id, data FROM bot_settings")).fetchall()
    for bot_id, data in settings_rows:
        payload = _parse_json(data) or {}
        cleaned = strip_hard_mode(payload)
        if cleaned == payload:
            continue
        bind.execute(
            sa.text("UPDATE bot_settings SET data = :data WHERE bot_id = :bot_id"),
            {"data": _dump_json(cleaned), "bot_id": bot_id},
        )


def downgrade() -> None:
    bind = op.get_bind()
    gs = _global_settings_table()
    row = bind.execute(sa.select(gs.c.data).where(gs.c.key == PANEL_SETTINGS_KEY)).fetchone()
    panel = _parse_json(row[0]) if row else {}
    if not isinstance(panel, dict):
        panel = {}
    enabled = bool(panel.get(HARD_MODE_KEY, False))
    now = datetime.utcnow()

    settings_rows = bind.execute(sa.text("SELECT bot_id, data FROM bot_settings")).fetchall()
    for bot_id, data in settings_rows:
        payload = _parse_json(data) or {}
        payload[HARD_MODE_KEY] = enabled
        bind.execute(
            sa.text("UPDATE bot_settings SET data = :data WHERE bot_id = :bot_id"),
            {"data": _dump_json(payload), "bot_id": bot_id},
        )

    if row is not None:
        cleaned = strip_hard_mode(panel)
        bind.execute(
            sa.update(gs).where(gs.c.key == PANEL_SETTINGS_KEY).values(data=_dump_json(cleaned), updated_at=now)
        )
