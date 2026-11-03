"""Статика страницы подписки (NPVPN-2315): тип шрифтов и версия в адресах `?v=`."""

from __future__ import annotations

import asyncio
import pathlib
import re

import jinja2
import pytest
from fastapi.staticfiles import StaticFiles

import config as panel_config
from config import register_subscription_static_types, subscription_statics_version

_SUB_DIR = pathlib.Path(__file__).parent.parent / "app" / "templates" / "subscription"


def test_woff2_served_as_font(tmp_path):
    (tmp_path / "inter.woff2").write_bytes(b"wOF2")
    register_subscription_static_types()

    scope = {"type": "http", "method": "GET", "headers": []}
    response = asyncio.run(StaticFiles(directory=tmp_path).get_response("inter.woff2", scope))

    assert response.media_type == "font/woff2"


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
