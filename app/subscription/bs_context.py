"""БС-контекст подписки: какие хосты заблокированы по исчерпанному БС-лимиту.

Чистый модуль (без импортов БД/xray) — юнит-тестируется в песочнице tests/conftest.py,
как bs_limit / routing_profiles.

С NPVPN-2024 BsContext отвечает только за БС-лимит трафика (blocked_node_ids/stub_text).
Признак клиентского routing (какой профиль отдать хосту) больше не хранится здесь —
профиль лежит прямо на хосте (host["routing_profile_id"], кэш xray.hosts).

Признак блокировки хоста определяется ТОЛЬКО по привязанным нодам (host_nodes →
host["node_ids"]), а не по совпадению адреса хоста с Node.address: хост может быть задан
доменом (маскировка под свой домен в TLS/SNI), тогда как нода подключена по IP, и адреса
не совпадают (NPVPN-1652).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class StubEndpoint:
    """Адрес/порт мёртвой заглушки в подписке (зависит от формата/клиента)."""

    address: str
    port: int


ZERO_STUB = StubEndpoint(address="0.0.0.0", port=0)


@dataclass(frozen=True)
class BsContext:
    blocked_node_ids: frozenset[int]
    stub_text: str

    @classmethod
    def empty(cls) -> BsContext:
        """Контекст без БС-логики (revoked/expired-подписка)."""
        return cls(blocked_node_ids=frozenset(), stub_text="")

    @property
    def has_blocks(self) -> bool:
        return bool(self.blocked_node_ids)

    def is_blocked(self, host: Mapping) -> bool:
        """Юзер исчерпал БС-лимит на ноде этого хоста → хост станет заглушкой."""
        return self._matches(host, self.blocked_node_ids)

    @staticmethod
    def _matches(host: Mapping, node_ids: frozenset[int]) -> bool:
        if not node_ids:
            return False
        host_node_ids: Iterable[int] = host.get("node_ids") or ()
        return any(node_id in node_ids for node_id in host_node_ids)
