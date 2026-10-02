"""Суточный агрегат БС-трафика по ботам (NPVPN-2044).

Нужен, чтобы счета партнёрам не зависели от ретеншна сырого node_user_usages:
та таблица 11 ГБ и растёт, и однажды её чистку включат.
"""

from __future__ import annotations

import sys
import types
from datetime import date, datetime

_saved_stubs: dict[str, types.ModuleType] = {}
for _name, _module in list(sys.modules.items()):
    if _name.startswith("app.") and not hasattr(_module, "__file__") and not hasattr(_module, "__path__"):
        _saved_stubs[_name] = sys.modules.pop(_name)

_share_stub = types.ModuleType("app.subscription.share")
_share_stub.generate_v2ray_links = lambda *args, **kwargs: []
sys.modules.setdefault("app.subscription.share", _share_stub)

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.models import Bot, BotBsDaily, Node, User  # noqa: E402
from app.jobs.record_usages import record_bot_bs_daily  # noqa: E402

if sys.modules.get("app.subscription.share") is _share_stub:
    del sys.modules["app.subscription.share"]

sys.modules.update(_saved_stubs)

DAY = date(2026, 10, 2)


class _FakeCtx:
    """GetDB() — контекстный менеджер; в тесте подменяем его на готовую сессию."""

    def __init__(self, db):
        self._db = db

    def __enter__(self):
        return self._db

    def __exit__(self, *exc):
        return False


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def seeded(db):
    bot = Bot(username="AppleGurruBot")
    node = Node(name="bs-1", address="1.1.1.1", port=62050, api_port=62051, is_bs=True)
    db.add_all([bot, node])
    db.flush()
    u1 = User(username="u1", bot_id=bot.id)
    u2 = User(username="u2", bot_id=bot.id)
    db.add_all([u1, u2])
    db.commit()
    return {"bot": bot, "node": node, "u1": u1, "u2": u2}


def _rows(db):
    return {(r.bot_id, r.node_id, r.day): r.used_bytes for r in db.query(BotBsDaily).all()}


def test_deltas_of_one_bot_are_summed_into_one_row(db, seeded):
    record_bot_bs_daily(db, seeded["node"].id, {seeded["u1"].id: 100, seeded["u2"].id: 50}, DAY)
    db.commit()

    assert _rows(db) == {(seeded["bot"].id, seeded["node"].id, DAY): 150}


def test_second_tick_same_day_accumulates(db, seeded):
    """Два тика в одни сутки складываются, а не перезаписываются."""
    record_bot_bs_daily(db, seeded["node"].id, {seeded["u1"].id: 100}, DAY)
    db.commit()
    record_bot_bs_daily(db, seeded["node"].id, {seeded["u1"].id: 40}, DAY)
    db.commit()

    assert _rows(db) == {(seeded["bot"].id, seeded["node"].id, DAY): 140}


def test_next_day_is_a_separate_row(db, seeded):
    """Review Focus 4: тик на границе суток UTC попадает в сутки своего момента."""
    record_bot_bs_daily(db, seeded["node"].id, {seeded["u1"].id: 100}, DAY)
    record_bot_bs_daily(db, seeded["node"].id, {seeded["u1"].id: 7}, date(2026, 10, 3))
    db.commit()

    rows = _rows(db)
    assert rows[(seeded["bot"].id, seeded["node"].id, DAY)] == 100
    assert rows[(seeded["bot"].id, seeded["node"].id, date(2026, 10, 3))] == 7


def test_user_without_bot_is_skipped(db, seeded):
    """Юзер без bot_id не относится ни к одному партнёру — в счёт его не отнести."""
    orphan = User(username="orphan", bot_id=None)
    db.add(orphan)
    db.commit()

    record_bot_bs_daily(db, seeded["node"].id, {orphan.id: 999}, DAY)
    db.commit()

    assert _rows(db) == {}


def test_empty_deltas_write_nothing(db, seeded):
    record_bot_bs_daily(db, seeded["node"].id, {}, DAY)
    db.commit()

    assert _rows(db) == {}


def test_rows_survive_bot_and_node_deletion(db, seeded):
    """Review Focus 3: архив должен пережить удаление бота или ноды,
    иначе счёт за прошлый месяц исчезнет вместе с удалённой нодой."""
    record_bot_bs_daily(db, seeded["node"].id, {seeded["u1"].id: 100}, DAY)
    db.commit()

    db.query(User).delete()
    db.query(Node).delete()
    db.query(Bot).delete()
    db.commit()

    assert list(_rows(db).values()) == [100]


def test_job_fills_aggregate(db, seeded, monkeypatch):
    """Агрегат наполняется тем же тиком, что node_user_bs_usage."""
    from app.jobs import record_usages

    # GetDB импортирован на уровне модуля — подменяется атрибутом модуля.
    # get_bs_monthly_limit подменять НЕ нужно: он импортируется локально внутри
    # функции (record_usages.py:158) и вызывается только когда период пула
    # отстал, а в этой фикстуре строк node_user_bs_usage ещё нет.
    monkeypatch.setattr(record_usages, "GetDB", lambda: _FakeCtx(db))

    record_usages.record_bs_user_stats([{"uid": seeded["u1"].id, "value": 100}], seeded["node"].id, 1)

    assert _rows(db)[(seeded["bot"].id, seeded["node"].id, datetime.utcnow().date())] == 100
