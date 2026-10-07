"""Предикат доступности хоста боту (NPVPN-2044).

Модуль листовой (без pydantic/crud/БД), поэтому тест не нуждается в обходе
стабов conftest: app.xray.host_addresses импортирует только app.models.node.
"""

from __future__ import annotations

import pytest

from app.xray.host_addresses import host_allowed_for_bot


@pytest.mark.parametrize(
    ("bot_usernames", "viewer", "expected"),
    [
        (["AppleGurruBot"], "AppleGurruBot", True),
        (["AppleGurruBot", "vpnZabBot"], "vpnZabBot", True),
        (["AppleGurruBot"], "vpnZabBot", False),
        # Пустая привязка больше не значит «всем»: это «никому».
        ([], "AppleGurruBot", False),
        ([], None, False),
        # Бот юзера неизвестен (users.bot_id IS NULL) — хост не отдаётся.
        # Прежний предикат отдавал ему ВСЕ хосты, включая платные персональные.
        (["AppleGurruBot"], None, False),
    ],
)
def test_host_allowed_for_bot(bot_usernames, viewer, expected):
    assert host_allowed_for_bot(bot_usernames, viewer) is expected
