"""Миграция expire INT -> BIGINT (NPVPN-1879).

В MySQL Integer — это INT с потолком 2147483647 (2038-01-19 03:14:07).
Бессрочные подписки бота выставляют ровно этот потолок, и продление поверх
него роняло UPDATE ошибкой 1264 "Out of range value for column 'expire'",
из-за чего панель отвечала боту 500 на каждом синке.

SQLite тут ничего не доказывает — там INTEGER и так 64-битный, — поэтому
проверяем то, что проверить можно: dialect-guard и объявленный тип колонок.
"""

from __future__ import annotations

import glob
import importlib.util
import os
import sys
import types

import sqlalchemy as sa

# app/__init__.py тяжёлый, а app.subscription.share тянет за собой весь стек
# генерации ссылок — тот же обход, что в test_node_metrics.py.
for _name, _module in list(sys.modules.items()):
    if _name.startswith("app.") and not hasattr(_module, "__file__") and not hasattr(_module, "__path__"):
        del sys.modules[_name]

_share_stub = types.ModuleType("app.subscription.share")
_share_stub.generate_v2ray_links = lambda *args, **kwargs: []
sys.modules.setdefault("app.subscription.share", _share_stub)

from app.db.models import NextPlan, User  # noqa: E402


def _load_migration():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    matches = glob.glob(os.path.join(here, "app/db/migrations/versions/*_npvpn_1879_expire_int_to_bigint.py"))
    assert len(matches) == 1, f"expected exactly one expire migration, got {matches}"
    spec = importlib.util.spec_from_file_location("expire_bigint_migration", matches[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bind(dialect: str):
    class _Engine:
        name = dialect

    class _Bind:
        engine = _Engine()

    return _Bind()


class _RecordingOp:
    """Заглушка alembic.op: записывает вызовы вместо похода в БД."""

    def __init__(self, dialect: str):
        self._bind = _bind(dialect)
        self.altered: list[tuple[str, str, object]] = []
        self.executed: list[str] = []

    def get_bind(self):
        return self._bind

    def alter_column(self, table, column, **kwargs):
        self.altered.append((table, column, kwargs.get("type_")))

    def execute(self, statement):
        self.executed.append(str(statement))


def test_models_declare_bigint_expire():
    assert isinstance(User.__table__.c.expire.type, sa.BigInteger)
    assert isinstance(NextPlan.__table__.c.expire.type, sa.BigInteger)


def test_upgrade_widens_both_tables_on_mysql(monkeypatch):
    migration = _load_migration()
    op = _RecordingOp("mysql")
    monkeypatch.setattr(migration, "op", op)

    migration.upgrade()

    assert [(table, column) for table, column, _ in op.altered] == [("users", "expire"), ("next_plans", "expire")]
    assert all(isinstance(type_, sa.BigInteger) for _, _, type_ in op.altered)


def test_upgrade_is_noop_on_sqlite(monkeypatch):
    """SQLite и так хранит 64-битные целые — ALTER там не нужен и не поддержан."""
    migration = _load_migration()
    op = _RecordingOp("sqlite")
    monkeypatch.setattr(migration, "op", op)

    migration.upgrade()

    assert op.altered == []
    assert op.executed == []


def test_downgrade_clamps_before_narrowing(monkeypatch):
    """Сужение обратно до INT обязано сначала прижать значения к потолку.

    Иначе откат падает ровно той же ошибкой 1264, из-за которой миграция и
    появилась.
    """
    migration = _load_migration()
    op = _RecordingOp("mysql")
    monkeypatch.setattr(migration, "op", op)

    migration.downgrade()

    assert len(op.executed) == 2
    assert all(str(migration.INT32_MAX) in statement for statement in op.executed)
    assert [(table, column) for table, column, _ in op.altered] == [("next_plans", "expire"), ("users", "expire")]
    assert all(type(type_) is sa.Integer for _, _, type_ in op.altered)


def test_downgrade_is_noop_on_sqlite(monkeypatch):
    migration = _load_migration()
    op = _RecordingOp("sqlite")
    monkeypatch.setattr(migration, "op", op)

    migration.downgrade()

    assert op.altered == []
    assert op.executed == []
