"""app.services.xray_templates.get_active_bodies (NPVPN-2024).

Только чтение активных тел (шаблон + routing-профили) и сессионный кэш. Запись версий,
откат и CRUD профилей — Task 3, здесь не тестируются.
"""

from __future__ import annotations

import sys
import types

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

_share_stub = types.ModuleType("app.subscription.share")
_share_stub.generate_v2ray_links = lambda *args, **kwargs: []
sys.modules.setdefault("app.subscription.share", _share_stub)

from app.db.base import Base  # noqa: E402
from app.db.models import (  # noqa: E402
    BS_PROFILE_SLUG,
    DEFAULT_PROFILE_SLUG,
    PROFILE_KIND,
    TEMPLATE_KIND,
    TEMPLATE_SLUG,
    ProxyHost,
    ProxyInbound,
    XrayTemplate,
    XrayTemplateVersion,
)
from app.services import xray_templates as svc  # noqa: E402
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


def test_default_profile_id_is_reported_even_when_body_is_empty():
    """`default_profile_id` — отдельный ключ именно потому, что при пустом теле документа
    в "profiles" его нет: share.py по этому id достаёт вторую ступень фолбэка, и её
    отсутствие обязано означать «падать на routing шаблона», а не «профиль потерян»."""
    engine = _engine()
    with Session(engine) as db:
        tpl = _template(db, kind=TEMPLATE_KIND, slug=TEMPLATE_SLUG)
        _version(db, tpl.id, 1, '{"tpl": true}')
        default_profile = _template(db, kind=PROFILE_KIND, slug=DEFAULT_PROFILE_SLUG)
        _version(db, default_profile.id, 1, "   ")
        db.commit()

        bodies = get_active_bodies(db)

        assert bodies["default_profile_id"] == default_profile.id
        assert default_profile.id not in bodies["profiles"]


def test_default_profile_id_points_at_non_empty_default_body():
    engine = _engine()
    with Session(engine) as db:
        default_profile = _template(db, kind=PROFILE_KIND, slug=DEFAULT_PROFILE_SLUG)
        _version(db, default_profile.id, 1, '{"rules": ["default"]}')
        other = _template(db, kind=PROFILE_KIND, slug=BS_PROFILE_SLUG)
        _version(db, other.id, 1, '{"rules": ["bs"]}')
        db.commit()

        bodies = get_active_bodies(db)

        assert bodies["default_profile_id"] == default_profile.id
        assert bodies["profiles"][default_profile.id] == '{"rules": ["default"]}'


def test_missing_template_raises_lookup_error_not_conflict(db):
    """404, а не 409: «документа нет» — не нарушение правил документов."""
    with pytest.raises(LookupError):
        svc.save_version(db, 99999, "{}", None, _Admin())
    with pytest.raises(LookupError):
        svc.delete_profile(db, 99999)


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


class _Admin:
    """Заглушка sudo-админа для сервисных тестов (id + username, как в моделях)."""

    id = 1
    username = "sudo"


@pytest.fixture()
def db():
    """Отдельная in-memory БД с полной схемой (ProxyHost/ProxyInbound нужны для теста
    удаления профиля)."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    for slug, kind, title in (
        (TEMPLATE_SLUG, TEMPLATE_KIND, "v2ray-json шаблон"),
        (DEFAULT_PROFILE_SLUG, PROFILE_KIND, "Обычные ноды"),
        (BS_PROFILE_SLUG, PROFILE_KIND, "БС-ноды"),
    ):
        template = XrayTemplate(kind=kind, slug=slug, title=title)
        session.add(template)
        session.flush()
        session.add(XrayTemplateVersion(template_id=template.id, version=1, body="", author_username="migration"))
    session.commit()
    yield session
    session.close()


def _template_id(db, slug):
    return db.query(XrayTemplate).filter(XrayTemplate.slug == slug).one().id


def test_save_appends_new_version(db):
    tid = _template_id(db, TEMPLATE_SLUG)
    svc.save_version(db, tid, '{"outbounds": []}', "первая правка", _Admin())
    versions = svc.list_versions(db, tid, limit=10, offset=0)
    assert [v["version"] for v in versions] == [2, 1]
    assert versions[0]["author_username"] == "sudo"
    assert versions[0]["comment"] == "первая правка"


def test_active_body_is_the_highest_version(db):
    tid = _template_id(db, TEMPLATE_SLUG)
    svc.save_version(db, tid, '{"a": 1}', None, _Admin())
    svc.save_version(db, tid, '{"a": 2}', None, _Admin())
    assert svc.get_active_bodies(db)["template"] == '{"a": 2}'


def test_revert_creates_new_version_and_keeps_history(db):
    tid = _template_id(db, TEMPLATE_SLUG)
    svc.save_version(db, tid, '{"a": 1}', None, _Admin())
    svc.save_version(db, tid, '{"a": 2}', None, _Admin())
    svc.revert(db, tid, 2, _Admin())
    versions = svc.list_versions(db, tid, limit=10, offset=0)
    assert [v["version"] for v in versions] == [4, 3, 2, 1]
    assert svc.get_active_bodies(db)["template"] == '{"a": 1}'
    # История append-only: старые версии на месте, тела не переписаны.
    assert svc.get_version(db, tid, 3).body == '{"a": 2}'


def test_invalid_json_is_rejected_and_no_version_written(db):
    tid = _template_id(db, TEMPLATE_SLUG)
    with pytest.raises(svc.InvalidTemplateBody):
        svc.save_version(db, tid, "{not json", None, _Admin())
    assert [v["version"] for v in svc.list_versions(db, tid, limit=10, offset=0)] == [1]


def test_empty_body_is_allowed(db):
    tid = _template_id(db, DEFAULT_PROFILE_SLUG)
    svc.save_version(db, tid, "   ", None, _Admin())
    assert svc.get_active_bodies(db)["profiles"].get(tid) in (None, "   ")


def test_profiles_map_skips_blank_bodies(db):
    bs_id = _template_id(db, BS_PROFILE_SLUG)
    svc.save_version(db, bs_id, '{"rules": []}', None, _Admin())
    bodies = svc.get_active_bodies(db)
    assert bodies["profiles"][bs_id] == '{"rules": []}'
    assert _template_id(db, DEFAULT_PROFILE_SLUG) not in bodies["profiles"]


def test_deleting_profile_resets_bound_hosts(db):
    """NPVPN-2024: привязка живёт на ProxyHost, а не на Node — delete_profile обязан
    сбрасывать routing_profile_id у хостов, а не у нод (в БД это делает ON DELETE
    SET NULL у хостового FK, здесь проверяем то же самое в ORM-сессии)."""
    bs_id = _template_id(db, BS_PROFILE_SLUG)
    db.add(ProxyInbound(tag="VLESS_TCP_REALITY"))
    db.commit()
    db.add(
        ProxyHost(
            remark="host-1",
            address="1.2.3.4",
            inbound_tag="VLESS_TCP_REALITY",
            routing_profile_id=bs_id,
        )
    )
    db.commit()
    svc.delete_profile(db, bs_id)
    assert db.query(ProxyHost).one().routing_profile_id is None


def test_template_and_default_profile_cannot_be_deleted(db):
    with pytest.raises(svc.XrayTemplateError):
        svc.delete_profile(db, _template_id(db, TEMPLATE_SLUG))
    with pytest.raises(svc.XrayTemplateError):
        svc.delete_profile(db, _template_id(db, DEFAULT_PROFILE_SLUG))


def test_created_profile_starts_with_empty_version_one(db):
    created = svc.create_profile(db, "mobile", "Мобильные", _Admin())
    versions = svc.list_versions(db, created["id"], limit=10, offset=0)
    assert [v["version"] for v in versions] == [1]
    assert svc.get_version(db, created["id"], 1).body == ""


def test_duplicate_slug_is_rejected(db):
    svc.create_profile(db, "mobile", "Мобильные", _Admin())
    with pytest.raises(svc.XrayTemplateError):
        svc.create_profile(db, "mobile", "Дубль", _Admin())


def test_invalidate_called_on_save_refreshes_process_cache(db, monkeypatch):
    """Требование корректности: запись версии обязана сбрасывать get_cached_active_bodies,
    иначе подписка продолжит отдавать старое тело до перезапуска процесса (см. брифинг Task 3).

    get_cached_active_bodies() в проде открывает свою сессию через GetDB() — здесь
    подменяем её на сессию фикстуры, чтобы процессный кэш читал то же состояние, что и
    save_version() пишет.
    """
    import contextlib

    monkeypatch.setattr(svc, "GetDB", lambda: contextlib.nullcontext(db))
    tid = _template_id(db, TEMPLATE_SLUG)
    svc.get_cached_active_bodies.cache_clear()
    svc.save_version(db, tid, '{"a": "before"}', None, _Admin())
    # Прогреваем кэш текущим состоянием БД (как это делает /sub/ на горячем пути).
    assert svc.get_cached_active_bodies()["template"] == '{"a": "before"}'
    svc.save_version(db, tid, '{"a": "after"}', None, _Admin())
    # Без invalidate() внутри save_version здесь осталось бы старое закэшированное значение.
    assert svc.get_cached_active_bodies()["template"] == '{"a": "after"}'


def test_delete_profile_invalidates_process_cache(db, monkeypatch):
    """Тот же инвариант, что выше, но для пути удаления профиля (Task 3 доказывала его
    только для записи версии через _append_version). delete_profile тоже обязан звать
    invalidate(), иначе /sub/ продолжит отдавать тело уже удалённого профиля из процессного
    кэша до перезапуска.
    """
    import contextlib

    monkeypatch.setattr(svc, "GetDB", lambda: contextlib.nullcontext(db))
    bs_id = _template_id(db, BS_PROFILE_SLUG)
    svc.save_version(db, bs_id, '{"rules": ["bs"]}', None, _Admin())
    svc.get_cached_active_bodies.cache_clear()
    # Прогреваем процессный кэш непустым телом удаляемого профиля.
    assert svc.get_cached_active_bodies()["profiles"][bs_id] == '{"rules": ["bs"]}'

    svc.delete_profile(db, bs_id)

    # Именно процессный кэш — не get_active_bodies(db) — должен перестать отдавать тело.
    assert bs_id not in svc.get_cached_active_bodies()["profiles"]


def test_assert_profile_exists_rejects_template_and_unknown(db):
    svc.assert_profile_exists(db, _template_id(db, BS_PROFILE_SLUG))  # не бросает
    with pytest.raises(svc.XrayTemplateError):
        svc.assert_profile_exists(db, _template_id(db, TEMPLATE_SLUG))
    with pytest.raises(svc.XrayTemplateError):
        svc.assert_profile_exists(db, 99999)


def test_assert_profile_exists_allows_none(db):
    """None — валидное значение (профиль default), а не «профиль не найден»."""
    svc.assert_profile_exists(db, None)  # не бросает
    svc.get_cached_active_bodies.cache_clear()
