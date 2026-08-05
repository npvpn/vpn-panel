"""Контекст 404-страницы подписки (NPVPN-1762).

`app/subscription/not_found.py` на уровне модуля тянет `app.db` (Session/crud) —
тяжёлую зависимость, недоступную в песочнице `tests/conftest.py` (см. её докстринг
про заглушку `app`). Поэтому стабим ровно `app.db` через monkeypatch и грузим
модуль напрямую через importlib, как это делает tests/test_settings_apps_managed_gate.py.

monkeypatch (а не голое присвоение в sys.modules) — чтобы не перетереть заглушки
других тестов: при полном прогоне `pytest -q` файлы делят один процесс и один
sys.modules.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import types
from types import SimpleNamespace

import pytest

_ROOT = pathlib.Path(__file__).parent.parent


def _bot(*, web_url: str = "", bot_url: str = "", show_ads: bool = True):
    """Бот с настройками, как их отдаёт BotSettings.data."""
    return SimpleNamespace(
        settings=SimpleNamespace(data={"web_url": web_url, "bot_url": bot_url, "show_ads": show_ads})
    )


def _user(bot):
    return SimpleNamespace(bot=bot)


@pytest.fixture
def not_found(monkeypatch):
    db_module = sys.modules.get("app.db")
    if db_module is None:
        db_module = types.ModuleType("app.db")
        monkeypatch.setitem(sys.modules, "app.db", db_module)
    if not hasattr(db_module, "Session"):
        monkeypatch.setattr(db_module, "Session", object, raising=False)

    crud_module = getattr(db_module, "crud", None)
    if crud_module is None:
        crud_module = types.SimpleNamespace()
        monkeypatch.setattr(db_module, "crud", crud_module, raising=False)
    if not hasattr(crud_module, "get_user"):
        monkeypatch.setattr(crud_module, "get_user", lambda db, username: None, raising=False)
    if not hasattr(crud_module, "get_bots"):
        monkeypatch.setattr(crud_module, "get_bots", lambda db: [], raising=False)

    spec = importlib.util.spec_from_file_location(
        "app.subscription.not_found", _ROOT / "app" / "subscription" / "not_found.py"
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "app.subscription.not_found", module)
    spec.loader.exec_module(module)
    # Токен не подделываем: подпись проверяет реальный get_subscription_payload,
    # а нас интересует ветвление после успешного разбора.
    monkeypatch.setattr(module, "get_subscription_payload", lambda token: {"username": "42_7"})
    return module


def test_home_url_prefers_web_url(not_found, monkeypatch):
    bot = _bot(web_url="https://cab.example", bot_url="https://t.me/bot")
    monkeypatch.setattr(not_found.crud, "get_user", lambda db, username: _user(bot))

    ctx = not_found.build_not_found_page_context(db=object(), token="whatever-long-token")

    assert ctx["home_url"] == "https://cab.example"


def test_home_url_falls_back_to_bot_url(not_found, monkeypatch):
    bot = _bot(web_url="", bot_url="https://t.me/bot")
    monkeypatch.setattr(not_found.crud, "get_user", lambda db, username: _user(bot))

    ctx = not_found.build_not_found_page_context(db=object(), token="whatever-long-token")

    assert ctx["home_url"] == "https://t.me/bot"


def test_home_url_empty_when_bot_has_no_links(not_found, monkeypatch):
    bot = _bot(web_url="", bot_url="")
    monkeypatch.setattr(not_found.crud, "get_user", lambda db, username: _user(bot))

    ctx = not_found.build_not_found_page_context(db=object(), token="whatever-long-token")

    assert ctx["home_url"] == ""


def test_single_bot_used_when_user_not_found(not_found, monkeypatch):
    monkeypatch.setattr(not_found.crud, "get_user", lambda db, username: None)
    monkeypatch.setattr(not_found.crud, "get_bots", lambda db: [_bot(web_url="https://only.example")])

    ctx = not_found.build_not_found_page_context(db=object(), token="whatever-long-token")

    assert ctx["home_url"] == "https://only.example"


def test_multi_bot_gives_no_link(not_found, monkeypatch):
    monkeypatch.setattr(not_found.crud, "get_user", lambda db, username: None)
    monkeypatch.setattr(
        not_found.crud,
        "get_bots",
        lambda db: [_bot(web_url="https://one.example"), _bot(web_url="https://two.example")],
    )
    # apply_bot_settings_fallback(None) подставил бы env BOT_URL — застабленное
    # значение узнаваемо не-пустое, чтобы тест реально ловил регресс на этот вызов,
    # а не полагался на то, что DEFAULT_BOT_SETTINGS["bot_url"] в тестовой среде пуст.
    monkeypatch.setattr(
        not_found, "apply_bot_settings_fallback", lambda raw: {"web_url": "", "bot_url": "https://t.me/env-default"}
    )

    ctx = not_found.build_not_found_page_context(db=object(), token="whatever-long-token")

    # Ни чужой бот, ни env-дефолт: на мультиботовой панели угадывать нечего.
    assert ctx["home_url"] == ""


def test_user_found_without_own_bot_gives_no_link(not_found, monkeypatch):
    """Мультиботовая панель, у найденного пользователя bot is None (бот удалён) —
    ступень 1 не должна подставлять чужого/env-бота, а провалиться на ступень 3."""
    monkeypatch.setattr(not_found.crud, "get_user", lambda db, username: _user(bot=None))
    monkeypatch.setattr(
        not_found.crud,
        "get_bots",
        lambda db: [_bot(web_url="https://one.example"), _bot(web_url="https://two.example")],
    )
    monkeypatch.setattr(
        not_found, "apply_bot_settings_fallback", lambda raw: {"web_url": "", "bot_url": "https://t.me/env-default"}
    )

    ctx = not_found.build_not_found_page_context(db=object(), token="whatever-long-token")

    assert ctx["home_url"] == ""


def test_no_bots_uses_env_defaults(not_found, monkeypatch):
    monkeypatch.setattr(not_found.crud, "get_user", lambda db, username: None)
    monkeypatch.setattr(not_found.crud, "get_bots", lambda db: [])
    received_raw = []

    def _fallback(raw):
        received_raw.append(raw)
        return {"web_url": "", "bot_url": "https://t.me/env"}

    monkeypatch.setattr(not_found, "apply_bot_settings_fallback", _fallback)

    ctx = not_found.build_not_found_page_context(db=object(), token="whatever-long-token")

    # Ноль ботов в панели -> raw должен быть None: это и есть «взяли env-дефолты»,
    # а не просто проброс произвольного значения через стаб.
    assert received_raw == [None]
    assert ctx["home_url"] == "https://t.me/env"


def test_unsafe_url_scheme_gives_no_link(not_found, monkeypatch):
    bot = _bot(web_url="", bot_url="javascript:alert(1)")
    monkeypatch.setattr(not_found.crud, "get_user", lambda db, username: _user(bot))

    ctx = not_found.build_not_found_page_context(db=object(), token="whatever-long-token")

    assert ctx["home_url"] == ""


def test_show_ads_taken_from_bot_settings(not_found, monkeypatch):
    bot = _bot(web_url="https://cab.example", show_ads=False)
    monkeypatch.setattr(not_found.crud, "get_user", lambda db, username: _user(bot))

    ctx = not_found.build_not_found_page_context(db=object(), token="whatever-long-token")

    assert ctx["show_ads"] is False


def test_db_error_does_not_break_page(not_found, monkeypatch):
    def _boom(db, username):
        raise RuntimeError("db is down")

    monkeypatch.setattr(not_found.crud, "get_user", _boom)

    ctx = not_found.build_not_found_page_context(db=object(), token="whatever-long-token")

    assert ctx == {"home_url": "", "show_ads": True}


def test_unparsable_token_skips_user_lookup(not_found, monkeypatch):
    monkeypatch.setattr(not_found, "get_subscription_payload", lambda token: None)

    def _must_not_be_called(db, username):
        raise AssertionError("get_user не должен вызываться при неразобранном токене")

    monkeypatch.setattr(not_found.crud, "get_user", _must_not_be_called)
    monkeypatch.setattr(not_found.crud, "get_bots", lambda db: [_bot(bot_url="https://t.me/only")])

    ctx = not_found.build_not_found_page_context(db=object(), token="garbage")

    assert ctx["home_url"] == "https://t.me/only"


def _request(accept: str):
    """Минимальная замена fastapi.Request: нужен только заголовок Accept."""
    return SimpleNamespace(headers={"Accept": accept})


def test_api_client_gets_empty_404(not_found, monkeypatch):
    def _must_not_render(name, context=None):
        raise AssertionError("шаблон не должен рендериться для не-HTML клиента")

    monkeypatch.setattr(not_found, "render_template", _must_not_render)

    response = not_found.render_not_found(_request("*/*"), db=object(), token="whatever-long-token")

    assert response.status_code == 404
    assert response.body == b""


def test_browser_gets_html_404(not_found, monkeypatch):
    monkeypatch.setattr(not_found.crud, "get_user", lambda db, username: _user(_bot(web_url="https://cab.example")))
    monkeypatch.setattr(not_found, "render_template", lambda name, context: f"<html>{context['home_url']}</html>")

    response = not_found.render_not_found(
        _request("text/html,application/xhtml+xml"), db=object(), token="whatever-long-token"
    )

    assert response.status_code == 404
    assert b"https://cab.example" in response.body


def _render_real_template(context: dict) -> str:
    """Рендер боевого templates/sub/not_found.html через тот же jinja-env, что и панель."""
    import jinja2

    env = jinja2.Environment(loader=jinja2.FileSystemLoader([str(_ROOT / "templates"), str(_ROOT / "app/templates")]))
    return env.get_template("sub/not_found.html").render(context)


def test_template_renders_link_when_home_url_set():
    html = _render_real_template({"home_url": "https://cab.example", "show_ads": True})

    assert '<a href="https://cab.example"' in html
    assert "<button" not in html


def test_template_hides_button_without_home_url():
    html = _render_real_template({"home_url": "", "show_ads": True})

    assert "light-btn" not in html


def test_template_footer_respects_show_ads():
    assert "npvpn" not in _render_real_template({"home_url": "", "show_ads": False})
    assert "npvpn" in _render_real_template({"home_url": "", "show_ads": True})
