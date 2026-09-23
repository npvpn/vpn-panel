from __future__ import annotations

import sys
import types

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

_share_stub = types.ModuleType("app.subscription.share")
_share_stub.generate_v2ray_links = lambda *args, **kwargs: []
sys.modules.setdefault("app.subscription.share", _share_stub)

from app.db.base import Base  # noqa: E402
from app.db.models import ProxyInbound, XrayTemplate  # noqa: E402
from app.models.proxy import ProxyHost as ProxyHostModify  # noqa: E402


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(ProxyInbound(tag="VLESS_TCP"))
    session.add(XrayTemplate(slug="mobile", title="Мобильные"))
    session.commit()
    yield session
    session.close()


def _profile_id(db):
    return db.query(XrayTemplate).filter(XrayTemplate.slug == "mobile").one().id


def _host_payload(profile_id: int | None) -> ProxyHostModify:
    return ProxyHostModify(remark="server", address="example.com", client_config_id=profile_id)


def test_add_host_persists_client_config(db):
    from app.db import crud

    pid = _profile_id(db)
    hosts = crud.add_host(db, "VLESS_TCP", _host_payload(pid))
    assert [h.client_config_id for h in hosts] == [pid]


def test_update_hosts_keeps_client_config(db):
    """Регресс: update_hosts пересоздаёт строки целиком (inbound.hosts = [ProxyHost(...)]).

    Поле, не проброшенное в этот конструктор, обнулялось бы при КАЖДОМ сохранении
    диалога хостов — то есть у всех хостов сразу, на штатном действии админа.
    """
    from app.db import crud

    pid = _profile_id(db)
    crud.add_host(db, "VLESS_TCP", _host_payload(pid))
    hosts = crud.update_hosts(db, "VLESS_TCP", [_host_payload(pid)])
    assert [h.client_config_id for h in hosts] == [pid]


def test_update_hosts_can_clear_client_config(db):
    from app.db import crud

    pid = _profile_id(db)
    crud.add_host(db, "VLESS_TCP", _host_payload(pid))
    hosts = crud.update_hosts(db, "VLESS_TCP", [_host_payload(None)])
    assert [h.client_config_id for h in hosts] == [None]


def test_host_payload_defaults_to_no_profile():
    assert ProxyHostModify(remark="server", address="example.com").client_config_id is None


def _subset_payload() -> ProxyHostModify:
    return ProxyHostModify(
        remark="server",
        address="example.com",
        address_subset_enabled=True,
        address_subset_size=3,
        address_rotation_days=5,
    )


def test_add_host_persists_address_subset_settings(db):
    from app.db import crud

    hosts = crud.add_host(db, "VLESS_TCP", _subset_payload())
    assert [(h.address_subset_enabled, h.address_subset_size, h.address_rotation_days) for h in hosts] == [(True, 3, 5)]


def test_update_hosts_keeps_address_subset_settings(db):
    """Тот же регресс, что у client_config_id: update_hosts пересоздаёт строки целиком.

    Не проброшенная в конструктор настройка сужения обнулялась бы при КАЖДОМ сохранении
    диалога хостов — фича тихо выключалась бы у всех хостов на штатном действии админа
    (NPVPN-2072).
    """
    from app.db import crud

    crud.add_host(db, "VLESS_TCP", _subset_payload())
    hosts = crud.update_hosts(db, "VLESS_TCP", [_subset_payload()])
    assert [(h.address_subset_enabled, h.address_subset_size, h.address_rotation_days) for h in hosts] == [(True, 3, 5)]
