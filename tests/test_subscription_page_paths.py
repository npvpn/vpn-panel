"""Каталог страниц подписки из SUBSCRIPTION_PAGE_TEMPLATE и fallback CUSTOM."""

from __future__ import annotations

from pathlib import Path

from config import (
    SUBSCRIPTION_PAGE_FILENAME,
    resolved_custom_templates_directory,
    resolved_subscription_templates_dir,
    subscription_statics_url,
)

_ROOT = Path(__file__).parent.parent
_BUILTIN = _ROOT / "app" / "templates" / "subscription"


def test_index_filename_and_default_statics_url(monkeypatch):
    import config as panel_config

    monkeypatch.setattr(panel_config, "_SUBSCRIPTION_PAGE", Path("subscription/index.html"))
    assert SUBSCRIPTION_PAGE_FILENAME == "index.html"
    assert subscription_statics_url() == "/statics/subscription/"
    assert resolved_subscription_templates_dir() == _BUILTIN


def test_legacy_sub_env_finds_subscription_folder(monkeypatch):
    """Старый env SUBSCRIPTION_PAGE_TEMPLATE=sub/index.html после переноса в subscription/."""
    import config as panel_config

    monkeypatch.setattr(panel_config, "_SUBSCRIPTION_PAGE", Path("sub/index.html"))
    monkeypatch.setattr(panel_config, "CUSTOM_TEMPLATES_DIRECTORY", "/code/templates/")

    assert resolved_custom_templates_directory() is None
    resolved = resolved_subscription_templates_dir()
    assert resolved == _BUILTIN
    assert (resolved / "index.html").is_file()
    assert (resolved / "expired.html").is_file()
    assert (resolved / "not_found.html").is_file()
    assert subscription_statics_url() == "/statics/sub/"


def test_existing_custom_dir_wins(monkeypatch, tmp_path):
    import config as panel_config

    custom_dir = tmp_path / "subscription"
    custom_dir.mkdir()
    (custom_dir / "index.html").write_text("custom")
    monkeypatch.setattr(panel_config, "_SUBSCRIPTION_PAGE", Path("subscription/index.html"))
    monkeypatch.setattr(panel_config, "CUSTOM_TEMPLATES_DIRECTORY", str(tmp_path))

    assert resolved_custom_templates_directory() == str(tmp_path)
    assert resolved_subscription_templates_dir() == custom_dir
