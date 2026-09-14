"""app.services.xray_templates (NPVPN-2024).

Документы клиентского конфига самодостаточны: видов документов нет, каждое тело —
полный конфиг. Здесь — чтение активных тел, сессионный/процессный кэш и CRUD.
"""

from __future__ import annotations

import json
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
    BS_CONFIG_SLUG,
    DEFAULT_CONFIG_SLUG,
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


def _template(db: Session, *, slug: str) -> XrayTemplate:
    tpl = XrayTemplate(slug=slug, title=slug)
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
        tpl = _template(db, slug=DEFAULT_CONFIG_SLUG)
        _version(db, tpl.id, 1, '{"v": 1}')
        _version(db, tpl.id, 3, '{"v": 3}')
        _version(db, tpl.id, 2, '{"v": 2}')
        db.commit()

        bodies = get_active_bodies(db)

        assert bodies["configs"] == {tpl.id: '{"v": 3}'}


def test_active_bodies_reports_only_configs_and_default_id():
    """Ключей ровно два: карта тел по id и id дефолтного документа.

    Видов документов больше нет — шаблон перестал быть отдельной сущностью, поэтому
    ключа "template" (как и "profiles"/"profile_ids") в выдаче быть не должно.
    """
    engine = _engine()
    with Session(engine) as db:
        default_config = _template(db, slug=DEFAULT_CONFIG_SLUG)
        _version(db, default_config.id, 1, '{"routing": {"rules": ["default"]}}')
        bs_config = _template(db, slug=BS_CONFIG_SLUG)
        _version(db, bs_config.id, 1, '{"routing": {"rules": ["bs"]}}')
        db.commit()

        bodies = get_active_bodies(db)

        assert set(bodies) == {"configs", "default_id"}
        assert bodies["default_id"] == default_config.id
        assert bodies["configs"] == {
            default_config.id: '{"routing": {"rules": ["default"]}}',
            bs_config.id: '{"routing": {"rules": ["bs"]}}',
        }


def test_empty_or_blank_body_does_not_get_into_configs():
    """Пустое тело = «документ не заполнен»: в карту не попадает, и рендер уходит
    фолбэком на дефолтный документ (или на файловый шаблон)."""
    engine = _engine()
    with Session(engine) as db:
        blank = _template(db, slug="blank")
        _version(db, blank.id, 1, "   ")
        empty = _template(db, slug="empty")
        _version(db, empty.id, 1, "")
        db.commit()

        bodies = get_active_bodies(db)

        assert bodies["configs"] == {}


def test_default_id_is_reported_even_when_body_is_empty():
    """`default_id` отдаётся отдельно от карты тел именно потому, что при пустом теле
    документа в "configs" его нет: select_config обязан увидеть ссылку на дефолтный
    документ, обнаружить, что тела нет, и уйти на файловый шаблон."""
    engine = _engine()
    with Session(engine) as db:
        default_config = _template(db, slug=DEFAULT_CONFIG_SLUG)
        _version(db, default_config.id, 1, "   ")
        db.commit()

        bodies = get_active_bodies(db)

        assert bodies["default_id"] == default_config.id
        assert default_config.id not in bodies["configs"]


def test_missing_template_raises_lookup_error_not_conflict(db):
    """404, а не 409: «документа нет» — не нарушение правил документов."""
    with pytest.raises(LookupError):
        svc.save_version(db, 99999, "{}", None, _Admin())
    with pytest.raises(LookupError):
        svc.delete_config(db, 99999)


def test_template_without_any_versions_does_not_break_query():
    engine = _engine()
    with Session(engine) as db:
        _template(db, slug="orphan")  # без единой версии
        default_config = _template(db, slug=DEFAULT_CONFIG_SLUG)
        _version(db, default_config.id, 1, '{"rules": []}')
        db.commit()

        bodies = get_active_bodies(db)

        assert bodies["configs"] == {default_config.id: '{"rules": []}'}
        assert bodies["default_id"] == default_config.id


def test_repeat_call_in_same_session_does_not_query_again():
    """Сессионный кэш (db.info): второй вызов в той же сессии не должен трогать БД."""
    engine = _engine()
    with Session(engine) as db:
        tpl = _template(db, slug=DEFAULT_CONFIG_SLUG)
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
    удаления документа). Состояние — как после миграции: два самодостаточных документа."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    for slug, title in (
        (DEFAULT_CONFIG_SLUG, "Обычные ноды"),
        (BS_CONFIG_SLUG, "БС-ноды"),
    ):
        template = XrayTemplate(slug=slug, title=title)
        session.add(template)
        session.flush()
        session.add(XrayTemplateVersion(template_id=template.id, version=1, body="", author_username="migration"))
    session.commit()
    yield session
    session.close()


def _template_id(db, slug):
    return db.query(XrayTemplate).filter(XrayTemplate.slug == slug).one().id


def test_save_appends_new_version(db):
    tid = _template_id(db, DEFAULT_CONFIG_SLUG)
    svc.save_version(db, tid, '{"outbounds": []}', "первая правка", _Admin())
    versions = svc.list_versions(db, tid, limit=10, offset=0)
    assert [v["version"] for v in versions] == [2, 1]
    assert versions[0]["author_username"] == "sudo"
    assert versions[0]["comment"] == "первая правка"


def test_active_body_is_the_highest_version(db):
    tid = _template_id(db, DEFAULT_CONFIG_SLUG)
    svc.save_version(db, tid, '{"a": 1}', None, _Admin())
    svc.save_version(db, tid, '{"a": 2}', None, _Admin())
    assert svc.get_active_bodies(db)["configs"][tid] == '{"a": 2}'


def test_revert_creates_new_version_and_keeps_history(db):
    tid = _template_id(db, DEFAULT_CONFIG_SLUG)
    svc.save_version(db, tid, '{"a": 1}', None, _Admin())
    svc.save_version(db, tid, '{"a": 2}', None, _Admin())
    svc.revert(db, tid, 2, _Admin())
    versions = svc.list_versions(db, tid, limit=10, offset=0)
    assert [v["version"] for v in versions] == [4, 3, 2, 1]
    assert svc.get_active_bodies(db)["configs"][tid] == '{"a": 1}'
    # История append-only: старые версии на месте, тела не переписаны.
    assert svc.get_version(db, tid, 3).body == '{"a": 2}'


def test_invalid_json_is_rejected_and_no_version_written(db):
    tid = _template_id(db, DEFAULT_CONFIG_SLUG)
    with pytest.raises(svc.InvalidTemplateBody):
        svc.save_version(db, tid, "{not json", None, _Admin())
    assert [v["version"] for v in svc.list_versions(db, tid, limit=10, offset=0)] == [1]


def test_empty_body_is_allowed(db):
    tid = _template_id(db, DEFAULT_CONFIG_SLUG)
    svc.save_version(db, tid, "   ", None, _Admin())
    assert svc.get_active_bodies(db)["configs"].get(tid) in (None, "   ")


def test_configs_map_skips_blank_bodies(db):
    bs_id = _template_id(db, BS_CONFIG_SLUG)
    svc.save_version(db, bs_id, '{"rules": []}', None, _Admin())
    bodies = svc.get_active_bodies(db)
    assert bodies["configs"][bs_id] == '{"rules": []}'
    assert _template_id(db, DEFAULT_CONFIG_SLUG) not in bodies["configs"]


def test_deleting_config_resets_bound_hosts(db):
    """NPVPN-2024: привязка живёт на ProxyHost, а не на Node — delete_config обязан
    сбрасывать client_config_id у хостов, а не у нод (в БД это делает ON DELETE
    SET NULL у хостового FK, здесь проверяем то же самое в ORM-сессии)."""
    bs_id = _template_id(db, BS_CONFIG_SLUG)
    db.add(ProxyInbound(tag="VLESS_TCP_REALITY"))
    db.commit()
    db.add(
        ProxyHost(
            remark="host-1",
            address="1.2.3.4",
            inbound_tag="VLESS_TCP_REALITY",
            client_config_id=bs_id,
        )
    )
    db.commit()
    svc.delete_config(db, bs_id)
    assert db.query(ProxyHost).one().client_config_id is None


def test_default_config_cannot_be_deleted(db):
    """Единственный неудаляемый документ — `default`: он последняя ступень фолбэка для
    хостов без привязки. Любой другой документ (включая `bs`) удаляется свободно."""
    with pytest.raises(svc.XrayTemplateError):
        svc.delete_config(db, _template_id(db, DEFAULT_CONFIG_SLUG))
    svc.delete_config(db, _template_id(db, BS_CONFIG_SLUG))


def test_created_config_copies_default_body(db):
    """Пустой самодостаточный конфиг бессмыслен: новый документ рождается копией дефолтного."""
    default_id = _template_id(db, DEFAULT_CONFIG_SLUG)
    svc.save_version(db, default_id, '{"dns": {"servers": ["1.1.1.1"]}}', None, _Admin())

    created = svc.create_config(db, "eu", "Европа", _Admin())

    assert [v["version"] for v in svc.list_versions(db, created["id"], limit=10, offset=0)] == [1]
    assert json.loads(svc.get_version(db, created["id"], 1).body) == {"dns": {"servers": ["1.1.1.1"]}}


def test_duplicate_slug_is_rejected(db):
    svc.create_config(db, "mobile", "Мобильные", _Admin())
    with pytest.raises(svc.XrayTemplateError):
        svc.create_config(db, "mobile", "Дубль", _Admin())


def test_invalidate_called_on_save_refreshes_process_cache(db, monkeypatch):
    """Требование корректности: запись версии обязана сбрасывать get_cached_active_bodies,
    иначе подписка продолжит отдавать старое тело до перезапуска процесса (см. брифинг Task 3).

    get_cached_active_bodies() в проде открывает свою сессию через GetDB() — здесь
    подменяем её на сессию фикстуры, чтобы процессный кэш читал то же состояние, что и
    save_version() пишет.
    """
    import contextlib

    monkeypatch.setattr(svc, "GetDB", lambda: contextlib.nullcontext(db))
    tid = _template_id(db, DEFAULT_CONFIG_SLUG)
    svc.get_cached_active_bodies.cache_clear()
    svc.save_version(db, tid, '{"a": "before"}', None, _Admin())
    # Прогреваем кэш текущим состоянием БД (как это делает /sub/ на горячем пути).
    assert svc.get_cached_active_bodies()["configs"][tid] == '{"a": "before"}'
    svc.save_version(db, tid, '{"a": "after"}', None, _Admin())
    # Без invalidate() внутри save_version здесь осталось бы старое закэшированное значение.
    assert svc.get_cached_active_bodies()["configs"][tid] == '{"a": "after"}'


def test_delete_config_invalidates_process_cache(db, monkeypatch):
    """Тот же инвариант, что выше, но для пути удаления документа (Task 3 доказывала его
    только для записи версии через _append_version). delete_config тоже обязан звать
    invalidate(), иначе /sub/ продолжит отдавать тело уже удалённого документа из
    процессного кэша до перезапуска.
    """
    import contextlib

    monkeypatch.setattr(svc, "GetDB", lambda: contextlib.nullcontext(db))
    bs_id = _template_id(db, BS_CONFIG_SLUG)
    svc.save_version(db, bs_id, '{"rules": ["bs"]}', None, _Admin())
    svc.get_cached_active_bodies.cache_clear()
    # Прогреваем процессный кэш непустым телом удаляемого документа.
    assert svc.get_cached_active_bodies()["configs"][bs_id] == '{"rules": ["bs"]}'

    svc.delete_config(db, bs_id)

    # Именно процессный кэш — не get_active_bodies(db) — должен перестать отдавать тело.
    assert bs_id not in svc.get_cached_active_bodies()["configs"]


def test_assert_config_exists_rejects_unknown(db):
    """Видов документов нет: проверка свелась к «документ существует». Любой из двух
    мигрированных документов — валидная привязка хоста."""
    svc.assert_config_exists(db, _template_id(db, BS_CONFIG_SLUG))  # не бросает
    svc.assert_config_exists(db, _template_id(db, DEFAULT_CONFIG_SLUG))  # не бросает
    with pytest.raises(svc.XrayTemplateError):
        svc.assert_config_exists(db, 99999)


def test_assert_config_exists_allows_none(db):
    """None — валидное значение (документ default), а не «документ не найден»."""
    svc.assert_config_exists(db, None)  # не бросает
    svc.get_cached_active_bodies.cache_clear()


def test_list_documents_reports_default_as_not_deletable(db):
    docs = svc.list_documents(db)
    by_slug = {doc["slug"]: doc for doc in docs}
    assert set(by_slug) == {DEFAULT_CONFIG_SLUG, BS_CONFIG_SLUG}
    assert by_slug[DEFAULT_CONFIG_SLUG]["deletable"] is False
    assert by_slug[BS_CONFIG_SLUG]["deletable"] is True
    assert all("kind" not in doc for doc in docs)
