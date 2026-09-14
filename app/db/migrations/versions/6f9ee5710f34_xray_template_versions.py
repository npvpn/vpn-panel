"""xray template versions

NPVPN-2024: три плоских ключа клиентского конфига переезжают в документы с
лентой версий; выбор routing переезжает на `hosts.client_config_id` и
отвязывается от булева nodes.is_bs.

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


def _global_settings_table():
    # `key` — зарезервированное слово в MySQL: без явного sa.table/sa.column
    # SQLAlchemy само кавычит идентификатор под диалект (в MySQL — обратными
    # кавычками). Сырой SQL с двойными кавычками компилируется в строковый
    # литерал 'key' = 'panel' (без ANSI_QUOTES) и условие всегда ложно —
    # см. app/db/migrations/versions/c9d4e2f1a8b7_legacy_jwt_keys_to_panel_settings.py.
    return sa.table(
        "global_settings",
        sa.column("key"),
        sa.column("data"),
        sa.column("created_at"),
        sa.column("updated_at"),
    )


def _panel_data(conn) -> dict:
    gs = _global_settings_table()
    raw = conn.execute(sa.select(gs.c.data).where(gs.c.key == "panel")).scalar()
    if not raw:
        return {}
    return raw if isinstance(raw, dict) else json.loads(raw)


def _write_panel_data(conn, data: dict) -> None:
    """Upsert: строки `key='panel'` может не быть на свежей установке (сеется
    только `client_apps`, см. af83ddaadbe7_add_global_settings.py)."""
    gs = _global_settings_table()
    now = datetime.utcnow()
    payload = json.dumps(data)
    result = conn.execute(sa.update(gs).where(gs.c.key == "panel").values(data=payload, updated_at=now))
    if result.rowcount == 0:
        conn.execute(sa.insert(gs).values(key="panel", data=payload, created_at=now, updated_at=now))


HOSTS_FK_NAME = "fk_hosts_client_config_id_xray_templates"


def _add_client_config_column(op_like) -> None:
    """Колонка профиля у хоста + ИМЕНОВАННЫЙ FK.

    Безымянный sa.ForeignKey внутри add_column MySQL называет сам (hosts_ibfk_N), и
    downgrade потом не может его снять: drop_column упирается в ERROR 1828 «Cannot drop
    column ... needed in a foreign key constraint». На sqlite этого не видно.
    """
    with op_like.batch_alter_table("hosts") as batch_op:
        batch_op.add_column(sa.Column("client_config_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            HOSTS_FK_NAME,
            "xray_templates",
            ["client_config_id"],
            ["id"],
            ondelete="SET NULL",
        )


def _drop_client_config_column(op_like) -> None:
    """Снять FK и только потом колонку — иначе MySQL отвечает ERROR 1828."""
    with op_like.batch_alter_table("hosts") as batch_op:
        batch_op.drop_constraint(HOSTS_FK_NAME, type_="foreignkey")
        batch_op.drop_column("client_config_id")


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
    # Профиль `bs` получают хосты, у которых через host_nodes привязана хотя бы одна
    # нода с is_bs=1 — ровно та ANY-семантика, по которой БС-признак хоста определялся
    # до переезда. Поэтому рендер подписки после миграции не меняется.
    conn.execute(
        sa.text(
            "UPDATE hosts SET client_config_id = :pid WHERE id IN ("
            "SELECT hn.host_id FROM host_nodes hn JOIN nodes n ON n.id = hn.node_id "
            "WHERE n.is_bs = 1)"
        ),
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
    _add_client_config_column(op)
    _migrate_data(op)


def downgrade() -> None:
    _rollback_data(op)
    _drop_client_config_column(op)
    op.drop_table("xray_template_versions")
    op.drop_table("xray_templates")
