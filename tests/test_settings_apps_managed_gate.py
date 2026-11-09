"""PUT /api/settings/apps сохраняет каталог и при устаревшей managed-пометке.

`app.routers.settings` на уровне модуля тянет `app.db` (Session/get_db/crud) и
`app.models.admin.Admin`. В реальности эти импорты доходят до SQLAlchemy-моделей
(`app.db.crud` -> `app.db.models` -> `app.xray` -> `app.models.proxy` ->
`app.utils.system` -> `app.scheduler`) — тяжёлых зависимостей, недоступных в
песочнице `tests/conftest.py` (см. её докстринг про заглушку `app`). Прямой
`import app.routers.settings` также запускает `app/routers/__init__.py`,
который eagerly импортирует вообще все роутеры (включая `admin.py` с тем же
`app.db`) — падает ещё раньше, на сборе теста.

Чтобы проверить сам роутер (а не только пересказ его логики), стабим ровно
`app.db` и `app.models.admin` минимальными заглушками; `app.services.client_apps`
и `app.services.managed_settings` подхватывают тот же стаб `app.db` и грузятся
настоящими. Сам `app/routers/settings.py` грузим напрямую через `importlib`, в
обход `app/routers/__init__.py`.

Стабинг сделан через `monkeypatch`, а не голым присвоением `sys.modules[...]` на
уровне модуля (как в tests/test_subscription_bs_render.py). Тот файл ставит СВОЙ
`app.db`/`app.db.crud` на уровне модуля НАВСЕГДА (без отката) — при полном прогоне
`pytest -q` файлы делят один и тот же процесс и один `sys.modules`, а порядок сбора
алфавитный (`test_settings_apps_managed_gate` собирается раньше `test_subscription_
bs_render`). Голая подмена `crud` целиком перетёрла бы их заглушку (или наоборот —
их заглушка "тихо" не добавила бы наш `is_managed`, см. `_stub_module` там же:
"дописать недостающие атрибуты... их мог завести другой тест"), и один из наборов
тестов терял бы нужные ему функции crud. `monkeypatch` откатывает и добавленные
атрибуты, и целиком добавленные модули после каждого теста — оба файла остаются
независимы вне зависимости от порядка сбора/выполнения.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import types
from unittest.mock import MagicMock

import pytest

from app.models.settings import DEFAULT_CLIENT_APPS, ClientAppsPayload

_ROOT = pathlib.Path(__file__).parent.parent


def _get_db_stub():
    yield None


class _FakeAdmin:
    @staticmethod
    def get_current():
        return None

    @staticmethod
    def check_sudo_admin():
        return None


@pytest.fixture
def settings_router(monkeypatch):
    db_module = sys.modules.get("app.db")
    if db_module is None:
        db_module = types.ModuleType("app.db")
        monkeypatch.setitem(sys.modules, "app.db", db_module)
    if not hasattr(db_module, "Session"):
        monkeypatch.setattr(db_module, "Session", object, raising=False)
    if not hasattr(db_module, "get_db"):
        monkeypatch.setattr(db_module, "get_db", _get_db_stub, raising=False)
    if not hasattr(db_module, "GetDB"):
        monkeypatch.setattr(db_module, "GetDB", lambda: None, raising=False)

    # settings.py импортирует panel_settings, а тот — app.db.models.JWT.
    # В изолированном прогоне настоящего пакета моделей нет.
    models_module = sys.modules.get("app.db.models")
    if models_module is None:
        models_module = types.ModuleType("app.db.models")
        monkeypatch.setitem(sys.modules, "app.db.models", models_module)
    if not hasattr(models_module, "JWT"):
        monkeypatch.setattr(models_module, "JWT", object, raising=False)

    # crud — общий подобъект app.db, дописываем is_managed в существующий (если он уже
    # заведён другим тестом), а не подменяем целиком (см. докстринг модуля).
    crud_module = getattr(db_module, "crud", None)
    if crud_module is None:
        crud_module = types.SimpleNamespace()
        monkeypatch.setattr(db_module, "crud", crud_module, raising=False)
    if not hasattr(crud_module, "is_managed"):
        monkeypatch.setattr(crud_module, "is_managed", lambda db, key: False, raising=False)

    admin_module = sys.modules.get("app.models.admin")
    if admin_module is None:
        admin_module = types.ModuleType("app.models.admin")
        monkeypatch.setitem(sys.modules, "app.models.admin", admin_module)
    if not hasattr(admin_module, "Admin"):
        monkeypatch.setattr(admin_module, "Admin", _FakeAdmin, raising=False)

    spec = importlib.util.spec_from_file_location("app.routers.settings", _ROOT / "app" / "routers" / "settings.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "app.routers.settings", module)
    spec.loader.exec_module(module)
    return module


def test_put_saves_even_if_stale_managed_row_exists(settings_router, monkeypatch):
    import inspect

    monkeypatch.setattr(
        settings_router.client_apps_service, "save_client_apps", lambda db, payload: payload.model_dump()
    )
    assert "managed_by_admin" not in inspect.getsource(settings_router.update_client_apps)
    payload = ClientAppsPayload.model_validate(DEFAULT_CLIENT_APPS)
    result = settings_router.update_client_apps(payload=payload, db=MagicMock(), admin=object())
    assert result["apps"][0]["id"] == DEFAULT_CLIENT_APPS["apps"][0]["id"]


def test_put_allowed_when_not_managed(settings_router, monkeypatch):
    monkeypatch.setattr(
        settings_router.client_apps_service, "save_client_apps", lambda db, payload: payload.model_dump()
    )
    payload = ClientAppsPayload.model_validate(DEFAULT_CLIENT_APPS)
    result = settings_router.update_client_apps(payload=payload, db=MagicMock(), admin=object())
    assert "apps" in result
