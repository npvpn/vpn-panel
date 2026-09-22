"""Когда health-check материализует полный конфиг волны (NPVPN-2120).

include_db_users() собирает конфиг со ВСЕМИ юзерами: на opl это 4-16 секунд и сотни
мегабайт, с которых потом снимается по копии на каждую подключаемую ноду. Раньше он
строился до проверок `_should_force_reconnect` / `is_connect_in_progress`, то есть и на
тиках, где ни один реконнект в итоге не планировался. При двух десятках нод, вечно
висящих в `connecting` с живым локом, панель собирала его вхолостую каждые
JOB_CORE_HEALTH_CHECK_INTERVAL секунд, распухала до 5.7 ГБ RSS и уводила хост в
swap-thrashing. Здесь зафиксировано, что сборка происходит ровно тогда, когда конфиг
кому-то отдают, и ровно один раз на тик.
"""

import enum
import importlib.util
import pathlib
import sys
import types
from unittest.mock import MagicMock

import pytest

_JOB_PATH = pathlib.Path(__file__).parent.parent / "app" / "jobs" / "0_xray_core.py"


class _NodeStatus(str, enum.Enum):
    connected = "connected"
    connecting = "connecting"
    error = "error"
    disabled = "disabled"


class _DBNode:
    def __init__(self, node_id, status, name=None):
        self.id = node_id
        self.status = status
        self.name = name or f"node-{node_id}"


@pytest.fixture
def job(monkeypatch):
    """Грузит app/jobs/0_xray_core.py с заглушками вместо БД, xray и FastAPI-инстанса.

    Имя файла начинается с цифры, поэтому обычный import невозможен — только по пути.
    """
    app_pkg = sys.modules["app"]
    monkeypatch.setattr(app_pkg, "app", MagicMock(), raising=False)
    monkeypatch.setattr(app_pkg, "xray", MagicMock(), raising=False)

    db_stub = types.ModuleType("app.db")
    db_stub.GetDB = MagicMock()
    db_stub.GetDB.return_value.__enter__ = MagicMock(return_value=MagicMock())
    db_stub.GetDB.return_value.__exit__ = MagicMock(return_value=False)
    db_stub.crud = MagicMock()

    node_models_stub = types.ModuleType("app.models.node")
    node_models_stub.NodeStatus = _NodeStatus

    xray_node_stub = types.ModuleType("app.xray.node")
    xray_node_stub.NodeAPIError = type("NodeAPIError", (Exception,), {})

    xray_api_stub = types.ModuleType("xray_api")
    xray_api_exc_stub = types.ModuleType("xray_api.exc")
    xray_api_exc_stub.XrayError = type("XrayError", (Exception,), {})
    xray_api_stub.exc = xray_api_exc_stub

    for name, module in (
        ("app.db", db_stub),
        ("app.models", types.ModuleType("app.models")),
        ("app.models.node", node_models_stub),
        ("app.xray.node", xray_node_stub),
        ("xray_api", xray_api_stub),
        ("xray_api.exc", xray_api_exc_stub),
    ):
        monkeypatch.setitem(sys.modules, name, module)

    spec = importlib.util.spec_from_file_location("panel_job_xray_core", _JOB_PATH)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "panel_job_xray_core", module)
    spec.loader.exec_module(module)

    module.crud = db_stub.crud
    return module


def _healthy_node():
    node = MagicMock()
    node.connected = True
    node.started = True
    return node


def _arrange(job, dbnodes, *, in_progress=False, stale=False):
    """Готовит xray-заглушку под заданный набор нод и возвращает счётчик сборок."""
    job.crud.get_nodes.return_value = dbnodes

    job.xray.core.started = True
    job.xray.nodes = {dbnode.id: _healthy_node() for dbnode in dbnodes}
    job.xray.config.include_db_users.return_value = {"wave": "config"}

    job.xray.operations.is_connect_in_progress.return_value = in_progress
    job.xray.operations.is_connect_stale.return_value = stale
    job.xray.operations.connecting_age_seconds.return_value = None

    return job.xray.config.include_db_users


def test_no_wave_when_every_node_is_healthy(job):
    include_db_users = _arrange(job, [_DBNode(1, _NodeStatus.connected)])

    job.core_health_check()

    include_db_users.assert_not_called()
    job.xray.operations.connect_node.assert_not_called()


def test_no_wave_when_connecting_node_is_already_locked(job):
    """Главная регрессия: нода висит в connecting с живым локом, реконнекта не будет."""
    include_db_users = _arrange(job, [_DBNode(1, _NodeStatus.connecting)], in_progress=True, stale=False)

    job.core_health_check()

    include_db_users.assert_not_called()
    job.xray.operations.connect_node.assert_not_called()


def test_wave_is_built_when_node_needs_reconnect(job):
    include_db_users = _arrange(job, [_DBNode(1, _NodeStatus.error)])

    job.core_health_check()

    include_db_users.assert_called_once()
    job.xray.operations.connect_node.assert_called_once()
    assert job.xray.operations.connect_node.call_args.args[1] == {"wave": "config"}


def test_wave_is_built_once_per_tick_and_shared(job):
    """Конфиг волны один на тик — иначе каждая нода тащила бы свою копию всех юзеров."""
    include_db_users = _arrange(
        job,
        [_DBNode(1, _NodeStatus.error), _DBNode(2, _NodeStatus.error), _DBNode(3, _NodeStatus.error)],
    )

    job.core_health_check()

    include_db_users.assert_called_once()
    assert job.xray.operations.connect_node.call_count == 3

    configs = [call.args[1] for call in job.xray.operations.connect_node.call_args_list]
    assert all(config is configs[0] for config in configs)


def test_previous_wave_memory_is_returned_to_kernel(job, monkeypatch):
    """Тик начинается с возврата памяти прошлой волны — иначе RSS копится между волнами."""
    calls = []
    monkeypatch.setattr(job, "trim_malloc", lambda: calls.append("trim") or True)
    _arrange(job, [_DBNode(1, _NodeStatus.connected)])

    job.core_health_check()

    assert calls == ["trim"]
