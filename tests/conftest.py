"""Минимальный pytest-харнесс для панели.

app/__init__.py поднимает FastAPI и тяжёлые зависимости при импорте.
Чтобы тесты app.xray.inbound_filter (без БД/окружения) работали без полного
окружения, заглушаем app как пустой пакет до того, как pytest начнёт сбор.
"""

import logging
import os
import pathlib
import sys
import types
from unittest.mock import MagicMock

_APP_DIR = pathlib.Path(__file__).parent.parent / "app"

# Тесты не должны создавать db.sqlite3 из дефолта config.py: модели/джобы работают
# на своих in-memory движках (см. test_record_bs_usage.py).
os.environ.setdefault("SQLALCHEMY_DATABASE_URL", "sqlite://")

# Регистрируем app как пустой пакет — тогда `from app.xray.inbound_filter import …`
# не запускает app/__init__.py, а берёт app.xray из реального файла.
if "app" not in sys.modules:
    app_stub = types.ModuleType("app")
    # Указываем реальный путь пакета, чтобы Python мог найти субмодули
    # (logging_config, logging_context, xray.*, subscription.*) без запуска app/__init__.py.
    app_stub.__path__ = [str(_APP_DIR)]
    app_stub.__package__ = "app"
    # app.db.base / app.jobs.* берут logger и scheduler прямо из пакета app.
    app_stub.logger = logging.getLogger("panel.tests")
    app_stub.scheduler = MagicMock()
    sys.modules["app"] = app_stub

if "app.xray" not in sys.modules:
    import pathlib

    # Загружаем реальный app/xray/__init__.py напрямую через spec,
    # но он тоже тяжёлый — вместо этого регистрируем заглушку пакета,
    # и Python найдёт app/xray/inbound_filter.py через обычный механизм.
    xray_stub = types.ModuleType("app.xray")
    xray_stub.__path__ = [str(_APP_DIR / "xray")]
    xray_stub.__package__ = "app.xray"
    sys.modules["app.xray"] = xray_stub

if "app.jobs" not in sys.modules:
    # app/jobs/__init__.py грузит ВСЕ джобы пакета (включая те, что тянут FastAPI-инстанс),
    # поэтому пакет тоже заглушаем — отдельный джоб импортируется как обычный субмодуль.
    jobs_stub = types.ModuleType("app.jobs")
    jobs_stub.__path__ = [str(_APP_DIR / "jobs")]
    jobs_stub.__package__ = "app.jobs"
    sys.modules["app.jobs"] = jobs_stub

if "app.subscription" not in sys.modules:
    # Заглушка пакета app.subscription с реальным путём — Python найдёт
    # app/subscription/device_ua.py, sub_stub.py, custom_headers.py и др.,
    # не выполняя app/subscription/__init__.py.
    subscription_stub = types.ModuleType("app.subscription")
    subscription_stub.__path__ = [str(_APP_DIR / "subscription")]
    subscription_stub.__package__ = "app.subscription"
    sys.modules["app.subscription"] = subscription_stub
