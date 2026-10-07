"""update_hosts обновляет хосты по месту, а не пересоздаёт (NPVPN-2044).

Пересоздание теряло hosts.id, а на него ссылаются user_node_pins с
ondelete=CASCADE — то есть любое сохранение формы хостов молча удаляло
все закрепления пользователей. Отметка аренды на host_bot_association
умирала бы так же.
"""

from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta

# conftest и часть тестов (например test_subscription_bs_render) оставляют в
# sys.modules лёгкие заглушки app.*; настоящие модели и crud через них не
# импортируются. Снимаем заглушки на время импорта и ВОЗВРАЩАЕМ их обратно:
# безвозвратное удаление ломало тесты, которые идут после этого файла
# (app.templates терял render_template → 5 падений в test_xray_templates_*).
_saved_stubs: dict[str, types.ModuleType] = {}
for _name, _module in list(sys.modules.items()):
    if _name.startswith("app.") and not hasattr(_module, "__file__") and not hasattr(_module, "__path__"):
        _saved_stubs[_name] = sys.modules.pop(_name)

_share_stub = types.ModuleType("app.subscription.share")
_share_stub.generate_v2ray_links = lambda *args, **kwargs: []
sys.modules.setdefault("app.subscription.share", _share_stub)

import pytest  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db import crud  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.models import Bot, ProxyHost, ProxyInbound, User, UserNodePin  # noqa: E402
from app.models.proxy import ProxyHost as ProxyHostSchema  # noqa: E402

if sys.modules.get("app.subscription.share") is _share_stub:
    del sys.modules["app.subscription.share"]

# Заглушки на место — следующий тестовый файл должен увидеть то же состояние,
# что было до нас.
sys.modules.update(_saved_stubs)

TAG = "VLESS TCP REALITY"


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    # Без этого PRAGMA в SQLite ondelete=CASCADE не работает, и тест про пины
    # зеленеет, ничего не проверив: на MySQL прода каскад срабатывает и пины
    # исчезают. Включаем FK, чтобы тест говорил о реальном поведении.
    @event.listens_for(engine, "connect")
    def _enable_sqlite_fk(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def seeded(db):
    inbound = ProxyInbound(tag=TAG)
    bot = Bot(username="AppleGurruBot")
    db.add_all([inbound, bot])
    db.flush()
    host = ProxyHost(remark="Нидерланды", address="1.1.1.1", inbound=inbound, bots=[bot])
    db.add(host)
    db.commit()
    return host


def _payload(host: ProxyHost, **overrides) -> ProxyHostSchema:
    data = {
        "id": host.id,
        "remark": host.remark,
        "address": host.address,
        "bot_usernames": ["AppleGurruBot"],
    }
    data.update(overrides)
    return ProxyHostSchema(**data)


def test_resave_without_changes_keeps_host_id(db, seeded):
    """Главный инвариант: на стабильности hosts.id стоят аренда, пины и снапшоты."""
    original_id = seeded.id

    crud.update_hosts(db, TAG, [_payload(seeded)])

    hosts = db.query(ProxyHost).all()
    assert len(hosts) == 1
    assert hosts[0].id == original_id


def test_resave_keeps_user_node_pins(db, seeded):
    """Раньше любое сохранение формы хостов стирало закрепления каскадом."""
    user = User(username="u1")
    db.add(user)
    db.flush()
    db.add(
        UserNodePin(
            user_id=user.id,
            host_id=seeded.id,
            node_ids=[1],
            expires_at=datetime.utcnow() + timedelta(days=1),
            created_by="support",
        )
    )
    db.commit()

    crud.update_hosts(db, TAG, [_payload(seeded)])

    assert db.query(UserNodePin).count() == 1


def test_host_without_id_is_created(db, seeded):
    crud.update_hosts(
        db,
        TAG,
        [_payload(seeded), ProxyHostSchema(remark="Новый", address="2.2.2.2")],
    )

    remarks = {host.remark for host in db.query(ProxyHost).all()}
    assert remarks == {"Нидерланды", "Новый"}


def test_host_missing_from_payload_is_deleted(db, seeded):
    crud.update_hosts(db, TAG, [])

    assert db.query(ProxyHost).count() == 0


def test_duplicate_ids_are_rejected_without_changes(db, seeded):
    """Review Focus 3: иначе один хост применится дважды, а второй тихо исчезнет."""
    with pytest.raises(ValueError):
        crud.update_hosts(db, TAG, [_payload(seeded), _payload(seeded, remark="Копия")])

    db.rollback()
    assert db.query(ProxyHost).count() == 1
    assert db.query(ProxyHost).one().remark == "Нидерланды"


def test_id_from_other_inbound_is_rejected(db, seeded):
    other = ProxyInbound(tag="VMESS WS")
    db.add(other)
    db.flush()
    foreign = ProxyHost(remark="Чужой", address="9.9.9.9", inbound=other)
    db.add(foreign)
    db.commit()

    with pytest.raises(ValueError):
        crud.update_hosts(db, TAG, [_payload(seeded, id=foreign.id)])

    db.rollback()
    assert db.get(ProxyHost, foreign.id).inbound.tag == "VMESS WS"
