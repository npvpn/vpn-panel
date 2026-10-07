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


def test_partner_node_traffic_is_excluded_from_the_invoice(db, seeded):
    """NPVPN-2044.1: трафик партнёрской БС-ноды (billable=False) в счёт не
    идёт — партнёр платит за такой сервер сам."""
    partner_bot = Bot(username="AppleGurruBot_owner")
    partner_node = Node(
        name="appleguru-cdn-node-01",
        address="2.2.2.2",
        port=62050,
        api_port=62051,
        is_bs=True,
        owner_bot_id=None,  # владелец ноды не важен для этого теста — важен billable
    )
    db.add_all([partner_bot, partner_node])
    db.flush()
    db.add(
        BotBsDaily(
            bot_id=seeded["bot"].id,
            node_id=partner_node.id,
            day=date(2026, 9, 15),
            used_bytes=163_200,
            billable=False,
        )
    )
    db.commit()

    rows = collect_bot_usage(db, datetime(2026, 9, 1), datetime(2026, 10, 1))

    # Billable-трафик с основной ноды (140) учтён, партнёрские 163200 — нет.
    assert rows[0]["bs_bytes"] == 140


def test_our_node_traffic_is_included_as_billable(db, seeded):
    """Трафик с нашей (billable=True) ноды идёт в счёт как обычно."""
    rows = collect_bot_usage(db, datetime(2026, 9, 1), datetime(2026, 10, 1))

    assert rows[0]["bs_bytes"] == 140


def test_bot_with_only_partner_node_traffic_has_zero_bs_bytes_but_stays_in_response(db, seeded):
    """Весь трафик бота лежит на партнёрской (не билящейся) ноде: bs_bytes
    должен стать 0, но бот не должен выпасть из ответа — у него есть другие
    величины (арендованный хост), и ноль там не означает «нет данных»."""
    partner_node = Node(name="appleguru-cdn-node-01", address="2.2.2.2", port=62050, api_port=62051, is_bs=True)
    db.add(partner_node)
    db.flush()

    second_bot = Bot(username="OnlyPartnerTrafficBot")
    inbound = ProxyInbound(tag="VLESS TCP REALITY #2")
    db.add_all([second_bot, inbound])
    db.flush()

    rented = ProxyHost(remark="🇪🇺 второй хост", address="3.3.3.3", inbound=inbound, bots=[second_bot])
    db.add(rented)
    db.flush()
    db.execute(
        host_bot_association.update()
        .where(host_bot_association.c.host_id == rented.id)
        .values(rented_at=datetime(2026, 9, 1))
    )
    db.add(
        BotBsDaily(
            bot_id=second_bot.id,
            node_id=partner_node.id,
            day=date(2026, 9, 15),
            used_bytes=50_000,
            billable=False,
        )
    )
    db.commit()

    rows = collect_bot_usage(db, datetime(2026, 9, 1), datetime(2026, 10, 1))
    by_bot = {r["bot_username"]: r for r in rows}

    assert by_bot["OnlyPartnerTrafficBot"]["bs_bytes"] == 0
    assert by_bot["OnlyPartnerTrafficBot"]["rented_hosts"] == 1


def test_bot_with_only_nonbillable_traffic_and_nothing_else_is_absent(db, seeded):
    """Зеркало предыдущего теста: бот без арендованных хостов/устройств и с
    трафиком ТОЛЬКО на партнёрской ноде не должен появляться в ответе — у него
    нет ни одной billable-величины, нулём притворяться нечем."""
    partner_node = Node(name="appleguru-cdn-node-01", address="2.2.2.2", port=62050, api_port=62051, is_bs=True)
    db.add(partner_node)
    db.flush()

    lonely_bot = Bot(username="LonelyPartnerBot")
    db.add(lonely_bot)
    db.flush()
    db.add(
        BotBsDaily(
            bot_id=lonely_bot.id,
            node_id=partner_node.id,
            day=date(2026, 9, 15),
            used_bytes=50_000,
            billable=False,
        )
    )
    db.commit()

    rows = collect_bot_usage(db, datetime(2026, 9, 1), datetime(2026, 10, 1))

    assert "LonelyPartnerBot" not in [r["bot_username"] for r in rows]
