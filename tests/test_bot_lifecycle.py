import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


@pytest.fixture
def bot_router(monkeypatch):
    share = types.ModuleType("app.subscription.share")
    share.generate_v2ray_links = lambda *_args, **_kwargs: []
    with monkeypatch.context() as patch:
        patch.setitem(sys.modules, "app.subscription.share", share)
        spec = importlib.util.spec_from_file_location(
            "bot_lifecycle_routes_test", Path(__file__).parents[1] / "app/routers/bot.py"
        )
        route = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(route)
    return route


def test_panel_toggles_existing_bot_without_changing_panel_database(monkeypatch, bot_router):
    monkeypatch.setenv("PANEL_BOT_LIFECYCLE_TOKEN", "test-token")
    monkeypatch.setenv("PANEL_BOT_LIFECYCLE_URL", "https://backend.example/panel-bots")
    monkeypatch.setattr(
        bot_router.crud, "get_bot", Mock(return_value=SimpleNamespace(username="partner_bot", source_bot_id=17))
    )
    read = Mock(status_code=200)
    read.json.return_value = {"is_active": True, "active_subscriptions": 12}
    disabled = Mock(status_code=200)
    disabled.json.return_value = {"is_active": False}
    enabled = Mock(status_code=200)
    enabled.json.return_value = {"is_active": True}
    responses = iter([read, disabled, enabled])
    db = MagicMock()
    connection = Mock()
    db.__enter__.return_value = connection
    monkeypatch.setattr(bot_router, "GetDB", Mock(return_value=db))

    def send_after_db_closed(*_args, **_kwargs):
        assert db.__enter__.call_count == db.__exit__.call_count
        return next(responses)

    send = Mock(side_effect=send_after_db_closed)
    monkeypatch.setattr(bot_router.requests, "request", send)

    before = bot_router.get_bot_lifecycle("partner_bot", Mock())
    after_disable = bot_router.update_bot_lifecycle(
        "partner_bot", bot_router.BotLifecycleUpdate(is_active=False), Mock()
    )
    after_enable = bot_router.update_bot_lifecycle("partner_bot", bot_router.BotLifecycleUpdate(is_active=True), Mock())

    assert (before.is_active, before.active_subscriptions) == (True, 12)
    assert after_disable.is_active is False
    assert after_enable.is_active is True
    assert [request.args[0] for request in send.call_args_list] == ["GET", "PATCH", "PATCH"]
    assert send.call_args.kwargs["params"] == {"active": "true", "source_bot_id": "17"}
    assert send.call_args.kwargs["allow_redirects"] is False
    assert connection.mock_calls == []


def test_unconfigured_panel_does_not_attempt_to_change_bot(monkeypatch, bot_router):
    monkeypatch.delenv("PANEL_BOT_LIFECYCLE_TOKEN", raising=False)
    monkeypatch.setattr(bot_router.crud, "get_bot", Mock(return_value=SimpleNamespace(username="partner_bot")))
    send = Mock()
    monkeypatch.setattr(bot_router.requests, "request", send)

    with pytest.raises(HTTPException) as error:
        bot_router.update_bot_lifecycle("partner_bot", bot_router.BotLifecycleUpdate(is_active=False), Mock())
    assert error.value.status_code == 404
    send.assert_not_called()


@pytest.mark.parametrize("method", ["GET", "PATCH"])
def test_operator_cannot_access_lifecycle_route(monkeypatch, bot_router, method):
    app = FastAPI()
    app.include_router(bot_router.router)
    monkeypatch.setattr(bot_router, "GetDB", MagicMock())
    monkeypatch.setattr(bot_router.Admin, "get_admin", Mock(return_value=SimpleNamespace(is_sudo=False)))
    lifecycle = Mock()
    monkeypatch.setattr(bot_router, "_bot_lifecycle", lifecycle)
    with TestClient(app) as client:
        response = client.request(
            method,
            "/api/bots/partner_bot/lifecycle",
            headers={"Authorization": "Bearer example"},
            json={"is_active": False},
        )
    assert response.status_code == 403
    lifecycle.assert_not_called()


@pytest.mark.parametrize(("detail", "status"), [("Not Found", 502), ("bot_lifecycle_unavailable", 404)])
def test_unknown_upstream_route_is_an_infrastructure_error(monkeypatch, bot_router, detail, status):
    monkeypatch.setenv("PANEL_BOT_LIFECYCLE_TOKEN", "test-token")
    monkeypatch.setenv("PANEL_BOT_LIFECYCLE_URL", "https://backend.example/panel-bots")
    monkeypatch.setattr(bot_router, "GetDB", MagicMock())
    monkeypatch.setattr(
        bot_router.crud, "get_bot", Mock(return_value=SimpleNamespace(username="partner_bot", source_bot_id=17))
    )
    response = Mock(status_code=404)
    response.json.return_value = {"detail": detail}
    monkeypatch.setattr(bot_router.requests, "request", Mock(return_value=response))

    with pytest.raises(HTTPException) as error:
        bot_router.get_bot_lifecycle("partner_bot", Mock())
    assert error.value.status_code == status
