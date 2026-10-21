"""move subscription announce/server texts to panel settings

Revision ID: c8a1b23e4f5
Revises: b1c2d3e4f5a6
Create Date: 2026-10-15 16:31:19.100255

Тексты объявлений и серверов становятся общими на всю панель.
Берём значения первого бота (минимальный bot_id); если ботов нет — заводские.
Ключи вычищаются из всех bot_settings. Существующий JSON `panel` дополняется,
не перезаписывается целиком.
"""

import json
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision = "c8a1b23e4f5"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None

PANEL_SETTINGS_KEY = "panel"

_DEFAULT_ANNOUNCE = (
    "• ID ПОЛЬЗОВАТЕЛЯ: <tg_id> •\n"
    "• ↖️ ССЫЛКА ДЛЯ УПРАВЛЕНИЯ ПОДПИСКОЙ • ССЫЛКА ПОДДЕРЖКИ ↗️  •\n"
    "• Не работает VPN? Нажмите на кнопку 🔁👆 •"
)

ANNOUNCE_KEYS = (
    "sub_client_note",
    "sub_revoked_announce_text",
    "sub_expired_announce_text",
    "sub_device_limit_announce_text",
    "sub_unsupported_client_announce_text",
    "sub_bs_limit_announce_text",
)
SERVER_KEYS = (
    "sub_revoked_server_text",
    "sub_expired_server_text",
    "sub_device_limit_server_text",
    "sub_unsupported_client_server_text",
    "sub_bs_limit_server_text",
)
MESSAGE_KEYS = (*ANNOUNCE_KEYS, *SERVER_KEYS)

DEFAULT_MESSAGES = {
    "sub_client_note": _DEFAULT_ANNOUNCE,
    "sub_revoked_announce_text": _DEFAULT_ANNOUNCE,
    "sub_expired_announce_text": _DEFAULT_ANNOUNCE,
    "sub_device_limit_announce_text": _DEFAULT_ANNOUNCE,
    "sub_unsupported_client_announce_text": _DEFAULT_ANNOUNCE,
    "sub_bs_limit_announce_text": _DEFAULT_ANNOUNCE,
    "sub_revoked_server_text": ["Эта ссылка не активна", "Обновите ссылку в боте"],
    "sub_expired_server_text": ["Подписка истекла", "Продлите подписку в боте"],
    "sub_device_limit_server_text": ["Достигнут лимит устройств", "Удалите старое устройство"],
    "sub_unsupported_client_server_text": ["Это приложение не поддерживается", "Установите другое"],
    "sub_bs_limit_server_text": [],
}


def _parse_json(data):
    if isinstance(data, (bytes, bytearray)):
        data = data.decode("utf-8")
    if isinstance(data, str):
        return json.loads(data) if data.strip() else {}
    return dict(data or {})


def _dump_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _normalize_server_text(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.replace("\n", ",").split(",") if item.strip()]
    return []


def _pick_messages(bot_rows) -> dict:
    picked = {key: (list(value) if isinstance(value, list) else value) for key, value in DEFAULT_MESSAGES.items()}
    if not bot_rows:
        return picked
    _bot_id, payload = bot_rows[0]
    for key in ANNOUNCE_KEYS:
        if key not in payload or payload[key] is None:
            continue
        text = str(payload[key] or "")
        if text.strip():
            picked[key] = text
    for key in SERVER_KEYS:
        if key not in payload:
            continue
        lines = _normalize_server_text(payload[key])
        if lines or key == "sub_bs_limit_server_text":
            picked[key] = lines
    return picked


def _strip_message_keys(payload: dict) -> dict:
    cleaned = dict(payload)
    for key in MESSAGE_KEYS:
        cleaned.pop(key, None)
    return cleaned


def _load_bot_rows(bind):
    rows = bind.execute(sa.text("SELECT bot_id, data FROM bot_settings ORDER BY bot_id")).fetchall()
    parsed = []
    for bot_id, data in rows:
        parsed.append((bot_id, _parse_json(data)))
    return parsed


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
    messages = _pick_messages(_load_bot_rows(bind))
    now = datetime.utcnow()
    gs = _global_settings_table()
    row = bind.execute(sa.select(gs.c.data).where(gs.c.key == PANEL_SETTINGS_KEY)).fetchone()
    panel = _parse_json(row[0]) if row else {}
    panel.update(messages)
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
        bind.execute(
            sa.update(gs).where(gs.c.key == PANEL_SETTINGS_KEY).values(data=dumped, updated_at=now)
        )

    for bot_id, payload in _load_bot_rows(bind):
        cleaned = _strip_message_keys(payload)
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
    snapshot = {}
    for key in ANNOUNCE_KEYS:
        snapshot[key] = panel.get(key, DEFAULT_MESSAGES[key])
    for key in SERVER_KEYS:
        snapshot[key] = _normalize_server_text(panel.get(key, DEFAULT_MESSAGES[key]))

    for bot_id, payload in _load_bot_rows(bind):
        merged = dict(payload)
        merged.update(snapshot)
        bind.execute(
            sa.text("UPDATE bot_settings SET data = :data WHERE bot_id = :bot_id"),
            {"data": _dump_json(merged), "bot_id": bot_id},
        )

    if row is not None:
        cleaned = _strip_message_keys(panel)
        bind.execute(
            sa.update(gs)
            .where(gs.c.key == PANEL_SETTINGS_KEY)
            .values(data=_dump_json(cleaned), updated_at=datetime.utcnow())
        )
