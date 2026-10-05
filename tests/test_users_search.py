"""Поиск пользователей в дашборде: невидимые символы в запросе (NPVPN-2161).

Строку поиска часто вставляют из Telegram, и вместе с именем прилетают пробел или
перенос в конце, неразрывный пробел, символ нулевой ширины. Внутри ILIKE '%...%'
любой из них ломает совпадение — пользователь есть, а поиск пустой.
"""

from __future__ import annotations

import sys
import types

# app.subscription.share тянет за собой весь стек генерации ссылок и цикл импортов
# через app.models.user — тот же обход, что в test_address_history.py.
for _name, _module in list(sys.modules.items()):
    if _name.startswith("app.") and not hasattr(_module, "__file__") and not hasattr(_module, "__path__"):
        del sys.modules[_name]

_share_stub = types.ModuleType("app.subscription.share")
_share_stub.generate_v2ray_links = lambda *args, **kwargs: []
sys.modules.setdefault("app.subscription.share", _share_stub)

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db import crud  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.models import User  # noqa: E402

if sys.modules.get("app.subscription.share") is _share_stub:
    del sys.modules["app.subscription.share"]

USERNAME = "202715_6078"


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([User(username=USERNAME), User(username="530399467_1", note="vip 6078")])
        session.commit()
        yield session


def _found(db: Session, search: str) -> list[str]:
    return sorted(user.username for user in crud.get_users(db, search=search))


@pytest.mark.parametrize(
    "search",
    [
        "202715_6078",
        "202715_6078 ",
        "202715_6078\n",
        " \t202715_6078",
        "\u200b202715_6078",
        "202715_6078\ufeff",
        "202715\u200d_6078",
        "\u00a0202715_6078\u202f",
    ],
)
def test_search_ignores_invisible_chars(db, search):
    assert _found(db, search) == [USERNAME]


def test_search_still_matches_note(db):
    assert _found(db, " vip ") == ["530399467_1"]


@pytest.mark.parametrize("search", ["", "   ", "\u200b", "\u00a0\n"])
def test_blank_search_does_not_filter(db, search):
    assert _found(db, search) == ["202715_6078", "530399467_1"]


def test_normalize_keeps_inner_spaces():
    assert crud.normalize_users_search("  vip\u00a0client ") == "vip client"
    assert crud.normalize_users_search(None) is None
