"""Какие локации подписки закрыты временной блокировкой торрента.

Чистый модуль, без БД. Хост затронут, если среди его нод есть хотя бы одна
из активной блокировки. Сборный профиль решает это отдельно: достаточно
одной затронутой ноды у получателя или у любого источника инжекта.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class TorrentContext:
    blocked_node_ids: frozenset[int]
    stub_text: str

    @classmethod
    def empty(cls) -> TorrentContext:
        return cls(blocked_node_ids=frozenset(), stub_text="")

    @property
    def has_blocks(self) -> bool:
        return bool(self.blocked_node_ids)

    def affects(self, host: Mapping) -> bool:
        if not self.blocked_node_ids:
            return False
        host_node_ids: Iterable[int] = host.get("node_ids") or ()
        return any(node_id in self.blocked_node_ids for node_id in host_node_ids)
