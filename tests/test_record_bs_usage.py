"""Учёт БС-трафика в node_user_bs_usage (record_bs_user_stats).

Регресс NPVPN-1518: ORM-овый executemany-UPDATE с дополнительным WHERE в
SQLAlchemy 2.0 всегда падает InvalidRequestError, из-за чего инкремент БС-usage
терялся на каждом тике джоба (строки создавались один раз и больше не росли).
"""

import glob
import importlib.util
import os
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
from app.db.models import Bot, BotSettings, Node, NodeUserBsUsage, User  # noqa: E402
from app.jobs import record_usages  # noqa: E402
from app.jobs.record_usages import record_bs_user_stats  # noqa: E402
from app.xray.bs_limit import period_keys  # noqa: E402

if sys.modules.get("app.subscription.share") is _share_stub:
    del sys.modules["app.subscription.share"]

NODE_ID = 13
USER_ID = 45581
GB = 1024**3


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


def _load_bs_period_migration():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    matches = glob.glob(os.path.join(here, "app/db/migrations/versions/*_npvpn_1768_bs_extra_period.py"))
    assert len(matches) == 1, f"expected exactly one bs_extra_period migration, got {matches}"
    spec = importlib.util.spec_from_file_location("bs_extra_period_migration", matches[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_backfill_restores_already_consumed_pool(db):
    """База 3 ГБ, куплено 10 ГБ, израсходовано 8 ГБ: в БД лежит съеденный пул 5 ГБ → чиним до 10 ГБ."""
    db.add(Bot(id=1, username="bot1"))
    db.add(BotSettings(id=1, bot_id=1, data={"bs_monthly_limit": 3 * GB}))
    user = db.query(User).filter(User.id == USER_ID).one()
    user.bot_id = 1
    user.bs_extra = 5 * GB
    db.add(
        NodeUserBsUsage(
            user_id=USER_ID,
            node_id=NODE_ID,
            monthly_used=8 * GB,
            monthly_period=period_keys(datetime.utcnow()),
        )
    )
    db.commit()

    _load_bs_period_migration()._backfill(db.connection())
    db.commit()
    db.expire_all()

    user = db.query(User).filter(User.id == USER_ID).one()
    assert user.bs_extra == 10 * GB
    assert user.bs_extra_period == period_keys(datetime.utcnow())


def test_backfill_leaves_pool_intact_when_base_not_exceeded(db):
    db.add(Bot(id=1, username="bot1"))
    db.add(BotSettings(id=1, bot_id=1, data={"bs_monthly_limit": 3 * GB}))
    user = db.query(User).filter(User.id == USER_ID).one()
    user.bot_id = 1
    user.bs_extra = 10 * GB
    db.add(
        NodeUserBsUsage(
            user_id=USER_ID,
            node_id=NODE_ID,
            monthly_used=2 * GB,
            monthly_period=period_keys(datetime.utcnow()),
        )
    )
    db.commit()

    _load_bs_period_migration()._backfill(db.connection())
    db.commit()
    db.expire_all()

    assert db.query(User).filter(User.id == USER_ID).one().bs_extra == 10 * GB


def test_backfill_is_idempotent(db):
    """Повторный вызов (ручная проверка, ретрай) не должен задваивать восстановленный пул."""
    db.add(Bot(id=1, username="bot1"))
    db.add(BotSettings(id=1, bot_id=1, data={"bs_monthly_limit": 3 * GB}))
    user = db.query(User).filter(User.id == USER_ID).one()
    user.bot_id = 1
    user.bs_extra = 5 * GB
    db.add(
        NodeUserBsUsage(
            user_id=USER_ID,
            node_id=NODE_ID,
            monthly_used=8 * GB,
            monthly_period=period_keys(datetime.utcnow()),
        )
    )
    db.commit()

    migration = _load_bs_period_migration()
    migration._backfill(db.connection())
    db.commit()
    db.expire_all()

    migration._backfill(db.connection())
    db.commit()
    db.expire_all()

    user = db.query(User).filter(User.id == USER_ID).one()
    assert user.bs_extra == 10 * GB
    assert user.bs_extra_period == period_keys(datetime.utcnow())


def _bot_with_limit(db, limit_bytes):
    db.add(Bot(id=1, username="bot1"))
    db.add(BotSettings(id=1, bot_id=1, data={"bs_monthly_limit": limit_bytes}))
    user = db.query(User).filter(User.id == USER_ID).one()
    user.bot_id = 1
    db.commit()
    return user


def test_normalize_is_noop_within_same_period(db):
    from app.db import crud

    now = period_keys(datetime.utcnow())
    user = _bot_with_limit(db, 3 * GB)
    user.bs_extra = 10 * GB
    user.bs_extra_period = now
    db.add(NodeUserBsUsage(user_id=USER_ID, node_id=NODE_ID, monthly_used=8 * GB, monthly_period=now))
    db.commit()

    assert crud.normalize_bs_extra_period(db, USER_ID, 3 * GB, now, persist=False) == 10 * GB


def test_normalize_is_noop_when_period_is_null(db):
    from app.db import crud

    now = period_keys(datetime.utcnow())
    user = _bot_with_limit(db, 3 * GB)
    user.bs_extra = 10 * GB
    user.bs_extra_period = None
    db.add(NodeUserBsUsage(user_id=USER_ID, node_id=NODE_ID, monthly_used=8 * GB, monthly_period="2000-01"))
    db.commit()

    assert crud.normalize_bs_extra_period(db, USER_ID, 3 * GB, now, persist=False) == 10 * GB


def test_normalize_subtracts_previous_month_overflow(db):
    from app.db import crud

    now = period_keys(datetime.utcnow())
    user = _bot_with_limit(db, 3 * GB)
    user.bs_extra = 10 * GB
    user.bs_extra_period = "2000-01"
    db.add(NodeUserBsUsage(user_id=USER_ID, node_id=NODE_ID, monthly_used=8 * GB, monthly_period="2000-01"))
    db.commit()

    assert crud.normalize_bs_extra_period(db, USER_ID, 3 * GB, now, persist=False) == 5 * GB


def test_normalize_persists_pool_and_period(db):
    from app.db import crud

    now = period_keys(datetime.utcnow())
    user = _bot_with_limit(db, 3 * GB)
    user.bs_extra = 10 * GB
    user.bs_extra_period = "2000-01"
    db.add(NodeUserBsUsage(user_id=USER_ID, node_id=NODE_ID, monthly_used=8 * GB, monthly_period="2000-01"))
    db.commit()

    crud.normalize_bs_extra_period(db, USER_ID, 3 * GB, now, persist=True)
    db.commit()
    db.expire_all()

    user = db.query(User).filter(User.id == USER_ID).one()
    assert user.bs_extra == 5 * GB
    assert user.bs_extra_period == now


def test_stale_totals_ignore_rows_older_than_pool_period(db):
    """Строка молчащей ноды из позапрошлого месяца уже была учтена — её не вычитаем снова."""
    from app.db import crud

    now = period_keys(datetime.utcnow())
    db.add(Node(id=NODE_ID + 1, name="bs-node-2", address="127.0.0.2", port=62050, api_port=62051, is_bs=True))
    db.add(NodeUserBsUsage(user_id=USER_ID, node_id=NODE_ID, monthly_used=8 * GB, monthly_period="2000-02"))
    db.add(NodeUserBsUsage(user_id=USER_ID, node_id=NODE_ID + 1, monthly_used=99 * GB, monthly_period="2000-01"))
    db.commit()

    assert crud.get_bs_usage_totals_stale(db, USER_ID, now, "2000-02") == 8 * GB


def test_get_bs_state_reports_stable_ceiling(db):
    from app.db import crud

    now = period_keys(datetime.utcnow())
    user = _bot_with_limit(db, 3 * GB)
    user.bs_extra = 10 * GB
    user.bs_extra_period = now
    db.add(NodeUserBsUsage(user_id=USER_ID, node_id=NODE_ID, monthly_used=8 * GB, monthly_period=now))
    db.commit()

    state = crud.get_bs_state(db, db.query(User).filter(User.id == USER_ID).one())
    assert state == {
        "monthly_used": 8 * GB,
        "monthly_limit": 3 * GB,
        "pool": 10 * GB,
        "limit_total": 13 * GB,
    }


def test_pool_untouched_by_ticks_within_month(db, patched_getdb):
    """Главный регресс NPVPN-1768: потолок не должен ехать вниз по мере расхода."""
    now = period_keys(datetime.utcnow())
    user = _bot_with_limit(db, 3 * GB)
    user.bs_extra = 10 * GB
    user.bs_extra_period = now
    db.commit()

    record_bs_user_stats([{"uid": USER_ID, "value": 4 * GB}], NODE_ID)
    record_bs_user_stats([{"uid": USER_ID, "value": 4 * GB}], NODE_ID)
    db.expire_all()

    user = db.query(User).filter(User.id == USER_ID).one()
    assert user.bs_extra == 10 * GB
    assert bs_usage(db).monthly_used == 8 * GB


def test_tick_in_new_month_carries_pool_over_once(db, patched_getdb):
    now = period_keys(datetime.utcnow())
    user = _bot_with_limit(db, 3 * GB)
    user.bs_extra = 10 * GB
    user.bs_extra_period = "2000-01"
    db.add(NodeUserBsUsage(user_id=USER_ID, node_id=NODE_ID, monthly_used=8 * GB, monthly_period="2000-01"))
    db.commit()

    record_bs_user_stats([{"uid": USER_ID, "value": 1 * GB}], NODE_ID)
    record_bs_user_stats([{"uid": USER_ID, "value": 1 * GB}], NODE_ID)
    db.expire_all()

    user = db.query(User).filter(User.id == USER_ID).one()
    assert user.bs_extra == 5 * GB  # вычли ровно перерасход прошлого месяца, второй тик — no-op
    assert user.bs_extra_period == now
    assert bs_usage(db).monthly_used == 2 * GB


def test_user_bs_traffic_summary_keeps_contract_and_stable_ceiling(db):
    from app.db import crud

    user = _bot_with_limit(db, 3 * GB)
    user.bs_extra = 10 * GB
    user.bs_extra_period = "2000-01"
    db.add(NodeUserBsUsage(user_id=USER_ID, node_id=NODE_ID, monthly_used=8 * GB, monthly_period="2000-01"))
    db.commit()

    summary = crud.get_user_bs_traffic(db, db.query(User).filter(User.id == USER_ID).one())

    assert set(summary) == {"monthly_used", "monthly_limit", "monthly_limit_with_extra", "extra_bytes"}
    assert summary["monthly_used"] == 0  # прошлый месяц в текущий агрегат не входит
    assert summary["monthly_limit"] == 3 * GB
    assert summary["extra_bytes"] == 5 * GB  # пул нормализован переносом
    assert summary["monthly_limit_with_extra"] == 8 * GB


def test_bs_monthly_limit_total_uses_normalized_pool(db):
    user = _bot_with_limit(db, 3 * GB)
    user.bs_extra = 10 * GB
    user.bs_extra_period = "2000-01"
    db.add(NodeUserBsUsage(user_id=USER_ID, node_id=NODE_ID, monthly_used=8 * GB, monthly_period="2000-01"))
    db.commit()

    assert db.query(User).filter(User.id == USER_ID).one().bs_monthly_limit_total == 8 * GB


def test_bs_monthly_limit_total_normalizes_pool_once_per_instance(db, monkeypatch):
    """Регресс ревью: bs_monthly_used обращается к bs_monthly_limit_total как к guard'у —
    без кеша на инстансе normalize_bs_extra_period (round-trip в БД) отрабатывал бы дважды
    на одно и то же чтение (например, один UserResponse.model_validate)."""
    from app.db import crud

    user = _bot_with_limit(db, 3 * GB)
    user.bs_extra = 10 * GB
    user.bs_extra_period = "2000-01"
    db.add(NodeUserBsUsage(user_id=USER_ID, node_id=NODE_ID, monthly_used=8 * GB, monthly_period="2000-01"))
    db.commit()

    calls = []
    original = crud.normalize_bs_extra_period

    def counting_normalize(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(crud, "normalize_bs_extra_period", counting_normalize)

    dbuser = db.query(User).filter(User.id == USER_ID).one()
    assert dbuser.bs_monthly_limit_total == 8 * GB
    assert dbuser.bs_monthly_used == 0  # прошлый месяц в текущий агрегат не входит
    assert dbuser.bs_monthly_limit_total == 8 * GB  # повторное чтение — тоже из кеша

    assert len(calls) == 1


def test_purchase_normalizes_stale_period_before_increment(db):
    """Покупка в новом месяце не должна лечь поверх непересчитанного пула."""
    from app.db import crud

    now = period_keys(datetime.utcnow())
    user = _bot_with_limit(db, 3 * GB)
    user.bs_extra = 10 * GB
    user.bs_extra_period = "2000-01"
    db.add(NodeUserBsUsage(user_id=USER_ID, node_id=NODE_ID, monthly_used=8 * GB, monthly_period="2000-01"))
    db.commit()

    crud.modify_user_bs_extra(db, db.query(User).filter(User.id == USER_ID).one(), delta_bytes=20 * GB)
    db.expire_all()

    user = db.query(User).filter(User.id == USER_ID).one()
    assert user.bs_extra == 25 * GB  # 10 − 5 перерасхода прошлого месяца + 20 купленных
    assert user.bs_extra_period == now


def test_reset_pool_sets_current_period(db):
    from app.db import crud

    user = _bot_with_limit(db, 3 * GB)
    user.bs_extra = 10 * GB
    user.bs_extra_period = "2000-01"
    db.commit()

    crud.reset_user_bs_extra_pool(db, db.query(User).filter(User.id == USER_ID).one())
    db.expire_all()

    user = db.query(User).filter(User.id == USER_ID).one()
    assert user.bs_extra == 0
    assert user.bs_extra_period == period_keys(datetime.utcnow())
