"""xray template versions

NPVPN-2024: три плоских ключа клиентского конфига переезжают в документы с
лентой версий; выбор routing отвязывается от булева nodes.is_bs.

Revision ID: 6f9ee5710f34
Revises: 03e94a203122
Create Date: 2026-09-11 17:42:04.396217

"""

import json
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "6f9ee5710f34"
down_revision = "03e94a203122"
branch_labels = None
depends_on = None

FLAT_KEYS = {
    "v2ray_json": "sub_v2ray_json_template",
    "default": "sub_routing_json_default",
    "bs": "sub_routing_json_bs",
}
TITLES = {
    "v2ray_json": "v2ray-json шаблон",
    "default": "Обычные ноды",
    "bs": "БС-ноды",
}
KINDS = {"v2ray_json": "template", "default": "routing_profile", "bs": "routing_profile"}


def _panel_data(conn) -> dict:
    raw = conn.execute(sa.text('SELECT data FROM global_settings WHERE "key" = :k'), {"k": "panel"}).scalar()
    if not raw:
        return {}
    return raw if isinstance(raw, dict) else json.loads(raw)


def _write_panel_data(conn, data: dict) -> None:
    conn.execute(
        sa.text('UPDATE global_settings SET data = :d WHERE "key" = :k'),
        {"d": json.dumps(data), "k": "panel"},
    )


def _migrate_data(op_like) -> None:
    """Перенос: ключи → документы + версия 1; is_bs=1 → профиль bs; ключи вычищаются."""
    conn = op_like.get_bind()
    data = _panel_data(conn)
    now = datetime.utcnow()
    slug_to_id: dict[str, int] = {}
    for slug, key in FLAT_KEYS.items():
        conn.execute(
            sa.text(
                "INSERT INTO xray_templates (kind, slug, title, created_at, updated_at) "
                "VALUES (:kind, :slug, :title, :now, :now)"
            ),
            {"kind": KINDS[slug], "slug": slug, "title": TITLES[slug], "now": now},
        )
        template_id = conn.execute(
            sa.text("SELECT id FROM xray_templates WHERE slug = :slug"), {"slug": slug}
        ).scalar_one()
        slug_to_id[slug] = template_id
        conn.execute(
            sa.text(
                "INSERT INTO xray_template_versions "
                "(template_id, version, body, comment, author_admin_id, author_username, created_at) "
                "VALUES (:tid, 1, :body, :comment, NULL, 'migration', :now)"
            ),
            {
                "tid": template_id,
                "body": str(data.get(key) or ""),
                "comment": "перенос из настроек панели",
                "now": now,
            },
        )
    conn.execute(
        sa.text("UPDATE nodes SET routing_profile_id = :pid WHERE is_bs = 1"),
        {"pid": slug_to_id["bs"]},
    )
    _write_panel_data(conn, {k: v for k, v in data.items() if k not in FLAT_KEYS.values()})


def _rollback_data(op_like) -> None:
    """Обратный перенос: активные тела документов возвращаются в плоские ключи."""
    conn = op_like.get_bind()
    data = _panel_data(conn)
    for slug, key in FLAT_KEYS.items():
        body = conn.execute(
            sa.text(
                "SELECT v.body FROM xray_template_versions v "
                "JOIN xray_templates t ON t.id = v.template_id "
                "WHERE t.slug = :slug ORDER BY v.version DESC LIMIT 1"
            ),
            {"slug": slug},
        ).scalar()
        data[key] = body or ""
    _write_panel_data(conn, data)


def upgrade() -> None:
    op.create_table(
        "xray_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("title", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "xray_template_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "template_id",
            sa.Integer(),
            sa.ForeignKey("xray_templates.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("body", mysql.LONGTEXT().with_variant(sa.Text(), "sqlite"), nullable=False),
        sa.Column("comment", sa.String(255), nullable=True),
        sa.Column("author_admin_id", sa.Integer(), sa.ForeignKey("admins.id", ondelete="SET NULL"), nullable=True),
        sa.Column("author_username", sa.String(34), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("template_id", "version"),
    )
    op.add_column(
        "nodes",
        sa.Column(
            "routing_profile_id",
            sa.Integer(),
            sa.ForeignKey("xray_templates.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    _migrate_data(op)


def downgrade() -> None:
    _rollback_data(op)
    op.drop_column("nodes", "routing_profile_id")
    op.drop_table("xray_template_versions")
    op.drop_table("xray_templates")
