"""add order to hosts

Revision ID: c4f8a1b2d3e5
Revises: b6e1d4f8a2c7
Create Date: 2026-08-11 11:06:51.150403

"""
import json
import os
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "c4f8a1b2d3e5"
down_revision = "b6e1d4f8a2c7"
branch_labels = None
depends_on = None


def _xray_inbound_tags() -> list[str]:
    """Теги инбаундов в порядке xray_config — как сейчас в подписке."""
    path = os.environ.get("XRAY_JSON") or "./xray_config.json"
    config_path = Path(path)
    if not config_path.is_file():
        # alembic часто запускают из panel/; пробуем относительно корня репо/панели
        for candidate in (Path("xray_config.json"), Path("panel/xray_config.json")):
            if candidate.is_file():
                config_path = candidate
                break
        else:
            return []

    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    tags = []
    for inbound in data.get("inbounds") or []:
        tag = inbound.get("tag")
        if tag and tag not in tags:
            tags.append(tag)
    return tags


def _backfill(bind) -> None:
    """Проставить order = 0..N-1 в текущем порядке подписки (inbound config → host.id)."""
    config_tags = _xray_inbound_tags()
    rows = bind.execute(
        sa.text('SELECT id, inbound_tag FROM hosts ORDER BY id')
    ).fetchall()
    if not rows:
        return

    by_tag: dict[str, list[int]] = {}
    for row in rows:
        by_tag.setdefault(row.inbound_tag, []).append(row.id)

    ordered_ids: list[int] = []
    seen_tags: set[str] = set()
    for tag in config_tags:
        if tag in by_tag:
            ordered_ids.extend(by_tag[tag])
            seen_tags.add(tag)

    for tag in sorted(t for t in by_tag if t not in seen_tags):
        ordered_ids.extend(by_tag[tag])

    hosts_table = sa.table(
        "hosts",
        sa.column("id", sa.Integer),
        sa.column("order", sa.Integer),
    )
    for order_value, host_id in enumerate(ordered_ids):
        bind.execute(
            sa.update(hosts_table).where(hosts_table.c.id == host_id).values(order=order_value)
        )


def upgrade() -> None:
    with op.batch_alter_table("hosts") as batch_op:
        batch_op.add_column(
            sa.Column("order", sa.Integer(), nullable=False, server_default="0")
        )

    _backfill(op.get_bind())


def downgrade() -> None:
    with op.batch_alter_table("hosts") as batch_op:
        batch_op.drop_column("order")
