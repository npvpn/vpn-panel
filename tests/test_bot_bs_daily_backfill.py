"""Бэкфилл суточного агрегата из node_user_usages (NPVPN-2044).

Сырой журнал хранит историю с октября 2024 (9.6 млн строк), и она не должна
потеряться при переходе на агрегат.
"""

from __future__ import annotations

import importlib.util
import pathlib
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
from app.db.models import Bot, BotBsDaily, Node, NodeUserUsage, User  # noqa: E402

if sys.modules.get("app.subscription.share") is _share_stub:
    del sys.modules["app.subscription.share"]

sys.modules.update(_saved_stubs)

_VERSIONS = pathlib.Path(__file__).parent.parent / "app" / "db" / "migrations" / "versions"


def _load_revision():
    """Модуль ревизии грузится напрямую: alembic-окружение панели требует xray."""
    path = next(_VERSIONS.glob("*_npvpn_2044_backfill_bot_bs_daily.py"))
    spec = importlib.util.spec_from_file_location("backfill_rev", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def seeded(db):
    bot = Bot(username="AppleGurruBot")
    bs_node = Node(name="bs-1", address="1.1.1.1", port=62050, api_port=62051, is_bs=True)
    plain_node = Node(name="plain", address="2.2.2.2", port=62050, api_port=62051, is_bs=False)
    db.add_all([bot, bs_node, plain_node])
    db.flush()
    user = User(username="u1", bot_id=bot.id)
    orphan = User(username="orphan", bot_id=None)
    db.add_all([user, orphan])
    db.flush()
    db.add_all(
        [
            # два часа одних суток по БС-ноде — должны сложиться
            NodeUserUsage(created_at=datetime(2026, 9, 1, 10), user_id=user.id, node_id=bs_node.id, used_traffic=100),
            NodeUserUsage(created_at=datetime(2026, 9, 1, 11), user_id=user.id, node_id=bs_node.id, used_traffic=40),
            # другие сутки
            NodeUserUsage(created_at=datetime(2026, 9, 2, 10), user_id=user.id, node_id=bs_node.id, used_traffic=7),
            # не-БС нода — не попадает
            NodeUserUsage(
                created_at=datetime(2026, 9, 1, 10), user_id=user.id, node_id=plain_node.id, used_traffic=999
            ),
            # юзер без бота — не попадает
            NodeUserUsage(created_at=datetime(2026, 9, 1, 10), user_id=orphan.id, node_id=bs_node.id, used_traffic=500),
        ]
    )
    db.commit()
    return {"bot": bot, "bs_node": bs_node}


def _rows(db):
    return {(r.bot_id, r.node_id, r.day): r.used_bytes for r in db.query(BotBsDaily).all()}


def test_backfill_aggregates_bs_traffic_by_day(db, seeded):
    _load_revision().backfill_bot_bs_daily(db.connection())
    db.commit()

    assert _rows(db) == {
        (seeded["bot"].id, seeded["bs_node"].id, date(2026, 9, 1)): 140,
        (seeded["bot"].id, seeded["bs_node"].id, date(2026, 9, 2)): 7,
    }


def test_backfill_is_idempotent(db, seeded):
    """Review Focus 2: повторный прогон не удваивает суммы, иначе счёт за
    прошлый период вырастет вдвое и будет выглядеть законным."""
    module = _load_revision()
    module.backfill_bot_bs_daily(db.connection())
    db.commit()
    module.backfill_bot_bs_daily(db.connection())
    db.commit()

    assert _rows(db) == {
        (seeded["bot"].id, seeded["bs_node"].id, date(2026, 9, 1)): 140,
        (seeded["bot"].id, seeded["bs_node"].id, date(2026, 9, 2)): 7,
    }


def test_backfill_does_not_touch_rows_written_by_the_job(db, seeded):
    """Строка, уже записанная джобой, не должна удвоиться бэкфиллом."""
    db.add(BotBsDaily(bot_id=seeded["bot"].id, node_id=seeded["bs_node"].id, day=date(2026, 9, 1), used_bytes=140))
    db.commit()

    _load_revision().backfill_bot_bs_daily(db.connection())
    db.commit()

    assert _rows(db)[(seeded["bot"].id, seeded["bs_node"].id, date(2026, 9, 1))] == 140
