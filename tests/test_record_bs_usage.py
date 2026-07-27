"""Учёт БС-трафика в node_user_bs_usage (record_bs_user_stats).

Регресс NPVPN-1518: ORM-овый executemany-UPDATE с дополнительным WHERE в
SQLAlchemy 2.0 всегда падает InvalidRequestError, из-за чего инкремент БС-usage
терялся на каждом тике джоба (строки создавались один раз и больше не росли).
"""

import sys
import types
from contextlib import contextmanager
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

# Здесь нужны НАСТОЯЩИЕ модели и джоб. Другие тесты (test_subscription_bs_render) кладут
# в sys.modules лёгкие заглушки отдельных модулей (app.db, app.utils.system, …) — если они
# уже там, убираем, иначе импорт ниже подхватит их вместо реальных. Пакеты-заглушки из
# conftest (у них есть __path__) не трогаем: на них держится вся песочница. Обратный
# порядок безопасен — тот тест держит ссылки на свои модули и подменяет crud фикстурой.
for _name, _module in list(sys.modules.items()):
    if _name.startswith("app.") and not hasattr(_module, "__file__") and not hasattr(_module, "__path__"):
        del sys.modules[_name]

# app.db.models тянет app.models.user → app.subscription.share, а тот на импорте делает
# `from . import *` (в песочнице conftest пакет заглушен) и лезет в сеть за public ip.
# Для учёта трафика он не нужен — подменяем на время импорта моделей и сразу убираем,
# чтобы тесты рендера подписки получили настоящий модуль.
_share_stub = types.ModuleType("app.subscription.share")
_share_stub.generate_v2ray_links = lambda *args, **kwargs: []
sys.modules.setdefault("app.subscription.share", _share_stub)

from app.db.base import Base  # noqa: E402
from app.db.models import Node, NodeUserBsUsage, User  # noqa: E402
from app.jobs import record_usages  # noqa: E402
from app.jobs.record_usages import record_bs_user_stats  # noqa: E402
from app.xray.bs_limit import period_keys  # noqa: E402

if sys.modules.get("app.subscription.share") is _share_stub:
    del sys.modules["app.subscription.share"]

NODE_ID = 13
USER_ID = 45581


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Node(id=NODE_ID, name="bs-node", address="127.0.0.1", port=62050, api_port=62051, is_bs=True))
        session.add(User(id=USER_ID, username="TEST100", created_at=datetime.utcnow()))
        session.commit()
        yield session


@pytest.fixture
def patched_getdb(db, monkeypatch):
    """record_bs_user_stats открывает свою сессию через GetDB — подменяем на тестовую."""

    @contextmanager
    def fake_getdb():
        yield db

    monkeypatch.setattr(record_usages, "GetDB", fake_getdb)


def bs_usage(db):
    return db.query(NodeUserBsUsage).filter(NodeUserBsUsage.node_id == NODE_ID).one()


def test_first_tick_creates_row_with_delta(db, patched_getdb):
    record_bs_user_stats([{"uid": USER_ID, "value": 1024}], NODE_ID)

    row = bs_usage(db)
    assert row.monthly_used == 1024
    assert row.monthly_period == period_keys(datetime.utcnow())


def test_next_tick_increments_existing_row(db, patched_getdb):
    # Ровно этот шаг и терялся: строка уже есть → идёт UPDATE, а не INSERT.
    record_bs_user_stats([{"uid": USER_ID, "value": 1024}], NODE_ID)
    record_bs_user_stats([{"uid": USER_ID, "value": 3072}], NODE_ID)

    assert bs_usage(db).monthly_used == 4096


def test_usage_coefficient_applied_on_increment(db, patched_getdb):
    record_bs_user_stats([{"uid": USER_ID, "value": 100}], NODE_ID)
    record_bs_user_stats([{"uid": USER_ID, "value": 100}], NODE_ID, consumption_factor=3)

    assert bs_usage(db).monthly_used == 400


def test_stale_month_resets_counter(db, patched_getdb):
    record_bs_user_stats([{"uid": USER_ID, "value": 500}], NODE_ID)
    row = bs_usage(db)
    row.monthly_period = "2000-01"
    db.commit()

    record_bs_user_stats([{"uid": USER_ID, "value": 700}], NODE_ID)

    row = bs_usage(db)
    assert row.monthly_used == 700
    assert row.monthly_period == period_keys(datetime.utcnow())
