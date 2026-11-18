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
        self.config_apply_pending = False
        self.status = status
        self.name = name or f"node-{node_id}"


@pytest.fixture
def job(monkeypatch):
    """Грузит app/jobs/0_xray_core.py с заглушками вместо БД, xray и FastAPI-инстанса.

    Имя файла начинается с цифры, поэтому обычный import невозможен — только по пути.
    """
    app_pkg = sys.modules["app"]
    app_instance = MagicMock()
    app_instance.on_event.side_effect = lambda _event: lambda func: func
    monkeypatch.setattr(app_pkg, "app", app_instance, raising=False)
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


def test_node_wave_is_not_built_before_executor_admission(job):
    include_db_users = _arrange(job, [_DBNode(1, _NodeStatus.error)])

    job.core_health_check()

    include_db_users.assert_not_called()
    job.xray.operations.connect_node.assert_called_once()
    assert job.xray.operations.connect_node.call_args.args == (1,)


def test_repeated_health_requests_carry_no_wave_config(job):
    """Конфиг волны один на тик — иначе каждая нода тащила бы свою копию всех юзеров."""
    include_db_users = _arrange(
        job,
        [_DBNode(1, _NodeStatus.error), _DBNode(2, _NodeStatus.error), _DBNode(3, _NodeStatus.error)],
    )

    job.core_health_check()

    include_db_users.assert_not_called()
    assert job.xray.operations.connect_node.call_count == 3

    assert all(len(call.args) == 1 for call in job.xray.operations.connect_node.call_args_list)


def test_previous_wave_memory_is_returned_to_kernel(job, monkeypatch):
    """Тик начинается с возврата памяти прошлой волны — иначе RSS копится между волнами."""
    calls = []
    monkeypatch.setattr(job, "trim_malloc", lambda: calls.append("trim") or True)
    _arrange(job, [_DBNode(1, _NodeStatus.connected)])

    job.core_health_check()

    assert calls == ["trim"]


def test_app_shutdown_releases_remote_nodes(job):
    job.app_shutdown()

    job.xray.core.stop.assert_called_once()
    job.xray.operations.release_remote_nodes.assert_called_once()


def test_missing_node_transport_is_created_only_after_admission(job):
    _arrange(job, [_DBNode(1, _NodeStatus.error)])
    job.xray.nodes = {}
    job.core_health_check()
    job.xray.operations.add_node.assert_not_called()
    job.xray.operations.connect_node.assert_called_once()


@pytest.mark.parametrize("status", [_NodeStatus.connecting, _NodeStatus.disabled])
def test_health_recovers_pending_manual_apply_including_disabled(job, status):
    """Незавершённая ручная правка восстанавливается существующим health тиком."""
    node = _DBNode(7, status)
    node.config_apply_pending = True
    job.crud.get_nodes.return_value = [node]
    job.xray.core.started = True
    job.core_health_check()
    job.xray.operations.apply_node.assert_called_once_with(7, recover=True)
    job.xray.operations.connect_node.assert_not_called()
    job.crud.get_nodes.assert_called_once_with(
        db=job.crud.get_nodes.call_args.kwargs["db"], enabled=True, include_pending=True
    )


def test_startup_keeps_pending_and_separates_normal_restore(job):
    """Startup восстанавливает pending HARD и отключение, остальные ноды — SOFT."""
    nodes = [_DBNode(7, _NodeStatus.connecting), _DBNode(8, _NodeStatus.disabled), _DBNode(9, _NodeStatus.connected)]
    nodes[0].config_apply_pending = nodes[1].config_apply_pending = True
    job.crud.get_nodes.return_value = nodes
    job.start_core()
    assert [call.args[0] for call in job.xray.operations.apply_node.call_args_list] == [7, 8]
    job.xray.operations.connect_nodes.assert_called_once_with([9])
    assert [call.args[1].id for call in job.crud.update_node_status.call_args_list] == [9]


def test_pending_failure_does_not_starve_other_node_at_cap_one(job, monkeypatch):
    pending = _DBNode(7, _NodeStatus.disabled)
    pending.config_apply_pending = True
    other = _DBNode(8, _NodeStatus.error)
    job.crud.get_nodes.return_value = [pending, other]
    job.xray.core.started = True
    job.xray.nodes = {}
    monkeypatch.setattr(job, "XRAY_NODE_MAX_CONCURRENT_CONNECTS", 1)
    for _ in range(3):
        job.core_health_check()
    assert job.xray.operations.connect_node.call_count == 3
    assert all(call.args[0] == 8 for call in job.xray.operations.connect_node.call_args_list)
