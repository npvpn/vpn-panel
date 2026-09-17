"""Какие адреса хоста достанутся конкретному юзеру (NPVPN-2072).

Чистый модуль (без импортов БД/xray) — как bs_context. Сборка из БД живёт в
address_context_builder.py.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from statistics import median

from app.xray.address_policy import pick_keys


def weighted_candidates(weights: Mapping[int, float], node_ids: Sequence[int]) -> dict[int, float]:
    """Веса нод этого хоста; неизвестные получают медиану известных, а не ноль.

    Лимит задан не у всех нод. Нулевой вес означал бы, что нода практически исчезает
    из выдачи, то есть заполнение поля «лимит» превратилось бы в рычаг видимости.
    Если не известен вес ни одной ноды хоста, медианы не существует — возвращаем нули,
    и выбор вырождается в невзвешенный, что корректно: данных для взвешивания нет.
    """
    known = [weights[node_id] for node_id in node_ids if node_id in weights]
    if not known:
        return dict.fromkeys(node_ids, 0.0)
    fallback = float(median(known))
    return {node_id: weights.get(node_id, fallback) for node_id in node_ids}


@dataclass(frozen=True)
class AddressContext:
    user_id: int
    size: int
    epoch: int
    weights: Mapping[int, float]
    enabled: bool

    @classmethod
    def disabled(cls) -> AddressContext:
        """Контекст без сужения (флаг выключен, revoked/expired-подписка)."""
        return cls(user_id=0, size=0, epoch=0, weights={}, enabled=False)

    def pick(self, addresses: Sequence[str], node_ids: Sequence[int], *, addresses_from_nodes: bool) -> list[str]:
        """Подмножество адресов хоста. Порядок исходного списка сохраняется.

        `addresses_from_nodes` обязан прийти снаружи (из того же места, что и
        node_ids — см. host["addresses_from_nodes"] в app/xray/__init__.py), а не
        выводиться из совпадения длин `addresses`/`node_ids`: у легаси-хоста со
        статическим host.address адреса заданы строкой, а нод за ним может стоять
        сколько угодно — длины могут случайно совпасть, но соответствие «адрес ↔
        нода» при этом отсутствует, и взвешивание по чужим нодам было бы шумом.
        """
        if not self.enabled or self.size <= 0 or len(addresses) <= self.size:
            return list(addresses)

        if addresses_from_nodes and node_ids:
            candidates = list(weighted_candidates(self.weights, node_ids).items())
            chosen = set(pick_keys(self.user_id, candidates, self.size, self.epoch))
            return [addr for addr, node_id in zip(addresses, node_ids) if node_id in chosen]

        by_address = [(addr, 0.0) for addr in addresses]
        chosen_addresses = set(pick_keys(self.user_id, by_address, self.size, self.epoch))
        return [addr for addr in addresses if addr in chosen_addresses]
