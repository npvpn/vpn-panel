"""Предикат доступности хоста боту (NPVPN-2044).

Модуль листовой (без pydantic/crud/БД), поэтому тест не нуждается в обходе
стабов conftest: app.xray.host_addresses импортирует только app.models.node.
"""

from __future__ import annotations

import pytest

from app.xray.host_addresses import host_allowed_for_bot

SHARED = "shared"
RESTRICTED = "restricted"


@pytest.mark.parametrize(
    ("visibility", "bot_usernames", "viewer", "expected"),
    [
        (SHARED, [], "AppleGurruBot", True),
        (SHARED, [], None, True),
        (RESTRICTED, ["AppleGurruBot"], "AppleGurruBot", True),
        (RESTRICTED, ["AppleGurruBot"], "vpnZabBot", False),
        # Ровно то поведение, которого раньше не было: пустая привязка больше не
        # означает «всем», иначе выбор хостов партнёром не значил бы ничего.
        (RESTRICTED, [], "AppleGurruBot", False),
        (RESTRICTED, [], None, False),
        # Review Focus 2: бот удалён из панели, его имени нет в привязке —
        # хост не должен стать видимым от того, что бот исчез.
        (RESTRICTED, ["AppleGurruBot"], None, False),
        # Review Focus 1: противоречивое состояние достижимо вручную;
        # shared старше привязки, иначе «виден всем» переставало бы работать
        # от добавления одного бота.
        (SHARED, ["AppleGurruBot"], "vpnZabBot", True),
    ],
)
def test_host_allowed_for_bot(visibility, bot_usernames, viewer, expected):
    assert host_allowed_for_bot(visibility, bot_usernames, viewer) is expected
