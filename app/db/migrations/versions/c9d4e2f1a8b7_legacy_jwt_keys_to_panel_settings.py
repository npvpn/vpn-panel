"""copy SUBSCRIPTION_LEGACY_SECRET_KEYS into panel settings

Revision ID: c9d4e2f1a8b7
Revises: 071beb7b9077
Create Date: 2026-08-28 11:03:12.642118

Legacy /sub/ verification keys lived only in env. Copy them into
global_settings.panel.subscription_legacy_secret_keys so they can be
edited in the dashboard without restarting the panel.
"""

from __future__ import annotations

import json
import os
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision = "c9d4e2f1a8b7"
down_revision = "071beb7b9077"
branch_labels = None
depends_on = None

PANEL_SETTINGS_KEY = "panel"
LEGACY_SECRET_KEYS_SETTING = "subscription_legacy_secret_keys"

DEFAULT_PANEL_SETTINGS = {
    "sub_custom_headers": "",
    "bs_monthly_limit": 0,
    "sub_routing_happ": "",
    "sub_routing_v2raytun": "",
    "sub_v2ray_json_template": "",
    "sub_routing_json_default": "",
    "sub_routing_json_bs": "",
    "subscription_legacy_secret_keys": [],
}


def _parse_json(data):
    if isinstance(data, (bytes, bytearray)):
        data = data.decode("utf-8")
    if isinstance(data, str):
        return json.loads(data) if data.strip() else {}
    return dict(data or {})


def _dump_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _env_legacy_keys() -> list[str]:
    raw = os.environ.get("SUBSCRIPTION_LEGACY_SECRET_KEYS", "") or ""
    seen: set[str] = set()
    out: list[str] = []
    for item in raw.split(","):
        key = item.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _normalize_legacy_keys(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = value.split(",")
    elif isinstance(value, (list, tuple)):
        items = value
    else:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = str(item or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


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
    gs = _global_settings_table()
    env_keys = _env_legacy_keys()
    now = datetime.utcnow()

    row = bind.execute(sa.select(gs.c.data).where(gs.c.key == PANEL_SETTINGS_KEY)).fetchone()
    if row is None:
        if not env_keys:
            return
        payload = dict(DEFAULT_PANEL_SETTINGS)
        payload[LEGACY_SECRET_KEYS_SETTING] = env_keys
        bind.execute(
            sa.insert(gs).values(
                {
                    "key": PANEL_SETTINGS_KEY,
                    "data": _dump_json(payload),
                    "created_at": now,
                    "updated_at": now,
                }
            )
        )
        return

    payload = _parse_json(row[0])
    existing = _normalize_legacy_keys(payload.get(LEGACY_SECRET_KEYS_SETTING)) if LEGACY_SECRET_KEYS_SETTING in payload else []
    if existing:
        if payload.get(LEGACY_SECRET_KEYS_SETTING) != existing:
            payload[LEGACY_SECRET_KEYS_SETTING] = existing
            bind.execute(
                sa.update(gs).where(gs.c.key == PANEL_SETTINGS_KEY).values(
                    data=_dump_json(payload), updated_at=now
                )
            )
        return
    if not env_keys and LEGACY_SECRET_KEYS_SETTING in payload:
        return
    payload[LEGACY_SECRET_KEYS_SETTING] = env_keys
    bind.execute(
        sa.update(gs).where(gs.c.key == PANEL_SETTINGS_KEY).values(data=_dump_json(payload), updated_at=now)
    )


def downgrade() -> None:
    bind = op.get_bind()
    gs = _global_settings_table()
    row = bind.execute(sa.select(gs.c.data).where(gs.c.key == PANEL_SETTINGS_KEY)).fetchone()
    if row is None:
        return
    payload = _parse_json(row[0])
    if LEGACY_SECRET_KEYS_SETTING not in payload:
        return
    payload.pop(LEGACY_SECRET_KEYS_SETTING, None)
    bind.execute(
        sa.update(gs)
        .where(gs.c.key == PANEL_SETTINGS_KEY)
        .values(data=_dump_json(payload), updated_at=datetime.utcnow())
    )
