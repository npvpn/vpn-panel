"""Какие адреса хоста достанутся конкретному юзеру (NPVPN-2072).

Чистый модуль (без импортов БД/xray) — как bs_context. Сборка из БД живёт в
address_context_builder.py.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from statistics import median
from typing import cast

from app.xray.address_policy import epoch_for, epoch_start_day, is_exhausted, pick_keys


@dataclass(frozen=True)
class HostSubsetSettings:
    """Настройки сужения КОНКРЕТНОГО хоста (`hosts.address_subset_*`).

    Живут на хосте, а не на боте: у локаций разное число нод и разная ценность —
    на одном хосте юзеру осмысленно отдать два адреса, на другом три. Период ротации
    тоже пер-хостовый, поэтому эпоха и снимок весов считаются здесь, а не один раз
    на юзера.
    """

    enabled: bool = False
    size: int = 0
    rotation_days: int = 1

    @property
    def narrows(self) -> bool:
        return self.enabled and self.size > 0


DISABLED_SETTINGS = HostSubsetSettings()

# Период ротации по умолчанию, если у включённого хоста он не задан. Двое суток —
# компромисс из постановки NPVPN-2072: достаточно редко, чтобы саппорт понимал, на каких
# нодах юзер сидел при обращении, и достаточно часто, чтобы расход выравнивался.
DEFAULT_ROTATION_DAYS = 2


def settings_from_host(host: Mapping) -> HostSubsetSettings:
    """Настройки сужения из записи кэша xray.hosts (см. app/xray/__init__.py)."""
    if not host.get("address_subset_enabled"):
        return DISABLED_SETTINGS
    size = int(host.get("address_subset_size") or 0)
    if size <= 0:
        # Размер не задан — сужать не по чему. Это не «выдать один адрес»: молча
        # превратить незаполненное поле в жёсткое ограничение до одной ноды нельзя.
        return DISABLED_SETTINGS
    return HostSubsetSettings(
        enabled=True,
        size=size,
        rotation_days=max(1, int(host.get("address_rotation_days") or DEFAULT_ROTATION_DAYS)),
    )


def collect_rotation_periods(host_lists) -> set[int]:
    """Периоды ротации всех хостов, где сужение включено.

    Нужны сборщику контекста: снимок весов берётся на начало эпохи КАЖДОГО периода.
    Считается по всему кэшу хостов, без фильтра по боту и инбаундам юзера — фильтр дал бы
    в лучшем случае на один снимок меньше, а знание о видимости хостов пришлось бы тащить
    в сборку контекста.
    """
    return {
        settings.rotation_days
        for hosts in host_lists
        for host in hosts
        if (settings := settings_from_host(host)).narrows
    }


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


def choose_nodes(
    user_id: int,
    node_ids: Sequence[int],
    *,
    weights: Mapping[int, float],
    exhausted: Collection[int],
    size: int,
    epoch: int,
) -> set[int]:
    """Какие ноды хоста достанутся юзеру: сперва порог, потом взвешивание.

    Исчерпанные вычитаются ДО взвешивания, а не получают малый вес: порог — стоп-кран, а
    не предпочтение. Но если исчерпан ВЕСЬ хост, возвращаются все его ноды: инвариант
    «подписка никогда не остаётся без адресов» жёстче экономии трафика — ошибка в лимитах
    не должна гасить локацию целиком.

    Единственное место, где живёт эта формула: её же вызывает журнал выдачи
    (app/services/address_history.py), и разъехавшись, они показывали бы саппорту не то,
    что юзер получил на самом деле.
    """
    alive = [node_id for node_id in node_ids if node_id not in exhausted]
    if not alive:
        alive = list(node_ids)
    if len(alive) <= size:
        return set(alive)
    candidates = list(weighted_candidates(weights, alive).items())
    # pick_keys работает с произвольными Hashable (у легаси-хостов ключ — сам адрес),
    # здесь же ключи заведомо node_id.
    return {cast(int, key) for key in pick_keys(user_id, candidates, size, epoch)}


def exhausted_from_snapshot(
    weights: Mapping[int, float],
    limits: Mapping[int, int],
    cutoff_percent: int,
) -> set[int]:
    """Ноды, исчерпанные НА МОМЕНТ снимка весов (для журнала выдачи).

    Живая выдача смотрит свежие `nodes.hosting_used_bytes`, но истории расхода мы не
    храним — за прошедшие сутки судить можно только по снимку: вес это остаток лимита,
    значит «исчерпана» равносильно «остатка меньше, чем (1 - порог) лимита». Лимит берётся
    текущий — то же допущение, которое журнал уже делает для настроек хоста.

    Точность здесь суточная: ноду, перешагнувшую порог в середине суток, журнал покажет по
    состоянию снимка.

    Расход восстанавливается как `лимит - остаток` и проверяется тем же предикатом, что и
    живая выдача. Сравнивать «остаток ≤ лимит × (1 - порог)» напрямую нельзя: 1000×(1−0.9)
    в double даёт 99.99999999999997, и нода с остатком ровно 100 при пороге 90% молча
    оставалась бы в выдаче.
    """
    return {
        node_id
        for node_id, weight in weights.items()
        if node_id in limits
        and is_exhausted(used=limits[node_id] - weight, limit=limits[node_id], cutoff_percent=cutoff_percent)
    }


@dataclass(frozen=True)
class AddressContext:
    """Пер-юзерная часть выбора: эпоха считается отсюда, настройки приходят с хоста.

    `weights_by_day` — снимки весов, разложенные по суткам начала эпохи: у хостов с
    разными периодами ротации эпохи начинаются в разные дни, поэтому снимок не один.

    `exhausted` — ноды, выбывшие по порогу `HOSTING_USAGE_CUTOFF_PERCENT`. Считается по
    СВЕЖИМ `nodes.hosting_used_bytes` (обновляются раз в минуту), а не по суточному
    снимку: порог существует ровно для того, чтобы не дать хостеру выставить счёт, и
    запаздывание на сутки лишило бы его смысла.
    """

    user_id: int
    day_index: int = 0
    offset: int = 0
    weights_by_day: Mapping[int, Mapping[int, float]] = field(default_factory=dict)
    exhausted: frozenset[int] = frozenset()
    enabled: bool = False
    pins: Mapping[int, Sequence[int]] = field(default_factory=dict)

    @classmethod
    def disabled(cls) -> AddressContext:
        """Контекст без сужения (revoked/expired-подписка)."""
        return cls(user_id=0, enabled=False)

    def _weights(self, settings: HostSubsetSettings) -> Mapping[int, float]:
        """Снимок на начало ЭТОЙ эпохи: внутри эпохи вес обязан быть постоянным."""
        day = epoch_start_day(self.user_id, self.day_index, settings.rotation_days)
        return self.weights_by_day.get(day, {})

    def pick(
        self,
        addresses: Sequence[str],
        node_ids: Sequence[int],
        *,
        addresses_from_nodes: bool,
        host_id: int | None = None,
        settings: HostSubsetSettings = DISABLED_SETTINGS,
    ) -> list[str]:
        """Подмножество адресов хоста. Порядок исходного списка сохраняется.

        `addresses_from_nodes` обязан прийти снаружи (из того же места, что и
        node_ids — см. host["addresses_from_nodes"] в app/xray/__init__.py), а не
        выводиться из совпадения длин `addresses`/`node_ids`: у легаси-хоста со
        статическим host.address адреса заданы строкой, а нод за ним может стоять
        сколько угодно — длины могут случайно совпасть, но соответствие «адрес ↔
        нода» при этом отсутствует, и взвешивание по чужим нодам было бы шумом.

        Закрепление (`pins`) заменяет автовыбор целиком для своего хоста, но
        применяется как ПЕРЕСЕЧЕНИЕ с фактическими node_ids хоста, а не как
        буквальный приказ: закреплённую ноду могли отвязать от хоста или удалить,
        и слепое исполнение пина оставило бы юзера без адресов вовсе — а этот
        инвариант жёстче любого закрепления. Пустое пересечение равносильно
        отсутствию пина (обычный автовыбор). Для легаси-хоста со статическим
        адресом (addresses_from_nodes=False) закреплять нечего — соответствия
        «адрес ↔ нода» там нет по построению.

        Пин СИЛЬНЕЕ порога исчерпания: закрепление — явное действие саппорта, с
        автором и сроком годности, и автоматика его не отменяет.
        """
        if addresses_from_nodes and host_id is not None and host_id in self.pins:
            pinned = set(self.pins[host_id]) & set(node_ids)
            if pinned:
                return [addr for addr, node_id in zip(addresses, node_ids) if node_id in pinned]

        if not self.enabled or not settings.narrows:
            return list(addresses)

        if addresses_from_nodes and node_ids:
            return self._pick_by_nodes(addresses, node_ids, settings)

        if len(addresses) <= settings.size:
            return list(addresses)
        by_address = [(addr, 0.0) for addr in addresses]
        epoch = epoch_for(self.user_id, self.day_index, settings.rotation_days, self.offset)
        chosen_addresses = set(pick_keys(self.user_id, by_address, settings.size, epoch))
        return [addr for addr in addresses if addr in chosen_addresses]

    def _pick_by_nodes(
        self,
        addresses: Sequence[str],
        node_ids: Sequence[int],
        settings: HostSubsetSettings,
    ) -> list[str]:
        """Выбор по нодам — вся формула в choose_nodes, общая с журналом выдачи."""
        chosen = choose_nodes(
            self.user_id,
            node_ids,
            weights=self._weights(settings),
            exhausted=self.exhausted,
            size=settings.size,
            epoch=epoch_for(self.user_id, self.day_index, settings.rotation_days, self.offset),
        )
        return [addr for addr, node_id in zip(addresses, node_ids) if node_id in chosen]
