"""move panel settings out of bot_settings

Revision ID: d7e9f1a2b3c4
Revises: 8a985b0c7775
Create Date: 2026-08-14 12:40:42.423120

"""
import json
from datetime import datetime

import sqlalchemy as sa
from alembic import op
  
revision = "d7e9f1a2b3c4"
down_revision = "8a985b0c7775"
branch_labels = None
depends_on = None

PANEL_SETTINGS_KEY = "panel"

PANEL_STRING_KEYS = (
    "sub_custom_headers",
    "sub_routing_happ",
    "sub_routing_v2raytun",
    "sub_v2ray_json_template",
    "sub_routing_json_default",
    "sub_routing_json_bs",
)
PANEL_KEYS = (*PANEL_STRING_KEYS, "bs_monthly_limit")

DEFAULT_PANEL_SETTINGS = {
    "sub_custom_headers": "",
    "bs_monthly_limit": 0,
    "sub_routing_happ": "",
    "sub_routing_v2raytun": "",
    "sub_v2ray_json_template": "",
    "sub_routing_json_default": "",
    "sub_routing_json_bs": "",
}


def _parse_json(data):
    if isinstance(data, (bytes, bytearray)):
        data = data.decode("utf-8")
    if isinstance(data, str):
        return json.loads(data) if data.strip() else {}
    return dict(data or {})


def _is_filled(key, value) -> bool:
    if key == "bs_monthly_limit":
        try:
            return int(value or 0) != 0
        except (TypeError, ValueError):
            return False
    return bool(str(value or "").strip())


def _load_bot_rows(bind):
    rows = bind.execute(sa.text("SELECT bot_id, data FROM bot_settings ORDER BY bot_id")).fetchall()
    parsed = []
    for bot_id, data in rows:
        parsed.append((bot_id, _parse_json(data)))
    return parsed


def _pick_panel_settings(bot_rows) -> dict:
    settings = dict(DEFAULT_PANEL_SETTINGS)
    filled = set()
    for _bot_id, payload in bot_rows:
        for key in PANEL_KEYS:
            if key in filled:
                continue
            if key not in payload:
                continue
            value = payload[key]
            if not _is_filled(key, value):
                continue
            if key == "bs_monthly_limit":
                settings[key] = int(value or 0)
            else:
                settings[key] = value if value is not None else ""
            filled.add(key)
        if len(filled) == len(PANEL_KEYS):
            break
    return settings


def _strip_panel_keys(payload: dict) -> dict:
    cleaned = dict(payload)
    for key in PANEL_KEYS:
        cleaned.pop(key, None)
    return cleaned


def _dump_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _global_settings_table():
    # `key` — зарезервированное слово MySQL; sa.column экранирует его сам.
    return sa.table(
        "global_settings",
        sa.column("key"),
        sa.column("data"),
        sa.column("created_at"),
        sa.column("updated_at"),
    )


def upgrade() -> None:
    bind = op.get_bind()
    bot_rows = _load_bot_rows(bind)
    panel = _pick_panel_settings(bot_rows)
    now = datetime.utcnow()
    gs = _global_settings_table()
    dumped = _dump_json(panel)

    existing = bind.execute(sa.select(gs.c.key).where(gs.c.key == PANEL_SETTINGS_KEY)).fetchone()
    if existing is None:
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
        bind.execute(
            sa.update(gs).where(gs.c.key == PANEL_SETTINGS_KEY).values(data=dumped, updated_at=now)
        )

    for bot_id, payload in bot_rows:
        cleaned = _strip_panel_keys(payload)
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
    panel = _parse_json(row[0]) if row else dict(DEFAULT_PANEL_SETTINGS)
    snapshot = {key: panel.get(key, DEFAULT_PANEL_SETTINGS[key]) for key in PANEL_KEYS}

    for bot_id, payload in _load_bot_rows(bind):
        merged = dict(payload)
        merged.update(snapshot)
        bind.execute(
            sa.text("UPDATE bot_settings SET data = :data WHERE bot_id = :bot_id"),
            {"data": _dump_json(merged), "bot_id": bot_id},
        )

    bind.execute(sa.delete(gs).where(gs.c.key == PANEL_SETTINGS_KEY))
