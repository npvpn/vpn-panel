"""Восстановление выдачи адресов задним числом — журнал для саппорта (NPVPN-2072).

Смысловое ядро фичи сужения адресов: ради этого и собираются суточные снимки
состава хостов (HostCompositionSnapshot) и весов нод (NodeWeightSnapshot).

Главный принцип: честность важнее полноты. Саппорт примет любой показанный
ответ за факт. Поэтому если по хосту за дату нет данных для однозначного
восстановления — источник "unknown" и restorable=False, а не пустой список
(который прочитают как "адресов не было") и не правдоподобная догадка по
чужим/неполным данным.

Историческая оговорка: `bot_settings` приходит СЕГОДНЯШНИМ — панель не хранит,
каким было `sub_address_subset_size`/`sub_address_rotation_days` в прошлом.
Реконструкция предполагает, что настройки сужения не менялись; если их
меняли, auto-часть истории за периоды до смены может быть неточной. Это
ограничение источника данных, а не что-то, что можно обойти в этом модуле.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal, cast

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import crud
from app.db.models import ProxyHost, User
from app.subscription.address_context import weighted_candidates
from app.subscription.address_context_builder import _EPOCH_ORIGIN
from app.xray.address_policy import ARCHIVE_RETENTION_DAYS, epoch_for, epoch_start_day, pick_keys
from app.xray.host_addresses import host_allowed_for_bot, visible_nodes

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

    Два фильтра, оба обязательны:
    1. Хост привязан к боту юзера (или ни к какому конкретному боту) — та же
       логика, что в `reconstruct`/рендере подписки: иначе саппорт увидел бы
       и мог бы закрепить локацию ЧУЖОГО бота, которая этому юзеру никогда не
       достанется.
    2. У хоста нет статического `address` (`not host.address` — пустая строка
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
    hosts = db.query(ProxyHost).filter(ProxyHost.address == "").order_by(ProxyHost.id).all()
    return [
        PinnableHost(
            host_id=cast(int, host.id),
            remark=cast(str, host.remark),
            nodes=[PinnableNode(node_id=cast(int, node.id), name=cast(str, node.name)) for node in visible_nodes(host)],
        )
        for host in hosts
        if host_allowed_for_bot(host.bot_usernames, user_bot_username)
    ]


def reconstruct(db: Session, user_id: int, day_index: int, bot_settings: dict) -> list[HostAssignment]:
    """Восстанавливает выдачу адресов юзеру за сутки `day_index` по всем хостам.

    Алгоритм на каждый хост:
    1. Если на эти сутки был активный пин (created_at < конец суток и
       expires_at > начало суток) — источник "pin", ноды из пина, пересечённые
       с фактическим составом хоста за эти сутки (та же семантика пересечения,
       что в AddressContext.pick — закреплённая нода могла с тех пор отвязаться
       от хоста).
    2. Иначе — если `sub_address_subset_enabled` включён, вычисляем эпоху
       юзера на эти сутки (epoch_for с его address_rotation_offset), берём
       снимок весов на начало этой эпохи и прогоняем тот же pick_keys, что
       работает в живой выдаче — источник "auto". Если флаг ВЫКЛЮЧЕН —
       сужения не было (см. build_address_context: при выключенном флаге
       size обнуляется независимо от sub_address_subset_size), юзеру шёл
       ПОЛНЫЙ состав хоста — источник "auto", но без урезания.
    3. Если снимка СОСТАВА хоста за эти сутки нет вовсе — восстановить нечего
       (мы даже не знаем, какие ноды/адреса стояли за хостом): "unknown".
       Если снимка ВЕСОВ за эти сутки нет, а сужение в этот день было бы
       фактическим (флаг включён И адресов больше размера подмножества) —
       тоже "unknown": угадывать веса значило бы выдавать может-быть-правду
       за факт.

    Флаг `sub_address_subset_enabled` гасит ТОЛЬКО автовыбор. Пины проверяются
    ДО флага и от него не зависят вовсе — это то же решение, что уже
    реализовано в build_address_context: закрепление — явное административное
    действие саппорта для отладки именно там, где фича сужения ещё не
    включена, и выключенный флаг не должен его глушить.

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
    day_start = day_start_at(day_index)
    day_end = day_start_at(day_index + 1)

    dbuser = db.query(User).filter(User.id == user_id).first()
    offset = int(getattr(dbuser, "address_rotation_offset", 0) or 0) if dbuser else 0
    # Единственная известная нам точка ротации — ПОСЛЕДНЯЯ (см. пояснение у
    # day_offset_known ниже, C1).
    rotation_at = getattr(dbuser, "address_rotation_offset_at", None) if dbuser else None
    user_bot_username = dbuser.bot_username if dbuser else None
    # reconstruct вызывается только для валидированного юзера (роутер
    # гарантирует существование через get_validated_user) — dbuser is None
    # защитный краевой случай, а не ожидаемый путь. При нём фильтр по
    # инбаундам не применяем вовсе (permissive-дефолт, тот же, что уже был у
    # фильтра по боту): считать несуществующего юзера лишённым вообще всех
    # хостов было бы новым, никем не проверенным поведением ради случая,
    # который никогда не должен наступить на живом роутере.
    visible_tags = _visible_inbound_tags(dbuser) if dbuser else set()

    composition = crud.get_host_composition(db, day_index)
    all_hosts = db.query(ProxyHost).order_by(ProxyHost.id).all()
    # Та же логика, что и в рендере подписки и в list_pinnable_hosts: пустой
    # bot_usernames = хост доступен всем ботам, отсеивать не надо. Плюс два
    # фильтра выше (is_disabled, инбаунды юзера, C2/M3) — см. докстринг.
    hosts = [
        host
        for host in all_hosts
        if not host.is_disabled
        and host_allowed_for_bot(host.bot_usernames, user_bot_username)
        and (dbuser is None or host.inbound_tag in visible_tags)
    ]
    pins_on_day = crud.get_pins_covering_day(db, user_id, day_start, day_end)

    # Флаг гасит ТОЛЬКО автовыбор — та же развилка, что в build_address_context
    # (app/subscription/address_context_builder.py): при выключенном
    # sub_address_subset_enabled size обнуляется НЕЗАВИСИМО от значения
    # sub_address_subset_size (дефолт бота — enabled=False, size=2, см.
    # app/models/bot.py — это состояние ЛЮБОГО бота, который фичу не включал).
    # Пины при этом проверяются раньше и не зависят от флага вовсе — они
    # применяются даже когда фича выключена (см. ruling в
    # build_address_context: закрепление — явное административное действие
    # для отладки именно там, где фичи ещё нет).
    enabled = bool(bot_settings.get("sub_address_subset_enabled"))
    period_days = max(1, int(bot_settings.get("sub_address_rotation_days") or 1))
    size = int(bot_settings.get("sub_address_subset_size") or 0) if enabled else 0
    epoch = epoch_for(user_id, day_index, period_days, offset)
    snapshot_day = epoch_start_day(user_id, day_index, period_days)
    # Как и build_address_context — весами не интересуемся, если сужения не
    # будет и так (флаг выключен или size<=0): лишний поход в БД не нужен.
    weights = crud.get_weight_snapshot(db, snapshot_day) if size > 0 else {}

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

        # Автовыбор. Если подмножество не режет список (фича выключена в
        # today-конфиге или адресов и так не больше size) — ответ полностью
        # определён СОСТАВОМ и не зависит от весов вовсе (см. pick_keys: при
        # len(candidates) <= n он просто возвращает все ключи). Объявлять его
        # "не восстановимо" из-за отсутствующего снимка весов было бы ложной
        # скромностью — веса тут ни при чём, выдаём состав как есть.
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
            candidates = list(weighted_candidates(weights, node_ids_all).items())
            chosen_nodes = set(pick_keys(user_id, candidates, size, epoch))
            chosen = [(nid, addr) for nid, addr in zip(node_ids_all, addresses_all, strict=True) if nid in chosen_nodes]
            node_ids_out = [nid for nid, _ in chosen]
            addresses_out = [addr for _, addr in chosen]
        else:
            by_address = [(addr, 0.0) for addr in addresses_all]
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
