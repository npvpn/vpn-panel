"""app.services.xray_templates.get_active_bodies (NPVPN-2024).

Только чтение активных тел (шаблон + routing-профили) и сессионный кэш. Запись версий,
откат и CRUD профилей — Task 3, здесь не тестируются.
"""

from __future__ import annotations

import sys
import types

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

_share_stub = types.ModuleType("app.subscription.share")
_share_stub.generate_v2ray_links = lambda *args, **kwargs: []
sys.modules.setdefault("app.subscription.share", _share_stub)

from app.db.base import Base  # noqa: E402
from app.db.models import PROFILE_KIND, TEMPLATE_KIND, XrayTemplate, XrayTemplateVersion  # noqa: E402
from app.services.xray_templates import get_active_bodies  # noqa: E402


def _engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[XrayTemplate.__table__, XrayTemplateVersion.__table__])
    return engine


def _template(db: Session, *, kind: str, slug: str) -> XrayTemplate:
    tpl = XrayTemplate(kind=kind, slug=slug, title=slug)
    db.add(tpl)
    db.flush()
    return tpl


def _version(db: Session, template_id: int, version: int, body: str) -> None:
    db.add(
        XrayTemplateVersion(
            template_id=template_id,
            version=version,
            body=body,
            author_username="",
        )
    )


def test_active_body_is_max_version_not_last_inserted_row():
    """Порядок ВСТАВКИ перемешан (3 раньше 2) — активной должна считаться версия 3."""
    engine = _engine()
    with Session(engine) as db:
        tpl = _template(db, kind=TEMPLATE_KIND, slug="v2ray_json")
        _version(db, tpl.id, 1, '{"v": 1}')
        _version(db, tpl.id, 3, '{"v": 3}')
        _version(db, tpl.id, 2, '{"v": 2}')
        db.commit()

        bodies = get_active_bodies(db)

        assert bodies["template"] == '{"v": 3}'


def test_template_kind_in_template_key_profile_kind_by_id():
    engine = _engine()
    with Session(engine) as db:
        tpl = _template(db, kind=TEMPLATE_KIND, slug="v2ray_json")
        _version(db, tpl.id, 1, '{"tpl": true}')
        profile = _template(db, kind=PROFILE_KIND, slug="default")
        _version(db, profile.id, 1, '{"rules": []}')
        db.commit()

        bodies = get_active_bodies(db)

        assert bodies["template"] == '{"tpl": true}'
        assert bodies["profiles"] == {profile.id: '{"rules": []}'}


def test_empty_or_blank_profile_body_excluded_empty_template_kept():
    engine = _engine()
    with Session(engine) as db:
        tpl = _template(db, kind=TEMPLATE_KIND, slug="v2ray_json")
        _version(db, tpl.id, 1, "")
        blank_profile = _template(db, kind=PROFILE_KIND, slug="blank")
        _version(db, blank_profile.id, 1, "   ")
        empty_profile = _template(db, kind=PROFILE_KIND, slug="empty")
        _version(db, empty_profile.id, 1, "")
        db.commit()

        bodies = get_active_bodies(db)

        assert bodies["template"] == ""  # пустой шаблон — валидный дефолт, остаётся в ключе
        assert bodies["profiles"] == {}  # пустые/пробельные тела профилей не попадают в карту


def test_template_without_any_versions_does_not_break_query():
    engine = _engine()
    with Session(engine) as db:
        _template(db, kind=TEMPLATE_KIND, slug="v2ray_json")  # без единой версии
        profile = _template(db, kind=PROFILE_KIND, slug="default")
        _version(db, profile.id, 1, '{"rules": []}')
        db.commit()

        bodies = get_active_bodies(db)

        assert bodies["template"] == ""
        assert bodies["profiles"] == {profile.id: '{"rules": []}'}


def test_repeat_call_in_same_session_does_not_query_again():
    """Сессионный кэш (db.info): второй вызов в той же сессии не должен трогать БД."""
    engine = _engine()
    with Session(engine) as db:
        tpl = _template(db, kind=TEMPLATE_KIND, slug="v2ray_json")
        _version(db, tpl.id, 1, '{"v": 1}')
        db.commit()

        first = get_active_bodies(db)

        query_calls = []
        original_query = db.query

        def _spy_query(*args, **kwargs):
            query_calls.append((args, kwargs))
            return original_query(*args, **kwargs)

        db.query = _spy_query
        second = get_active_bodies(db)

        assert second is first  # тот же закэшированный объект
        assert query_calls == []  # к БД не обращались вовсе
