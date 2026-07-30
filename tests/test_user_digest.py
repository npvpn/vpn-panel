"""Лёгкий срез юзеров для сверки с ботом (NPVPN-1643).

Существующий GET /api/users не годится: он вызывает ensure_subscription_token
на каждого юзера, то есть пишет в БД на чтении. Этот сервис читает три
колонки и ничего не пишет.
"""

from __future__ import annotations

from app.services.user_digest import get_users_digest


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows
        self.offset_applied = None
        self.limit_applied = None

    def join(self, *_args, **_kwargs):
        return self

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def offset(self, value):
        self.offset_applied = value
        return self

    def limit(self, value):
        self.limit_applied = value
        return self

    def count(self):
        return len(self._rows)

    def all(self):
        return list(self._rows)


class _FakeDb:
    def __init__(self, rows):
        self.last_query = _FakeQuery(rows)
        self.query_args = None

    def query(self, *args):
        self.query_args = args
        return self.last_query


def test_returns_three_fields_and_total():
    db = _FakeDb([("530399467_123", "active", 1767225600)])
    users, total = get_users_digest(db, admins=None, bot_username=None, offset=None, limit=None)
    assert users == [{"username": "530399467_123", "status": "active", "expire": 1767225600}]
    assert total == 1


def test_selects_only_three_columns():
    """Гарантия дешевизны: не грузим ORM-объекты, не тянем прокси и инбаунды."""
    db = _FakeDb([])
    get_users_digest(db, admins=None, bot_username=None, offset=None, limit=None)
    assert len(db.query_args) == 3


def test_pagination_is_passed_through():
    db = _FakeDb([])
    get_users_digest(db, admins=None, bot_username=None, offset=500, limit=500)
    assert db.last_query.offset_applied == 500
    assert db.last_query.limit_applied == 500


def test_null_expire_is_preserved():
    db = _FakeDb([("530399467_123", "active", None)])
    users, _ = get_users_digest(db, admins=None, bot_username=None, offset=None, limit=None)
    assert users[0]["expire"] is None
