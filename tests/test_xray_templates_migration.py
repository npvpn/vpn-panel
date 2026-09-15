from __future__ import annotations

import glob
import importlib.util
import json
import os

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool


def _load_migration():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    matches = glob.glob(os.path.join(here, "app/db/migrations/versions/*_xray_template_versions.py"))
    assert len(matches) == 1, f"expected exactly one xray templates migration, got {matches}"
    spec = importlib.util.spec_from_file_location("xray_templates_migration", matches[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Op:
    def __init__(self, bind):
        self._bind = bind

    def get_bind(self):
        return self._bind


def _engine(panel_data: dict, hosts: list[tuple[int, list[int]]], bs_node_ids: list[int]):
    """Песочница: global_settings + hosts/host_nodes/nodes + пустые целевые таблицы.

    hosts — список (host_id, [node_id, ...]); bs_node_ids — ноды с is_bs=1.
    """
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE global_settings ("
                '"key" VARCHAR(64) PRIMARY KEY, data TEXT, created_at DATETIME, updated_at DATETIME)'
            )
        )
        conn.execute(text("CREATE TABLE nodes (id INTEGER PRIMARY KEY, is_bs BOOLEAN)"))
        conn.execute(text("CREATE TABLE hosts (id INTEGER PRIMARY KEY, remark VARCHAR(256), client_config_id INTEGER)"))
        conn.execute(text("CREATE TABLE host_nodes (host_id INTEGER, node_id INTEGER)"))
        conn.execute(
            text(
                "CREATE TABLE xray_templates (id INTEGER PRIMARY KEY, slug VARCHAR(64), "
                "title VARCHAR(128), created_at DATETIME, updated_at DATETIME)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE xray_template_versions (id INTEGER PRIMARY KEY, template_id INTEGER, "
                "version INTEGER, body TEXT, comment VARCHAR(255), author_admin_id INTEGER, "
                "author_username VARCHAR(34), created_at DATETIME)"
            )
        )
        conn.execute(
            text('INSERT INTO global_settings ("key", data) VALUES (:k, :d)'),
            {"k": "panel", "d": json.dumps(panel_data)},
        )
        all_node_ids = {nid for _, nids in hosts for nid in nids} | set(bs_node_ids)
        for node_id in sorted(all_node_ids):
            conn.execute(
                text("INSERT INTO nodes (id, is_bs) VALUES (:i, :b)"),
                {"i": node_id, "b": 1 if node_id in bs_node_ids else 0},
            )
        for host_id, node_ids in hosts:
            conn.execute(
                text("INSERT INTO hosts (id, remark, client_config_id) VALUES (:i, :r, NULL)"),
                {"i": host_id, "r": f"host-{host_id}"},
            )
            for node_id in node_ids:
                conn.execute(
                    text("INSERT INTO host_nodes (host_id, node_id) VALUES (:h, :n)"),
                    {"h": host_id, "n": node_id},
                )
    return engine


def _engine_without_panel_row(hosts: list[tuple[int, list[int]]], bs_node_ids: list[int]):
    """Песочница без строки key='panel' в global_settings — сеется только client_apps
    на свежей установке (см. af83ddaadbe7_add_global_settings.py)."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE global_settings ("
                '"key" VARCHAR(64) PRIMARY KEY, data TEXT, created_at DATETIME, updated_at DATETIME)'
            )
        )
        conn.execute(text("CREATE TABLE nodes (id INTEGER PRIMARY KEY, is_bs BOOLEAN)"))
        conn.execute(text("CREATE TABLE hosts (id INTEGER PRIMARY KEY, remark VARCHAR(256), client_config_id INTEGER)"))
        conn.execute(text("CREATE TABLE host_nodes (host_id INTEGER, node_id INTEGER)"))
        conn.execute(
            text(
                "CREATE TABLE xray_templates (id INTEGER PRIMARY KEY, slug VARCHAR(64), "
                "title VARCHAR(128), created_at DATETIME, updated_at DATETIME)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE xray_template_versions (id INTEGER PRIMARY KEY, template_id INTEGER, "
                "version INTEGER, body TEXT, comment VARCHAR(255), author_admin_id INTEGER, "
                "author_username VARCHAR(34), created_at DATETIME)"
            )
        )
        all_node_ids = {nid for _, nids in hosts for nid in nids} | set(bs_node_ids)
        for node_id in sorted(all_node_ids):
            conn.execute(
                text("INSERT INTO nodes (id, is_bs) VALUES (:i, :b)"),
                {"i": node_id, "b": 1 if node_id in bs_node_ids else 0},
            )
        for host_id, node_ids in hosts:
            conn.execute(
                text("INSERT INTO hosts (id, remark, client_config_id) VALUES (:i, :r, NULL)"),
                {"i": host_id, "r": f"host-{host_id}"},
            )
            for node_id in node_ids:
                conn.execute(
                    text("INSERT INTO host_nodes (host_id, node_id) VALUES (:h, :n)"),
                    {"h": host_id, "n": node_id},
                )
    return engine


def test_migration_follows_master_head():
    assert _load_migration().down_revision == "03e94a203122"


def _documents(conn) -> dict[str, tuple[int, str, str]]:
    rows = conn.execute(
        text(
            "SELECT t.slug, v.version, v.body, v.author_username "
            "FROM xray_templates t JOIN xray_template_versions v ON v.template_id = t.id"
        )
    ).all()
    return {slug: (version, body, author) for slug, version, body, author in rows}


def test_flat_keys_become_two_self_contained_documents():
    """Документов ровно два, и каждый — ПОЛНЫЙ конфиг: шаблон со вклеенным routing
    своей группы серверов. Отдельного документа-шаблона больше нет."""
    migration = _load_migration()
    template = {"outbounds": [{"protocol": "freedom"}], "dns": {"servers": ["1.1.1.1"]}}
    engine = _engine(
        {
            "sub_custom_headers": "X-A: 1",
            "sub_v2ray_json_template": json.dumps(template),
            "sub_routing_json_default": '{"rules": ["default"]}',
            "sub_routing_json_bs": '{"rules": ["bs"]}',
        },
        hosts=[(1, [10])],
        bs_node_ids=[10],
    )
    with engine.begin() as conn:
        migration._migrate_data(_Op(conn))
        docs = _documents(conn)

    assert set(docs) == {"default", "bs"}
    for slug, routing in (("default", ["default"]), ("bs", ["bs"])):
        version, body, author = docs[slug]
        assert (version, author) == (1, "migration")
        parsed = json.loads(body)
        assert parsed["routing"] == {"rules": routing}
        # Остальные секции шаблона на месте — документ самодостаточен.
        assert parsed["outbounds"] == template["outbounds"]
        assert parsed["dns"] == template["dns"]


def test_empty_template_falls_back_to_file_template_as_base():
    """Шаблон не переопределяли, а sub_routing_json_bs заполнен: до переезда такой хост
    получал ФАЙЛОВЫЙ шаблон с вклеенным routing — им и становится база склейки."""
    migration = _load_migration()
    engine = _engine(
        {
            "sub_v2ray_json_template": "",
            "sub_routing_json_default": "",
            "sub_routing_json_bs": '{"rules": ["bs"]}',
        },
        hosts=[(1, [10])],
        bs_node_ids=[10],
    )
    with engine.begin() as conn:
        migration._migrate_data(_Op(conn))
        docs = _documents(conn)

    bs_body = json.loads(docs["bs"][1])
    assert bs_body["routing"] == {"rules": ["bs"]}
    # Секции файлового шаблона на месте, а не потеряны вместе с пустым ключом.
    assert "dns" in bs_body
    assert "log" in bs_body


def test_unavailable_file_template_does_not_break_upgrade(monkeypatch):
    """Файловый шаблон недоступен — upgrade всё равно доходит до конца.

    Это боевой путь, а не экзотика: на проде `sub_v2ray_json_template` пуст при
    заполненном `sub_routing_json_bs`, поэтому база склейки берётся из файла, а каталог
    шаблонов смонтирован томом с хоста — том может оказаться пустым. `render_template`
    бросил бы `TemplateNotFound` посреди DDL, и на MySQL панель осталась бы с созданными
    таблицами при непродвинутом alembic_version.
    """
    migration = _load_migration()
    monkeypatch.setattr(
        migration,
        "_file_template_body",
        lambda: (_ for _ in ()).throw(RuntimeError("TemplateNotFound: v2ray/default.json")),
    )
    engine = _engine(
        {
            "sub_v2ray_json_template": "",
            "sub_routing_json_default": "",
            "sub_routing_json_bs": '{"rules": ["bs"]}',
        },
        hosts=[(1, [10])],
        bs_node_ids=[10],
    )
    with engine.begin() as conn:
        migration._migrate_data(_Op(conn))
        docs = _documents(conn)

    # Склеивать не с чем — тело остаётся как есть; рантайм уводит хост на свой фолбэк.
    assert docs["bs"][1] == ""
    assert docs["default"][1] == ""


def test_file_template_that_is_not_an_object_does_not_break_upgrade(monkeypatch):
    """Файл распарсился, но это не объект конфига — вклеивать routing некуда."""
    migration = _load_migration()
    monkeypatch.setattr(migration, "_file_template_body", lambda: "[1, 2]")
    engine = _engine(
        {
            "sub_v2ray_json_template": "",
            "sub_routing_json_default": "",
            "sub_routing_json_bs": '{"rules": ["bs"]}',
        },
        hosts=[(1, [10])],
        bs_node_ids=[10],
    )
    with engine.begin() as conn:
        migration._migrate_data(_Op(conn))
        docs = _documents(conn)

    assert docs["bs"][1] == ""


def test_empty_routing_key_keeps_template_body_as_is():
    """Пустой routing-ключ означал «routing из шаблона» — тело документа и есть шаблон,
    включая пустую строку (тогда в рантайме работает файловый фолбэк)."""
    migration = _load_migration()
    engine = _engine(
        {
            "sub_v2ray_json_template": '{"outbounds": []}',
            "sub_routing_json_default": "",
            "sub_routing_json_bs": "",
        },
        hosts=[(1, [10])],
        bs_node_ids=[10],
    )
    with engine.begin() as conn:
        migration._migrate_data(_Op(conn))
        docs = _documents(conn)

    assert docs["default"][1] == '{"outbounds": []}'
    assert docs["bs"][1] == '{"outbounds": []}'


def test_empty_template_and_empty_routing_key_leave_body_empty():
    """Ничего не переопределяли — тело пустое: пустой документ уводит рантайм на файловый
    шаблон, ровно как до переезда."""
    migration = _load_migration()
    engine = _engine(
        {"sub_v2ray_json_template": "", "sub_routing_json_default": "", "sub_routing_json_bs": ""},
        hosts=[(1, [10])],
        bs_node_ids=[10],
    )
    with engine.begin() as conn:
        migration._migrate_data(_Op(conn))
        docs = _documents(conn)

    assert docs["default"][1] == ""
    assert docs["bs"][1] == ""


def test_hosts_of_bs_nodes_get_bs_config_and_others_stay_null():
    """ANY-семантика: хватает одной БС-ноды среди привязанных к хосту."""
    migration = _load_migration()
    engine = _engine(
        {"sub_v2ray_json_template": "", "sub_routing_json_default": "", "sub_routing_json_bs": ""},
        hosts=[(1, [10]), (2, [20]), (3, [20, 10]), (4, [])],
        bs_node_ids=[10],
    )
    with engine.begin() as conn:
        migration._migrate_data(_Op(conn))
        bs_id = conn.execute(text("SELECT id FROM xray_templates WHERE slug = 'bs'")).scalar_one()
        mapping = dict(conn.execute(text("SELECT id, client_config_id FROM hosts")).all())
    assert mapping == {1: bs_id, 2: None, 3: bs_id, 4: None}


def test_flat_keys_are_stripped_from_panel_settings():
    migration = _load_migration()
    engine = _engine(
        {
            "sub_custom_headers": "X-A: 1",
            "sub_v2ray_json_template": '{"a": 1}',
            "sub_routing_json_default": "",
            "sub_routing_json_bs": "",
        },
        hosts=[],
        bs_node_ids=[],
    )
    with engine.begin() as conn:
        migration._migrate_data(_Op(conn))
        raw = conn.execute(text('SELECT data FROM global_settings WHERE "key" = :k'), {"k": "panel"}).scalar_one()
    data = json.loads(raw)
    assert data == {"sub_custom_headers": "X-A: 1"}


def test_downgrade_restores_flat_keys_so_that_render_matches():
    """Раскладка обратно даёт тот же рендер, а не побайтово те же ключи.

    `default` целиком становится общим шаблоном (его routing и есть routing шаблона),
    sub_routing_json_default пустеет — пустой ключ и уводил обычный хост на routing
    шаблона. У БС-хоста в ключ возвращается только секция routing документа `bs`.
    """
    migration = _load_migration()
    template = {"outbounds": [{"protocol": "freedom"}], "dns": {"servers": ["1.1.1.1"]}}
    engine = _engine(
        {
            "sub_v2ray_json_template": json.dumps(template),
            "sub_routing_json_default": '{"rules": ["default"]}',
            "sub_routing_json_bs": '{"rules": ["bs"]}',
        },
        hosts=[(1, [10])],
        bs_node_ids=[10],
    )
    with engine.begin() as conn:
        migration._migrate_data(_Op(conn))
        migration._rollback_data(_Op(conn))
        raw = conn.execute(text('SELECT data FROM global_settings WHERE "key" = :k'), {"k": "panel"}).scalar_one()
    data = json.loads(raw)
    restored = json.loads(data["sub_v2ray_json_template"])
    # Обычный хост: шаблон + пустой default-ключ = routing шаблона = routing документа `default`.
    assert restored["routing"] == {"rules": ["default"]}
    assert restored["outbounds"] == template["outbounds"]
    assert restored["dns"] == template["dns"]
    assert data["sub_routing_json_default"] == ""
    # БС-хост: шаблон + свой routing-ключ = документ `bs`.
    assert json.loads(data["sub_routing_json_bs"]) == {"rules": ["bs"]}


def test_mysql_sql_quotes_reserved_key_column():
    """Регресс: сырой SELECT/UPDATE ... WHERE key ... падает/лжёт на MySQL (1064, KEY —
    reserved; без ANSI_QUOTES двойные кавычки — строковый литерал, не идентификатор,
    условие "key" = 'panel' всегда ложно)."""
    import sqlalchemy as sa
    from sqlalchemy.dialects import mysql

    migration = _load_migration()
    gs = migration._global_settings_table()

    select_compiled = str(sa.select(gs.c.data).where(gs.c.key == "panel").compile(dialect=mysql.dialect()))
    assert "`key`" in select_compiled
    assert "SELECT key " not in select_compiled

    update_compiled = str(sa.update(gs).where(gs.c.key == "panel").values(data="x").compile(dialect=mysql.dialect()))
    assert "`key`" in update_compiled
    assert 'WHERE "key"' not in update_compiled


def _compiled_mysql_ddl(fn) -> str:
    """Скомпилировать DDL-шаг миграции под MySQL, не подключаясь к серверу.

    Alembic в offline-режиме (as_sql) пишет готовый SQL в буфер — так проверяется
    ровно тот код, который поедет на прод, а не его пересказ в тесте.
    """
    import io

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy.dialects import mysql

    buffer = io.StringIO()
    context = MigrationContext.configure(dialect=mysql.dialect(), opts={"as_sql": True, "output_buffer": buffer})
    fn(Operations(context))
    return buffer.getvalue()


def test_ddl_names_hosts_foreign_key_and_drops_it_before_column():
    """Регресс: MySQL не даёт дропнуть колонку под живым FK (ERROR 1828).

    Утверждение про upgrade проверяет именно СОЗДАНИЕ констрейнта под явным именем
    (`ADD CONSTRAINT <HOSTS_FK_NAME> FOREIGN KEY`) — просто наличие HOSTS_FK_NAME
    где-то в тексте SQL прошло бы и при `create_foreign_key(None, ...)`, потому что
    то же имя жёстко зашито в `_drop_client_config_column` для DROP FOREIGN KEY.
    На MySQL такая рассинхронизация (безымянный ADD CONSTRAINT + именованный DROP)
    реально давала бы ERROR 1305 Unknown table constraint.
    """
    migration = _load_migration()

    upgrade_sql = _compiled_mysql_ddl(migration._add_client_config_column)
    assert f"ADD CONSTRAINT {migration.HOSTS_FK_NAME} FOREIGN KEY" in upgrade_sql
    assert "ALTER TABLE hosts ADD COLUMN client_config_id" in upgrade_sql

    downgrade_sql = _compiled_mysql_ddl(migration._drop_client_config_column)
    assert "ALTER TABLE hosts" in downgrade_sql
    drop_fk = downgrade_sql.index(f"DROP FOREIGN KEY {migration.HOSTS_FK_NAME}")
    drop_column = downgrade_sql.index("DROP COLUMN client_config_id")
    assert drop_fk < drop_column


def test_migrate_data_without_panel_row_does_not_fail_and_creates_row():
    """Свежая установка: строки key='panel' ещё нет (сеется только client_apps)."""
    migration = _load_migration()
    engine = _engine_without_panel_row(hosts=[(1, [10])], bs_node_ids=[10])
    with engine.begin() as conn:
        migration._migrate_data(_Op(conn))
        raw = conn.execute(text('SELECT data FROM global_settings WHERE "key" = :k'), {"k": "panel"}).scalar_one()
        bs_id = conn.execute(text("SELECT id FROM xray_templates WHERE slug = 'bs'")).scalar_one()
        mapping = dict(conn.execute(text("SELECT id, client_config_id FROM hosts")).all())
    # Строка создана (upsert = insert), плоских ключей в ней нет — их и не было.
    assert json.loads(raw) == {}
    assert mapping == {1: bs_id}


def test_rollback_data_without_panel_row_creates_row():
    """downgrade() на установке без строки key='panel': _rollback_data должна создать
    строку через upsert, а не молча потерять восстанавливаемые плоские ключи."""
    migration = _load_migration()
    engine = _engine_without_panel_row(hosts=[], bs_node_ids=[])
    with engine.begin() as conn:
        # Документы уже существуют (как будто upgrade() уже создал таблицы и версии),
        # но саму строку global_settings кто-то удалил/её никогда не было.
        migration._migrate_data(_Op(conn))
        conn.execute(text('DELETE FROM global_settings WHERE "key" = :k'), {"k": "panel"})
        assert conn.execute(text("SELECT COUNT(*) FROM global_settings")).scalar_one() == 0

        migration._rollback_data(_Op(conn))
        raw = conn.execute(text('SELECT data FROM global_settings WHERE "key" = :k'), {"k": "panel"}).scalar_one()
    data = json.loads(raw)
    assert data["sub_v2ray_json_template"] == ""
    assert data["sub_routing_json_default"] == ""
    assert data["sub_routing_json_bs"] == ""


def test_broken_template_key_falls_back_to_file_template_as_base():
    """Битый шаблон + непустой routing-ключ: до реформы такой хост получал ФАЙЛОВЫЙ
    шаблон с вклеенным routing (_safe_json в share.py глушил ValueError), — миграция
    обязана дойти до конца и повторить это, а не упасть посреди upgrade()."""
    migration = _load_migration()
    engine = _engine(
        {
            "sub_v2ray_json_template": '{"outbounds": [',  # обрезанный JSON
            "sub_routing_json_default": "",
            "sub_routing_json_bs": '{"rules": ["bs"]}',
        },
        hosts=[(1, [10])],
        bs_node_ids=[10],
    )
    with engine.begin() as conn:
        migration._migrate_data(_Op(conn))
        docs = _documents(conn)

    bs_body = json.loads(docs["bs"][1])
    assert bs_body["routing"] == {"rules": ["bs"]}
    # База — файловый шаблон, ровно как при пустом ключе.
    assert "dns" in bs_body
    assert "log" in bs_body


def test_broken_routing_key_keeps_template_body_as_is():
    """Битый routing-ключ трактуется как пустой: тело документа = шаблон, без склейки."""
    migration = _load_migration()
    engine = _engine(
        {
            "sub_v2ray_json_template": '{"outbounds": []}',
            "sub_routing_json_default": "",
            "sub_routing_json_bs": '{"rules": ',  # обрезанный JSON
        },
        hosts=[(1, [10])],
        bs_node_ids=[10],
    )
    with engine.begin() as conn:
        migration._migrate_data(_Op(conn))
        docs = _documents(conn)

    assert docs["bs"][1] == '{"outbounds": []}'


def test_json_array_value_is_treated_as_broken():
    """Валидный JSON, но не объект конфига: массив в шаблоне уводит базу на файловый
    шаблон, массив в routing-ключе трактуется как пустой ключ."""
    migration = _load_migration()
    engine = _engine(
        {
            "sub_v2ray_json_template": "[1, 2]",
            "sub_routing_json_default": "[1, 2]",
            "sub_routing_json_bs": '{"rules": ["bs"]}',
        },
        hosts=[(1, [10])],
        bs_node_ids=[10],
    )
    with engine.begin() as conn:
        migration._migrate_data(_Op(conn))
        docs = _documents(conn)

    # Массив в routing-ключе = ключ пуст: тело равно шаблону как есть.
    assert docs["default"][1] == "[1, 2]"
    # Массив в шаблоне = шаблон не задан: база склейки — файловый шаблон.
    bs_body = json.loads(docs["bs"][1])
    assert bs_body["routing"] == {"rules": ["bs"]}
    assert "dns" in bs_body


def test_downgrade_survives_unparsable_bs_document_body():
    """downgrade() на документе с непарсящимся телом (его туда кладёт сама миграция,
    сохраняя битый шаблон как есть) обязан дойти до конца, а не упасть на json.loads."""
    migration = _load_migration()
    engine = _engine(
        {
            "sub_v2ray_json_template": '{"outbounds": [',  # обрезанный JSON
            "sub_routing_json_default": "",
            "sub_routing_json_bs": "",
        },
        hosts=[(1, [10])],
        bs_node_ids=[10],
    )
    with engine.begin() as conn:
        migration._migrate_data(_Op(conn))
        assert _documents(conn)["bs"][1] == '{"outbounds": ['
        migration._rollback_data(_Op(conn))
        raw = conn.execute(text('SELECT data FROM global_settings WHERE "key" = :k'), {"k": "panel"}).scalar_one()
    data = json.loads(raw)
    assert data["sub_routing_json_bs"] == ""
