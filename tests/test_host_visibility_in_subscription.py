"""Фолбэк видимости на горячем пути подписки (NPVPN-2044).

Кэш хостов (app/xray/__init__.py) мог быть собран прежней версией процесса и
не содержать ключа visibility. Фолбэк обязан быть в сторону «не виден»:
пропавшая локация заметна и обратима, а лишняя уходит партнёру, который за
неё не платит, и обнаруживается только по счёту.
"""

from __future__ import annotations

from app.xray.host_addresses import host_allowed_for_bot


def _allowed(host: dict, viewer: str | None) -> bool:
    """Повторяет выражение из app/subscription/share.py:498 дословно."""
    return host_allowed_for_bot(host.get("visibility") or "restricted", host.get("bot_usernames") or [], viewer)


def test_cached_host_without_visibility_is_hidden():
    assert _allowed({"bot_usernames": []}, "AppleGurruBot") is False


def test_cached_host_without_visibility_but_bound_is_visible_to_its_bot():
    """Привязанный хост не должен пропасть из-за устаревшего кэша."""
    assert _allowed({"bot_usernames": ["AppleGurruBot"]}, "AppleGurruBot") is True


def test_cached_shared_host_is_visible_to_everyone():
    assert _allowed({"visibility": "shared", "bot_usernames": []}, "vpnZabBot") is True
