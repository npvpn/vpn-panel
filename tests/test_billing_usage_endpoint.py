"""Сбор данных для счёта партнёру (NPVPN-2044)."""

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
from app.db.models import (  # noqa: E402
    Bot,
    BotBsDaily,
    Node,
    ProxyHost,
    ProxyInbound,
    User,
    UserDevice,
    host_bot_association,
)
from app.services.billing_usage import (  # noqa: E402
    BillingPeriodError,
    collect_bot_usage,
    validate_period,
)

if sys.modules.get("app.subscription.share") is _share_stub:
    del sys.modules["app.subscription.share"]

sys.modules.update(_saved_stubs)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def seeded(db):
    inbound = ProxyInbound(tag="VLESS TCP REALITY")
    bot = Bot(username="AppleGurruBot")
    node = Node(name="bs-1", address="1.1.1.1", port=62050, api_port=62051, is_bs=True)
    db.add_all([inbound, bot, node])
    db.flush()

    rented = ProxyHost(remark="🇪🇺 [Белый список] #1", address="1.1.1.1", inbound=inbound, bots=[bot])
    service = ProxyHost(remark="Служебный", address="2.2.2.2", inbound=inbound, bots=[bot])
    db.add_all([rented, service])
    db.flush()
    db.execute(
        host_bot_association.update()
        .where(host_bot_association.c.host_id == rented.id)
        .values(rented_at=datetime(2026, 9, 1))
    )

    user = User(username="u1", bot_id=bot.id)
    db.add(user)
    db.flush()
    db.add_all(
        [
            UserDevice(user_id=user.id, hwid="a", status="active"),
            UserDevice(user_id=user.id, hwid="b", status="active"),
            UserDevice(user_id=user.id, hwid="c", status="revoked"),
        ]
    )
    db.add_all(
        [
            BotBsDaily(bot_id=bot.id, node_id=node.id, day=date(2026, 9, 10), used_bytes=100),
            BotBsDaily(bot_id=bot.id, node_id=node.id, day=date(2026, 9, 20), used_bytes=40),
            # вне периода — не должно попасть
            BotBsDaily(bot_id=bot.id, node_id=node.id, day=date(2026, 8, 31), used_bytes=777),
        ]
    )
    db.commit()
    return {"bot": bot}


def test_collects_four_values_for_a_bot(db, seeded):
    rows = collect_bot_usage(db, datetime(2026, 9, 1), datetime(2026, 10, 1))

    assert rows == [
        {
            "bot_username": "AppleGurruBot",
            "rented_hosts": 1,
            "rented_host_remarks": ["🇪🇺 [Белый список] #1"],
            "devices_active": 2,
            "bs_bytes": 140,
        }
    ]


def test_service_binding_is_not_counted_as_rented(db, seeded):
    """Привязка без rented_at — служебная, в счёт не идёт."""
    rows = collect_bot_usage(db, datetime(2026, 9, 1), datetime(2026, 10, 1))

    assert rows[0]["rented_hosts"] == 1
    assert "Служебный" not in rows[0]["rented_host_remarks"]


def test_bot_without_anything_is_absent_from_response(db, seeded):
    """Бот без данных не приходит с нулями: отличать «ноль» от «нет записи»
    должен вызывающий, иначе ноль прочтётся как «трафика не было»."""
    db.add(Bot(username="EmptyBot"))
    db.commit()

    rows = collect_bot_usage(db, datetime(2026, 9, 1), datetime(2026, 10, 1))

    assert [r["bot_username"] for r in rows] == ["AppleGurruBot"]


def test_period_is_half_open(db, seeded):
    """`to` исключительно: иначе сутки на стыке попадут в два счёта."""
    rows = collect_bot_usage(db, datetime(2026, 9, 10), datetime(2026, 9, 20))

    assert rows[0]["bs_bytes"] == 100


def test_rejects_reversed_period():
    """Review Focus 5: from >= to отвергается, а не отдаёт пустой ответ,
    который читается как «трафика не было». Роутер переводит это в 400."""
    with pytest.raises(BillingPeriodError):
        validate_period(datetime(2026, 10, 1), datetime(2026, 9, 1))


def test_rejects_empty_period():
    """Нулевой интервал — тоже ошибка: счёт за «ничего» не выставляют."""
    with pytest.raises(BillingPeriodError):
        validate_period(datetime(2026, 10, 1), datetime(2026, 10, 1))
