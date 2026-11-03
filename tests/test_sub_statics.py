"""Статика страницы подписки (NPVPN-2315): тип шрифтов и версия в адресах `?v=`."""

from __future__ import annotations

import asyncio
import mimetypes
import pathlib
import re

import jinja2
import pytest
from fastapi.staticfiles import StaticFiles

import config as panel_config
from config import register_subscription_static_types, subscription_statics_version

_ROOT = pathlib.Path(__file__).parent.parent
_SUB_DIR = _ROOT / "app" / "templates" / "subscription"


@pytest.fixture
def mimetypes_without_woff2(monkeypatch):
    """Таблица типов без .woff2 — как в образе панели.

    Системный /etc/mime.types (на раннере CI) уже знает .woff2, а mimetypes перечитывает его
    при инициализации — поэтому строим таблицу без системных файлов. monkeypatch возвращает
    модульные таблицы после теста.
    """
    for name in ("types_map", "common_types", "suffix_map", "encodings_map", "inited", "_db"):
        monkeypatch.setattr(mimetypes, name, getattr(mimetypes, name))
    monkeypatch.setattr(mimetypes, "knownfiles", [])
    monkeypatch.setattr(mimetypes, "_db", None)
    mimetypes.init([])
    mimetypes.types_map.pop(".woff2", None)


def test_woff2_served_as_font(tmp_path, mimetypes_without_woff2):
    # без регистрации ушёл бы не font/woff2 (в образе панели — text/plain)
    assert mimetypes.guess_type("inter.woff2")[0] != "font/woff2"
    (tmp_path / "inter.woff2").write_bytes(b"wOF2")

    register_subscription_static_types()

    scope = {"type": "http", "method": "GET", "headers": []}
    response = asyncio.run(StaticFiles(directory=tmp_path).get_response("inter.woff2", scope))
    assert response.media_type == "font/woff2"


def _source(relative: str) -> str:
    return (_ROOT / relative).read_text(encoding="utf-8")


# app.templates и app.dashboard в тестах на Windows не импортируются (тянут всё приложение) —
# проводку проверяем по исходнику: без неё функции выше в проде не работают, а тесты зелёные
def test_templates_get_statics_version():
    assert 'env.globals["static_v"] = subscription_statics_version()' in _source("app/templates/__init__.py")


def test_statics_mount_registers_font_type():
    source = _source("app/dashboard/__init__.py")
    mount = source[source.index("def mount_sub_statics") :]
    body = mount.split("\ndef ", 1)[0]
    assert "register_subscription_static_types()" in body


@pytest.fixture
def sub_dir(tmp_path, monkeypatch):
    (tmp_path / "styles").mkdir()
    (tmp_path / "styles" / "components.css").write_text(".a { color: red; }")
    (tmp_path / "index.html").write_text("<html></html>")
    monkeypatch.setattr(panel_config, "resolved_subscription_templates_dir", lambda: tmp_path)
    return tmp_path


def test_version_is_stable_for_same_files(sub_dir):
    assert subscription_statics_version() == subscription_statics_version()
    assert re.fullmatch(r"[0-9a-f]{10}", subscription_statics_version())


def test_version_changes_with_static_files(sub_dir):
    before = subscription_statics_version()
    (sub_dir / "styles" / "components.css").write_text(".a { color: blue; }")
    assert subscription_statics_version() != before


def test_version_ignores_templates(sub_dir):
    # шаблоны отдаёт сервер, их правка кэш статики сбрасывать не должна
    before = subscription_statics_version()
    (sub_dir / "index.html").write_text("<html><body></body></html>")
    assert subscription_statics_version() == before


def test_unreadable_file_does_not_break_startup(sub_dir, monkeypatch):
    # нечитаемый файл в своей папке шаблонов — версия считается без него, панель запускается
    (sub_dir / "styles" / "locked.css").write_text("x")
    real_read = pathlib.Path.read_bytes

    def read_bytes(path):
        if path.name == "locked.css":
            raise PermissionError("denied")
        return real_read(path)

    monkeypatch.setattr(pathlib.Path, "read_bytes", read_bytes)
    assert re.fullmatch(r"[0-9a-f]{10}", subscription_statics_version())


def test_no_templates_dir_gives_empty_version(monkeypatch):
    monkeypatch.setattr(panel_config, "resolved_subscription_templates_dir", lambda: None)
    assert subscription_statics_version() == ""


def _render(template: str) -> str:
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(_SUB_DIR)), undefined=jinja2.ChainableUndefined)
    ctx = {
        "token": "TOKEN",
        "devices_json": "[]",
        "client_apps": {},
        "user": {},
        "devices": [],
        "sub_path": "sub",
        "web_url": "https://cab.example.com",
        "bot_url": "",
        "show_ads": True,
        "sub_statics": "/statics/subscription/",
        "support": {"mode": "telegram", "tg_url": "https://t.me/x", "token": "T"},
        "static_v": "abc123",
    }
    return env.get_template(template).render(ctx)


@pytest.mark.parametrize("template", ["index.html", "expired.html", "not_found.html"])
def test_styles_linked_separately_with_version(template):
    # index.css больше не тянет остальные через @import: у @import нет версии, и components.css
    # мог остаться старым из кэша
    html = _render(template)
    links = re.findall(r'<link rel="stylesheet" href="/statics/subscription/styles/([\w-]+\.css)\?v=abc123"', html)
    assert links[:4] == ["fonts.css", "variables.css", "components.css", "index.css"]
    assert "@import" not in (_SUB_DIR / "styles" / "index.css").read_text(encoding="utf-8")


def test_app_icons_exist():
    # иконки приложений подключаются из JS по имени — проверяем, что файлы на месте
    for name in ["happ.svg", "incy.svg", "v2ray.svg", "qr-logo.png"]:
        assert (_SUB_DIR / "assets" / name).is_file(), name


def test_scripts_and_images_have_version():
    html = _render("index.html")
    for path in [
        "scripts/cabinet-link.js",
        "scripts/status-poll.js",
        "assets/qr-logo.png",
        "assets/happ.svg",
        "assets/incy.svg",
        "assets/v2ray.svg",
    ]:
        assert f"{path}?v=abc123" in html, path


def test_font_preload_matches_css_url():
    # адрес предзагрузки совпадает с url() в fonts.css (без версии) — иначе шрифт качается дважды
    html = _render("index.html")
    assert 'href="/statics/subscription/fonts/inter-cyrillic.woff2" as="font"' in html
    assert "url('../fonts/inter-cyrillic.woff2')" in (_SUB_DIR / "styles" / "fonts.css").read_text(encoding="utf-8")
