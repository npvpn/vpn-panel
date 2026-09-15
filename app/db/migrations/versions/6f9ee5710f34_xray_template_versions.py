"""xray template versions

NPVPN-2024: три плоских ключа клиентского конфига переезжают в ДВА самодостаточных
документа (`default`, `bs`) с лентой версий; выбор конфига переезжает на
`hosts.client_config_id` и отвязывается от булева nodes.is_bs.

Revision ID: 6f9ee5710f34
Revises: 03e94a203122
Create Date: 2026-09-11 17:42:04.396217

"""

import json
import logging
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

logger = logging.getLogger("alembic.runtime.migration")

revision = "6f9ee5710f34"
down_revision = "03e94a203122"
branch_labels = None
depends_on = None

FLAT_TEMPLATE_KEY = "sub_v2ray_json_template"
FLAT_ROUTING_KEYS = {"default": "sub_routing_json_default", "bs": "sub_routing_json_bs"}
FLAT_KEYS = (FLAT_TEMPLATE_KEY, *FLAT_ROUTING_KEYS.values())
TITLES = {"default": "Обычные ноды", "bs": "БС-ноды"}


def _file_template_body() -> str:
    """Файловый клиентский шаблон как база склейки.

    Нужен для реального случая «шаблон не переопределяли, а sub_routing_json_bs
    заполнен»: до переезда такой хост получал ФАЙЛОВЫЙ шаблон с вклеенным routing,
    и без этой базы самодостаточный конфиг БС-нод потерял бы всё, кроме routing.
    """
    from app.templates import render_template
    from config import V2RAY_SUBSCRIPTION_TEMPLATE

    return render_template(V2RAY_SUBSCRIPTION_TEMPLATE)


def _safe_file_template() -> dict | None:
    """Файловый шаблон как JSON-объект или None, но НИКОГДА исключение.

    Это БОЕВОЙ путь, а не защитное программирование: на проде `sub_v2ray_json_template`
    пуст при заполненном `sub_routing_json_bs`, поэтому база склейки берётся именно
    отсюда. Каталог шаблонов там смонтирован томом с хоста, так что файла может не
    оказаться на месте (пустой том) или он может быть испорчен руками — а `render_template`
    бросает `TemplateNotFound`, `json.loads` — `ValueError`, и любое из них уронило бы
    `upgrade()` посреди DDL, оставив панель неподнимаемой (см. `_safe_json_object`).

    None означает «базы нет»: вызывающий сохранит тело как есть, и routing доедет до
    администратора в редакторе, а не потеряется.
    """
    try:
        value = json.loads(_file_template_body())
    except Exception as exc:  # noqa: BLE001 — падение здесь дороже любой неточности диагноза
        logger.warning("NPVPN-2024: файловый шаблон недоступен (%s), сохраняю тело как есть", exc)
        return None
    if not isinstance(value, dict):
        logger.warning(
            "NPVPN-2024: файловый шаблон должен быть JSON-объектом, получен %s — сохраняю тело как есть",
            type(value).__name__,
        )
        return None
    return value


def _safe_json_object(raw: str, name: str) -> dict | None:
    """JSON-объект из значения или None, но НИКОГДА исключение.

    Значения плоских ключей не валидировались: `PanelSettingsPayload.validate_json_field`
    защищал только правки через UI панели, а d7e9f1a2b3c4_move_panel_settings.py скопировал
    их из `bot_settings.data` как есть. До реформы битый JSON в этих ключах ничего не ронял
    — `app/subscription/share.py::_safe_json` писал warning и уводил рендер на фолбэк.
    Миграция обязана вести себя так же: на MySQL DDL не транзакционен, и падение посреди
    upgrade() оставило бы созданные таблицы при непродвинутом alembic_version — панель не
    поднялась бы даже после рестарта («Table 'xray_templates' already exists»).

    Семантика повторяет `app/xray/client_configs.py::parse_json_object`, но локально:
    миграция самодостаточна и не тянет код приложения. Warning нужен, чтобы админ увидел
    потерянное значение и поправил его руками в редакторе.
    """
    if not (raw or "").strip():
        return None
    try:
        value = json.loads(raw)
    except ValueError as exc:
        logger.warning("NPVPN-2024: игнорирую битый JSON в %s: %s", name, exc)
        return None
    if not isinstance(value, dict):
        logger.warning("NPVPN-2024: игнорирую %s: ожидался JSON-объект, получен %s", name, type(value).__name__)
        return None
    return value


def _build_body(template_raw: str, routing_raw: str, routing_key: str) -> str:
    """Самодостаточный конфиг = база с вклеенной секцией routing.

    Пустой (а равно битый — см. `_safe_json_object`) routing-ключ означает «этой группе
    серверов routing из шаблона», то есть ровно шаблон, — поэтому тело берётся как есть,
    включая пустую строку: тогда работает файловый фолбэк рантайма. Битый шаблон тоже
    остаётся в теле как есть — рантайм отбросит его ровно как до реформы, зато админ
    увидит своё значение в редакторе и починит.

    Битая база при непустом routing = «шаблон не задан», то есть файловый шаблон: иначе
    склейка потеряла бы всё, кроме routing.
    """
    routing = _safe_json_object(routing_raw, routing_key)
    if routing is None:
        return template_raw or ""
    base = _safe_json_object(template_raw, FLAT_TEMPLATE_KEY)
    if base is None:
        base = _safe_file_template()
    if base is None:
        return template_raw or ""
    base["routing"] = routing
    return json.dumps(base, ensure_ascii=False)


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
    """Перенос: три плоских ключа → два самодостаточных документа + версия 1;
    is_bs=1 → документ bs; ключи вычищаются."""
    conn = op_like.get_bind()
    data = _panel_data(conn)
    now = datetime.utcnow()
    template_raw = str(data.get(FLAT_TEMPLATE_KEY) or "")
    slug_to_id: dict[str, int] = {}
    for slug, routing_key in FLAT_ROUTING_KEYS.items():
        conn.execute(
            sa.text(
                "INSERT INTO xray_templates (slug, title, created_at, updated_at) "
                "VALUES (:slug, :title, :now, :now)"
            ),
            {"slug": slug, "title": TITLES[slug], "now": now},
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
                "body": _build_body(template_raw, str(data.get(routing_key) or ""), routing_key),
                "comment": "перенос из настроек панели",
                "now": now,
            },
        )
    # Документ `bs` получают хосты, у которых через host_nodes привязана хотя бы одна
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
    _write_panel_data(conn, {k: v for k, v in data.items() if k not in FLAT_KEYS})


def _active_body(conn, slug: str) -> str:
    body = conn.execute(
        sa.text(
            "SELECT v.body FROM xray_template_versions v "
            "JOIN xray_templates t ON t.id = v.template_id "
            "WHERE t.slug = :slug ORDER BY v.version DESC LIMIT 1"
        ),
        {"slug": slug},
    ).scalar()
    return str(body or "")


def _rollback_data(op_like) -> None:
    """Обратный перенос: самодостаточные документы раскладываются обратно в три
    плоских ключа так, чтобы рендер подписки совпал.

    Документ `default` целиком становится общим шаблоном, а sub_routing_json_default
    — пустым: пустой ключ уводил обычный хост на routing шаблона, то есть ровно на
    routing документа `default`, который теперь и есть шаблон. У БС-хостов в ключ
    возвращается только секция routing документа `bs` — остальные его секции в
    дореформенной модели не существовали и всё равно брались из шаблона.
    """
    conn = op_like.get_bind()
    data = _panel_data(conn)
    data[FLAT_TEMPLATE_KEY] = _active_body(conn, "default")
    data[FLAT_ROUTING_KEYS["default"]] = ""
    # Тело документа тоже может не парситься: миграция сохраняет битый шаблон как есть,
    # чтобы админ увидел своё значение. downgrade() при этом обязан дойти до конца —
    # тот же класс дефекта, что и в _build_body.
    bs_body = _safe_json_object(_active_body(conn, "bs"), "тело активной версии документа `bs`")
    bs_routing = ""
    if bs_body is not None:
        routing = bs_body.get("routing")
        if routing is not None:
            bs_routing = json.dumps(routing, ensure_ascii=False)
    data[FLAT_ROUTING_KEYS["bs"]] = bs_routing
    _write_panel_data(conn, data)


def upgrade() -> None:
    op.create_table(
        "xray_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
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
