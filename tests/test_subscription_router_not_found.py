"""Маршруты подписки, которые раньше отдавали браузеру голый JSON (NPVPN-2374).

Ссылка без токена (/sub/), опечатка в типе клиента и лишний хвост пути ведут на
ту же 404-страницу, что и неверный токен. Проверяем маршрутизацию FastAPI целиком:
ошибка тут — в сопоставлении путей и валидации параметров, а не в одной функции.

Роутер грузим напрямую через importlib (как tests/test_not_found_page.py), а
тяжёлый app.subscription.share заглушаем: он тянет xray-конфиги, ненужные здесь.
Запросы шлём прямо в ASGI-приложение — без TestClient, которому нужен httpx.
"""

from __future__ import annotations

import asyncio
import importlib.util
import pathlib
import sys
from unittest.mock import MagicMock

import pytest
from fastapi import APIRouter, FastAPI, Response

_ROOT = pathlib.Path(__file__).parent.parent
_TOKEN = "tok"


@pytest.fixture
def sub(monkeypatch):
    share = MagicMock()
    share.__name__ = "app.subscription.share"
    monkeypatch.setitem(sys.modules, "app.subscription.share", share)

    spec = importlib.util.spec_from_file_location("app.routers.subscription", _ROOT / "app/routers/subscription.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "app.routers.subscription", module)
    spec.loader.exec_module(module)

    calls: list[str] = []

    def _not_found(request, db, token):
        calls.append(token)
        return Response(f"not-found:{token}", status_code=404)

    monkeypatch.setattr(module, "render_not_found", _not_found)
    module.not_found_calls = calls
    return module


def _app(sub) -> FastAPI:
    from app.db import get_db

    app = FastAPI()
    app.include_router(sub.router)
    app.dependency_overrides[get_db] = lambda: None
    return app


def _get(app: FastAPI, path: str) -> tuple[int, bytes]:
    status, _, body = _request(app, path)
    return status, body


def _request(app: FastAPI, path: str, query: str = "") -> tuple[int, dict[bytes, bytes], bytes]:
    messages: list[dict] = []
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query.encode(),
        "headers": [(b"accept", b"text/html"), (b"host", b"panel.test")],
        "scheme": "http",
        "server": ("panel.test", 80),
        "client": ("127.0.0.1", 1),
        "root_path": "",
        "http_version": "1.1",
    }

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        messages.append(message)

    asyncio.run(app(scope, receive, send))
    body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return messages[0]["status"], dict(messages[0]["headers"]), body


@pytest.mark.parametrize("path", ["/sub", "/sub/"])
def test_link_without_token_gets_not_found_page(sub, path):
    status, body = _get(_app(sub), path)

    assert (status, body) == (404, b"not-found:")
    assert sub.not_found_calls == [""]


def test_unknown_client_type_gets_not_found_page_before_user_lookup(sub, monkeypatch):
    def _must_not_be_called(token, db):
        raise AssertionError("с неизвестным типом клиента пользователя не ищем")

    monkeypatch.setattr(sub, "resolve_subscription_context", _must_not_be_called)

    status, body = _get(_app(sub), f"/sub/{_TOKEN}/456465")

    # раньше: 422 с JSON от валидации regex в Path
    assert (status, body) == (404, f"not-found:{_TOKEN}".encode())


def test_known_client_type_with_bad_token_gets_not_found_page(sub, monkeypatch):
    monkeypatch.setattr(sub, "resolve_subscription_context", lambda token, db: (None, False, None))

    status, body = _get(_app(sub), f"/sub/{_TOKEN}/v2ray")

    assert (status, body) == (404, f"not-found:{_TOKEN}".encode())


# Типы из выданных ссылок: до NPVPN-2374 их держал regex в Path, теперь — только
# ключи client_config. Список фиксируем явно, чтобы рабочая ссылка не стала 404
@pytest.mark.parametrize("client_type", ["sing-box", "clash-meta", "clash", "outline", "v2ray", "v2ray-json", "incy"])
def test_known_client_type_with_user_renders_subscription(sub, monkeypatch, client_type):
    dbuser = MagicMock(expire=None)
    rendered: list = []

    def _render(db, ctx, plan):
        rendered.append(plan)
        return Response("subscription", status_code=200)

    monkeypatch.setattr(sub, "resolve_subscription_context", lambda token, db: (dbuser, False, None))
    monkeypatch.setattr(sub, "crud", MagicMock())
    monkeypatch.setattr(sub, "UserResponse", MagicMock())
    monkeypatch.setattr(sub, "resolve_bot_settings", lambda user: None)
    monkeypatch.setattr(sub, "get_panel_settings", lambda db: None)
    monkeypatch.setattr(sub, "build_render_context", lambda *args, **kwargs: "ctx")
    monkeypatch.setattr(sub, "render_subscription", _render)

    status, body = _get(_app(sub), f"/sub/{_TOKEN}/{client_type}")

    assert (status, body) == (200, b"subscription")
    assert [plan.config_format for plan in rendered] == [client_type]
    assert sub.not_found_calls == []


def test_extra_path_tail_gets_not_found_page(sub):
    status, body = _get(_app(sub), f"/sub/{_TOKEN}/a/b/c")

    assert (status, body) == (404, f"not-found:{_TOKEN}".encode())


@pytest.mark.parametrize(
    ("path", "query", "location"),
    [
        (f"/sub/{_TOKEN}/v2ray/", "", f"/sub/{_TOKEN}/v2ray"),
        (f"/sub/{_TOKEN}/info/", "", f"/sub/{_TOKEN}/info"),
        (f"/sub/{_TOKEN}/usage/", "start=1", f"/sub/{_TOKEN}/usage?start=1"),
    ],
)
def test_trailing_slash_redirects_to_known_route(sub, path, query, location):
    # раньше это делал redirect_slashes Starlette; catch-all его перехватывал,
    # и рабочая ссылка со слешем на конце получала 404
    status, headers, _ = _request(_app(sub), path, query)

    assert (status, headers[b"location"].decode()) == (307, location)
    assert sub.not_found_calls == []


@pytest.mark.parametrize("path", [f"/sub/{_TOKEN}/a/b/", f"/sub/{_TOKEN}/456465/"])
def test_trailing_slash_on_unknown_path_gets_not_found_page(sub, path):
    # редирект только туда, где есть что отдать; иначе клиент без поддержки
    # редиректов получил бы 307 вместо 404
    status, body = _get(_app(sub), path)

    assert (status, body) == (404, f"not-found:{_TOKEN}".encode())


@pytest.mark.parametrize("path", ["/sub//v2ray", "/sub//a/b"])
def test_empty_token_with_suffix_gets_not_found_page(sub, path):
    # токен потерялся в середине ссылки: под {token} пустой сегмент не подходит,
    # без отдельного маршрута FastAPI отдал бы голый JSON 404
    status, body = _get(_app(sub), path)

    assert (status, body) == (404, b"not-found:")


def test_catch_all_is_the_last_route(sub):
    # Маршрут, объявленный ниже /{token}/{rest:path}, стал бы недостижим
    assert sub.router.routes[-1].path.endswith("/{token}/{rest:path}")


def test_own_routes_do_not_take_subscription_path(sub):
    assert sub.subscription_path_taken(_app(sub).routes) is False


@pytest.mark.parametrize("suffix", ["", "/"])
def test_foreign_route_on_subscription_path_is_detected(sub, suffix):
    app = _app(sub)
    foreign = APIRouter()
    foreign.add_api_route(f"/{sub.XRAY_SUBSCRIPTION_PATH}{suffix}", lambda: {}, methods=["GET"])
    app.include_router(foreign)

    assert sub.subscription_path_taken(app.routes) is True
