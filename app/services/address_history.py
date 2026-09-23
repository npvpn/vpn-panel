"""Восстановление выдачи адресов задним числом — журнал для саппорта (NPVPN-2072).

Смысловое ядро фичи сужения адресов: ради этого и собираются суточные снимки
состава хостов (HostCompositionSnapshot) и весов нод (NodeWeightSnapshot).

Главный принцип: честность важнее полноты. Саппорт примет любой показанный
ответ за факт. Поэтому если по хосту за дату нет данных для однозначного
восстановления — источник "unknown" и restorable=False, а не пустой список
(который прочитают как "адресов не было") и не правдоподобная догадка по
чужим/неполным данным.

Историческая оговорка: настройки сужения (`hosts.address_subset_*`, NPVPN-2072)
берутся СЕГОДНЯШНИМИ — панель не хранит, каким был размер подмножества или период
ротации хоста в прошлом. Реконструкция предполагает, что их не меняли; если меняли,
auto-часть истории за периоды до смены может быть неточной. То же и с порогом
исчерпания: свежего расхода за прошедшие сутки нет, исчерпание выводится из снимка
весов, поэтому его точность суточная (см. exhausted_from_snapshot). Это ограничения
источника данных, а не что-то, что можно обойти в этом модуле.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, cast

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import crud
from app.db.models import ProxyHost, User, UserNodePin
from app.subscription.address_context import (
    choose_nodes,
    exhausted_from_snapshot,
    settings_from_host,
)
from app.subscription.address_context_builder import _EPOCH_ORIGIN
from app.xray.address_policy import (
    ARCHIVE_RETENTION_DAYS,
    WEIGHT_SNAPSHOT_MAX_AGE_DAYS,
    epoch_for,
    epoch_start_day,
    pick_keys,
)
from app.xray.host_addresses import host_allowed_for_bot, visible_nodes
from config import HOSTING_USAGE_CUTOFF_PERCENT

AssignmentSource = Literal["pin", "auto", "unknown"]


class HostAssignment(BaseModel):
    """Что юзер получил по одному хосту в один день (NPVPN-2072).

    `restorable=False` — явный признак "не восстановимо": данных за эти сутки
    не хватает, `node_ids`/`addresses` в этом случае пустые и НЕ означают
    "адресов не было", а означают "неизвестно, какие были".
    """

    host_id: int
    remark: str
    source: AssignmentSource
    restorable: bool
    node_ids: list[int] = Field(default_factory=list)
    addresses: list[str] = Field(default_factory=list)


class DayAssignments(BaseModel):
    """Один день истории: `day_index` + человекочитаемая дата + все хосты."""

    day_index: int
    date: str
    hosts: list[HostAssignment]


# Архивный горизонт закреплений: тот же источник, что у снимков состава/весов
# (prune_host_composition_snapshots, NodeWeightSnapshot) — app/xray/address_policy.py
# (M4, единая константа, не копия числа). Пин с TTL дальше этого горизонта пережил
# бы собственную историю — стал бы необъяснимым, когда журнал за его срок уже
# вычищен.
MAX_PIN_TTL_DAYS = ARCHIVE_RETENTION_DAYS


class PinCreate(BaseModel):
    """Тело POST /user/{username}/pins. `created_by` намеренно не поле тела —
    берётся из аутентифицированного админа на стороне роутера, иначе автора
    действия можно подделать одной строкой в запросе."""

    host_id: int
    node_ids: list[int] = Field(min_length=1)
    ttl_days: int = Field(gt=0, le=MAX_PIN_TTL_DAYS)
    note: str | None = Field(default=None, max_length=500)


class PinResponse(BaseModel):
    host_id: int
    node_ids: list[int]
    created_at: datetime
    expires_at: datetime
    created_by: str
    note: str | None = None


class PinnableNode(BaseModel):
    node_id: int
    name: str


class PinnableHost(BaseModel):
    """Локация, которую можно закрепить этому юзеру (NPVPN-2072): полный
    состав нод, а не только уже выбранное подмножество — форма закрепления
    должна предлагать выбор из ВСЕХ нод хоста, а не из того, что видно в
    истории за какие-то конкретные сутки."""

    host_id: int
    remark: str
    nodes: list[PinnableNode]


def _visible_inbound_tags(dbuser: User) -> set[str]:
    """Теги инбаундов, реально видимых этому юзеру — тот же источник, что и
    рендер подписки (`User.inbounds`, `app/db/models.py`).

    Свойство `User.inbounds` уже учитывает ОБА условия, которыми живая выдача
    режет набор хостов (C2, NPVPN-2072): у юзера вообще есть прокси нужного
    протокола (`self.proxies`) и тег не входит в `excluded_inbounds` этого
    прокси. Не пересчитываем эту логику заново (I4-урок фичи) — только читаем
    её результат и разворачиваем по протоколам в плоское множество тегов,
    потому что `ProxyHost.inbound_tag` не хранит протокол сам по себе."""
    tags: set[str] = set()
    for proxy_tags in (dbuser.inbounds or {}).values():
        tags.update(proxy_tags)
    return tags


def list_pinnable_hosts(db: Session, dbuser: User) -> list[PinnableHost]:
    """Локации, которые реально мог получить этот юзер, с полным составом нод —
    источник данных для формы создания закрепления (`POST /user/{username}/pins`).

    ТРИ фильтра, все обязательны — те же условия «доступна ли эта локация
    этому юзеру», что в `reconstruct` (см. его докстринг) и в рендере
    подписки, а не переизобретённая здесь копия (I4-урок фичи, финальное
    ревью):
    1. Хост привязан к боту юзера (или ни к какому конкретному боту,
       `host_allowed_for_bot`) — иначе саппорт увидел бы и мог бы закрепить
       локацию ЧУЖОГО бота, которая этому юзеру никогда не достанется.
    2. Тег инбаунда хоста входит в эффективные инбаунды юзера
       (`_visible_inbound_tags`, тот же источник, что и в `reconstruct`) —
       без него форма предложила бы локацию, которой у юзера нет ни в проксях
       нужного протокола, ни за вычетом `excluded_inbounds`. Саппорт создал бы
       пин, получил 200, увидел его во вкладке «Закрепления» как действующий
       — а в подписке этой локации нет вовсе, пин не применится никогда. Тот
       же по сути дефект, что чинили по I2 для disabled-нод, только уровнем
       выше: там отсекалась одна нода, здесь — целая локация.
    3. У хоста нет статического `address` (`not host.address` — пустая строка
       у "адресного" хоста означает "адреса берутся из нод", см.
       `app/xray/__init__.py: addresses_from_nodes`). У легаси-хостов со
       статическим адресом соответствия "адрес ↔ нода" нет по построению —
       `POST /pins` и так отклонит такой host_id 400-й, показывать его в
       форме, которая заведомо будет отклонена, незачем.

    Список нод локации — `visible_nodes(host)` (app/xray/host_addresses.py), а
    не `host.nodes` целиком: disabled-нода не участвует в живой выдаче (см.
    I2), предлагать её в форме закрепления означало бы дать саппорту создать
    пин, который тут же молча не сработает.
    """
    user_bot_username = dbuser.bot_username
    visible_tags = _visible_inbound_tags(dbuser)
    hosts = db.query(ProxyHost).filter(ProxyHost.address == "").order_by(ProxyHost.id).all()
    return [
        PinnableHost(
            host_id=cast(int, host.id),
            remark=cast(str, host.remark),
            nodes=[PinnableNode(node_id=cast(int, node.id), name=cast(str, node.name)) for node in visible_nodes(host)],
        )
        for host in hosts
        if host_allowed_for_bot(host.bot_usernames, user_bot_username) and host.inbound_tag in visible_tags
    ]


@dataclass
class _HistoryScope:
    """День-независимые данные журнала, прочитанные один раз на весь диапазон.

    Журнал строится сразу за десятки суток (до ARCHIVE_RETENTION_DAYS). Поденное чтение
    юзера, хостов, пинов, снимков и лимитов означало бы сотни последовательных запросов
    в синхронном обработчике — при 90 днях больше четырёхсот. Здесь всё это читается
    пачкой, а раскладку по конкретным суткам делает `_reconstruct_day` в памяти.
    """

    user_id: int
    offset: int
    rotation_at: datetime | None
    hosts: list[ProxyHost]
    composition: dict[int, dict[int, list[dict]]]
    pins: list[UserNodePin]
    snapshots: dict[int, dict[int, float]]
    node_limits: dict[int, int]

    def pins_on_day(self, day_start: datetime, day_end: datetime) -> dict[int, list[int]]:
        """Закрепления, действовавшие в эти сутки. Правило то же, что в crud.get_pins_covering_day:
        пин создан до конца суток и не истёк до их начала; при нескольких строках на хост
        выигрывает самая свежая (строки уже отсортированы по created_at/id)."""
        result: dict[int, list[int]] = {}
        for pin in self.pins:
            if pin.created_at < day_end.replace(tzinfo=None) and pin.expires_at > day_start.replace(tzinfo=None):
                result[cast(int, pin.host_id)] = list(cast(list[int], pin.node_ids))
        return result

    def weights_for(self, day_index: int, period_days: int) -> dict[int, float]:
        """Снимок весов на начало эпохи этого хоста в эти сутки.

        Повторяет правило crud.get_weight_snapshot: берётся ближайший снимок не позже
        нужных суток, и он отбрасывается, если отстал больше чем на
        WEIGHT_SNAPSHOT_MAX_AGE_DAYS — иначе журнал показал бы распределение по весам,
        которых живая выдача в тот день уже не использовала.
        """
        snapshot_day = epoch_start_day(self.user_id, day_index, period_days)
        available = [day for day in self.snapshots if day <= snapshot_day]
        if not available:
            return {}
        latest = max(available)
        if snapshot_day - latest > WEIGHT_SNAPSHOT_MAX_AGE_DAYS:
            return {}
        return self.snapshots[latest]


def _build_scope(db: Session, user_id: int, first_day: int, last_day: int) -> _HistoryScope:
    dbuser = db.query(User).filter(User.id == user_id).first()
    user_bot_username = dbuser.bot_username if dbuser else None
    # reconstruct вызывается только для валидированного юзера (роутер гарантирует
    # существование через get_validated_user) — dbuser is None защитный краевой случай,
    # а не ожидаемый путь. При нём фильтр по инбаундам не применяем вовсе
    # (permissive-дефолт, тот же, что уже был у фильтра по боту): считать
    # несуществующего юзера лишённым вообще всех хостов было бы новым, никем не
    # проверенным поведением ради случая, который никогда не должен наступить.
    visible_tags = _visible_inbound_tags(dbuser) if dbuser else set()
    all_hosts = db.query(ProxyHost).order_by(ProxyHost.id).all()
    # Та же логика, что и в рендере подписки и в list_pinnable_hosts: пустой
    # bot_usernames = хост доступен всем ботам, отсеивать не надо. Плюс два фильтра
    # выше (is_disabled, инбаунды юзера, C2/M3) — см. докстринг reconstruct.
    hosts = [
        host
        for host in all_hosts
        if not host.is_disabled
        and host_allowed_for_bot(host.bot_usernames, user_bot_username)
        and (dbuser is None or host.inbound_tag in visible_tags)
    ]
    return _HistoryScope(
        user_id=user_id,
        offset=int(getattr(dbuser, "address_rotation_offset", 0) or 0) if dbuser else 0,
        # Единственная известная нам точка ротации — ПОСЛЕДНЯЯ (см. day_offset_known, C1).
        rotation_at=getattr(dbuser, "address_rotation_offset_at", None) if dbuser else None,
        hosts=hosts,
        composition=crud.get_host_composition_range(db, first_day, last_day),
        pins=crud.get_pins_covering_range(db, user_id, day_start_at(first_day), day_start_at(last_day + 1)),
        # Снимки эпох могут начинаться раньше запрошенного диапазона: период ротации
        # хоста бывает длиннее суток, и эпоха первого дня стартовала до него.
        snapshots=crud.get_weight_snapshots_range(db, first_day - ARCHIVE_RETENTION_DAYS, last_day),
        # Лимиты нужны, чтобы вывести исчерпание из снимка: вес — это остаток, а не доля.
        node_limits=crud.get_node_limits(db),
    )


def reconstruct_range(db: Session, user_id: int, first_day: int, last_day: int) -> dict[int, list[HostAssignment]]:
    """Журнал выдачи за диапазон суток включительно: day_index -> назначения по хостам.

    Диапазон, а не день, — основная форма: именно так журнал показывается саппорту
    (см. app/routers/user.py). Все чтения из БД делает `_build_scope` — по одному
    запросу на сущность, независимо от длины диапазона.
    """
    scope = _build_scope(db, user_id, first_day, last_day)
    return {day: _reconstruct_day(scope, day) for day in range(first_day, last_day + 1)}


def reconstruct(db: Session, user_id: int, day_index: int) -> list[HostAssignment]:
    """Восстанавливает выдачу адресов юзеру за сутки `day_index` по всем хостам.

    Алгоритм на каждый хост:
    1. Если на эти сутки был активный пин (created_at < конец суток и
       expires_at > начало суток) — источник "pin", ноды из пина, пересечённые
       с фактическим составом хоста за эти сутки (та же семантика пересечения,
       что в AddressContext.pick — закреплённая нода могла с тех пор отвязаться
       от хоста).
    2. Иначе — если сужение включено НА ЭТОМ ХОСТЕ, вычисляем эпоху юзера на
       эти сутки (epoch_for с его address_rotation_offset и периодом ротации
       хоста), берём снимок весов на начало этой эпохи, вычитаем исчерпанные по
       снимку ноды и прогоняем тот же choose_nodes, что работает в живой
       выдаче — источник "auto". Если на хосте сужение ВЫКЛЮЧЕНО — его не было,
       юзеру шёл ПОЛНЫЙ состав хоста: источник "auto", но без урезания.
    3. Если снимка СОСТАВА хоста за эти сутки нет вовсе — восстановить нечего
       (мы даже не знаем, какие ноды/адреса стояли за хостом): "unknown".
       Если снимка ВЕСОВ за эти сутки нет, а сужение в этот день было бы
       фактическим (включено на хосте И адресов больше размера подмножества) —
       тоже "unknown": угадывать веса значило бы выдавать может-быть-правду
       за факт.

    Настройки хоста гасят ТОЛЬКО автовыбор. Пины проверяются ДО них и от них не
    зависят вовсе — это то же решение, что уже реализовано в
    build_address_context: закрепление — явное административное действие
    саппорта для отладки именно там, где фича сужения ещё не включена, и
    выключенная на хосте настройка не должна его глушить.

    Допущение (смешанный payload): если в снимке состава для хоста часть
    записей содержит node_id, а часть — None (в теории не должно возникать,
    т.к. _host_payload пишет соответствие consistently: либо все None для
    статического host.address, либо все int для нодового), выбор уходит в
    ветку "по адресу без нод" (addresses_from_nodes=False, как и в
    AddressContext.pick) — и активный пин для такого хоста молча
    игнорируется, потому что пересекать node_id пина было бы не с чем.

    Хост показывается юзеру, только если он ему вообще мог достаться — ТРИ
    фильтра, те же, что применяет рендер подписки (см. `generate_v2ray_links` /
    `app/subscription/share.py`), а не переизобретённая здесь копия условий:
    1. Хост не отключён (`ProxyHost.is_disabled`) — выключенный хост джоба
       снимков и так не снимает (`snapshot_host_composition`), но если запись
       осталась в БД со старых суток, до выключения, её всё равно не надо
       показывать как нечто, что юзер мог бы получить СЕГОДНЯШНИМ запросом
       (тем же способом джоба уже фильтрует при снятии снимков).
    2. Привязка хоста к боту юзера (`host_allowed_for_bot`,
       `app/xray/host_addresses.py`) — хост, у которого задан непустой список
       `bot_usernames`, и юзер привязан к другому боту, отбрасывается. Без
       этого фильтра в мультибот-инсталляции история показала бы юзеру
       локации чужого бота как "автовыбор" с конкретными нодами — то самое
       правдоподобное вранье, которого весь этот модуль обязан избегать.
    3. Тег инбаунда хоста входит в эффективные инбаунды юзера
       (`_visible_inbound_tags`, читает `User.inbounds`) — учитывает и то,
       есть ли у юзера вообще прокси этого протокола, и `excluded_inbounds`.
       Без этого фильтра триальный/неоплативший юзер с урезанными
       `excluded_inbounds` увидел бы в истории локации, которые ему не
       рендерились НИКОГДА ни на одном хосте: `excluded_inbounds` активно
       используется, чтобы резать доступ именно таким юзерам.

    Источник данных для фильтров 1-2 — ТЕКУЩЕЕ состояние хоста
    (`ProxyHost.is_disabled`, `ProxyHost.bots`), не историческое: снимок
    состава их не хранит, а рендер подписки тоже всегда смотрит на текущую
    конфигурацию, а не на снимок на день рендера. Если хост включали/
    выключали или меняли его привязку к боту ПОСЛЕ `day_index` — история
    отразит сегодняшнее состояние, а не тогдашнее (тот хост, что тогда
    показывался юзеру, но с тех пор выключен или переехал к другому боту, из
    истории исчезнет; и наоборот). Это ограничение источника — панель не
    снимает эти атрибуты хоста посуточно, только адреса/веса.

    Ограничение статуса подписки и других состояний живой выдачи, которых
    `reconstruct` НЕ воспроизводит (I1):
    - `User.expire`/`sub_revoked_at`/`is_limited` (отозвана/истекла подписка,
      лимит устройств): живая выдача при этом адреса вовсе не отдаёт —
      показывает заглушку (см. is_revoked/is_expired в build_address_context
      и app/routers/subscription.py), а `reconstruct` этого не воспроизводит.
      Восстановить статус подписки задним числом нельзя: `User.expire`
      перезаписывается при каждом продлении, `User.sub_revoked_at` хранит
      только момент ПОСЛЕДНЕГО отзыва, истории переходов между статусами в
      модели нет вовсе — гадать по этим полям означало бы построить вторую
      версию той же лжи, от которой весь этот модуль защищает, только на
      другом основании.
    - Заблокированный БС-хост (`NodeUserBlock`, `app/subscription/bs_context.py`):
      живая выдача подменяет адрес на заглушку лимита (share.py:544), но
      `NodeUserBlock` хранит только ТЕКУЩЕЕ состояние блокировки — строка
      удаляется при разблокировке, истории блокировок нет. Восстановить,
      была ли нода заблокирована именно в `day_index`, нечем.
    Следствие для читающего ответ ОБОИХ пунктов: за сутки, когда подписка
    была недоступна, лимит устройств исчерпан или БС-хост был заблокирован,
    история всё равно покажет адреса, которых юзер фактически не получал —
    это документированная дыра в данных, а не баг восстановления.
    """
    return reconstruct_range(db, user_id, day_index, day_index)[day_index]


def _reconstruct_day(scope: _HistoryScope, day_index: int) -> list[HostAssignment]:
    """Одни сутки журнала по уже прочитанным данным диапазона (см. _HistoryScope)."""
    user_id = scope.user_id
    offset = scope.offset
    rotation_at = scope.rotation_at
    day_start = day_start_at(day_index)
    day_end = day_start_at(day_index + 1)

    composition = scope.composition.get(day_index, {})
    hosts = scope.hosts
    pins_on_day = scope.pins_on_day(day_start, day_end)

    # Настройки сужения живут на ХОСТЕ (NPVPN-2072), поэтому size/период/эпоха считаются
    # внутри цикла по хостам, а снимок весов берётся на начало эпохи КАЖДОГО периода —
    # у хостов с разными периодами эпохи стартуют в разные сутки. Пины при этом
    # проверяются раньше настроек и от них не зависят вовсе: закрепление — явное
    # административное действие для отладки именно там, где фичи ещё нет (тот же ruling,
    # что в build_address_context).
    #
    # Ограничение то же, что и раньше: настройки берутся ТЕКУЩИЕ. Истории изменения полей
    # хоста панель не хранит, и подставлять сегодняшние значения — меньшее зло, чем гадать.

    # C1: offset входит слагаемым в epoch_for, а users.address_rotation_offset
    # хранит только ТЕКУЩЕЕ значение — одно число без истории. Известна только
    # ПОСЛЕДНЯЯ ротация (address_rotation_offset_at): если она случилась ПОСЛЕ
    # начала day_index, offset на день day_index был другим (или несколькими
    # ротациями раньше) — восстановить промежуточные значения нечем, а
    # подставлять сегодняшний offset означало бы пересчитать эпоху задним
    # числом неверно и показать её как restorable=True (тот самый Critical:
    # кнопка "Перемешать" фальсифицировала бы историю всех прошлых суток).
    #
    # rotation_at is None => ротаций не было вовсе => offset всегда был 0 (тем,
    # что сейчас) => гасить нечего, все сутки день независимы от этого условия.
    # Ветка ПИНА выше не участвует: пин не зависит от offset/epoch вовсе.
    # day_start_at() отдаёт datetime с tzinfo=UTC (см. _EPOCH_ORIGIN), а
    # address_rotation_offset_at — обычная naive-UTC колонка (как остальные
    # DateTime этой модели, напр. created_at/sub_revoked_at) — сравнение "в
    # лоб" упало бы TypeError на разнице aware/naive, хотя оба представляют
    # тот же момент в UTC.
    day_offset_known = rotation_at is None or day_start.replace(tzinfo=None) >= rotation_at

    results: list[HostAssignment] = []
    for host in hosts:
        host_id = cast(int, host.id)
        remark = cast(str, host.remark)
        payload = composition.get(host_id)
        if payload is None:
            results.append(HostAssignment(host_id=host_id, remark=remark, source="unknown", restorable=False))
            continue

        node_ids_all = [item["node_id"] for item in payload]
        addresses_all = [item["address"] for item in payload]
        addresses_from_nodes = bool(node_ids_all) and all(nid is not None for nid in node_ids_all)

        pin_nodes = pins_on_day.get(host_id)
        if pin_nodes and addresses_from_nodes:
            pinned = set(pin_nodes) & set(node_ids_all)
            if pinned:
                chosen = [(nid, addr) for nid, addr in zip(node_ids_all, addresses_all, strict=True) if nid in pinned]
                results.append(
                    HostAssignment(
                        host_id=host_id,
                        remark=remark,
                        source="pin",
                        restorable=True,
                        node_ids=[nid for nid, _ in chosen],
                        addresses=[addr for _, addr in chosen],
                    )
                )
                continue

        # Автовыбор. Настройки — с ЭТОГО хоста: размер подмножества и период ротации у
        # каждого свои. Если подмножество не режет список (на хосте выключено или адресов
        # и так не больше size) — ответ полностью определён СОСТАВОМ и не зависит от весов
        # вовсе (см. pick_keys: при len(candidates) <= n он просто возвращает все ключи).
        # Объявлять его "не восстановимо" из-за отсутствующего снимка весов было бы ложной
        # скромностью — веса тут ни при чём, выдаём состав как есть.
        settings = settings_from_host(
            {
                "address_subset_enabled": host.address_subset_enabled,
                "address_subset_size": host.address_subset_size,
                "address_rotation_days": host.address_rotation_days,
            }
        )
        size = settings.size if settings.narrows else 0
        if size <= 0 or len(addresses_all) <= size:
            results.append(
                HostAssignment(
                    host_id=host_id,
                    remark=remark,
                    source="auto",
                    restorable=True,
                    node_ids=[nid for nid in node_ids_all if nid is not None],
                    addresses=addresses_all,
                )
            )
            continue

        weights = scope.weights_for(day_index, settings.rotation_days)
        if not weights:
            # Реальное сужение в этот день было бы, а весов нет: не гадаем,
            # каким было бы распределение — честно говорим "не восстановимо".
            results.append(HostAssignment(host_id=host_id, remark=remark, source="unknown", restorable=False))
            continue

        if not day_offset_known:
            # C1: epoch для этих суток зависел бы от offset, который на тот
            # момент мог быть другим — известна только ПОСЛЕДНЯЯ ротация.
            # Честно "не восстановимо", а не пересчёт с сегодняшним offset.
            results.append(HostAssignment(host_id=host_id, remark=remark, source="unknown", restorable=False))
            continue

        if addresses_from_nodes:
            epoch = epoch_for(user_id, day_index, settings.rotation_days, offset)
            chosen_nodes = choose_nodes(
                user_id,
                node_ids_all,
                weights=weights,
                # Исчерпание за прошедшие сутки выводится из снимка: свежего расхода за
                # тот день у нас нет (см. exhausted_from_snapshot).
                exhausted=exhausted_from_snapshot(weights, scope.node_limits, HOSTING_USAGE_CUTOFF_PERCENT),
                size=size,
                epoch=epoch,
            )
            chosen = [(nid, addr) for nid, addr in zip(node_ids_all, addresses_all, strict=True) if nid in chosen_nodes]
            node_ids_out = [nid for nid, _ in chosen]
            addresses_out = [addr for _, addr in chosen]
        else:
            by_address = [(addr, 0.0) for addr in addresses_all]
            epoch = epoch_for(user_id, day_index, settings.rotation_days, offset)
            chosen_addresses = set(pick_keys(user_id, by_address, size, epoch))
            node_ids_out = []
            addresses_out = [addr for addr in addresses_all if addr in chosen_addresses]

        results.append(
            HostAssignment(
                host_id=host_id,
                remark=remark,
                source="auto",
                restorable=True,
                node_ids=node_ids_out,
                addresses=addresses_out,
            )
        )

    return results


def day_start_at(day_index: int):
    """datetime начала указанных суток — обратная операция к day_index() из
    address_context_builder."""
    return _EPOCH_ORIGIN + timedelta(days=day_index)
