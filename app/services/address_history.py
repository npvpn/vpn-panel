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
from app.xray.address_policy import epoch_for, epoch_start_day, pick_keys

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


# Архивный горизонт закреплений: тот же, что у снимков состава/весов
# (prune_host_composition_snapshots, NodeWeightSnapshot). Пин с TTL дальше
# этого горизонта пережил бы собственную историю — стал бы необъяснимым,
# когда журнал за его срок уже вычищен.
MAX_PIN_TTL_DAYS = 90


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

    Хост показывается юзеру, только если он ему вообще мог достаться — тот же
    фильтр по привязке хоста к боту юзера, что и рендер подписки (см.
    `generate_v2ray_links` / `app/subscription/share.py`, где хост
    отбрасывается, если у него задан непустой список `bot_usernames` и юзер
    привязан к другому боту). Без этого фильтра в мультибот-инсталляции
    история показала бы юзеру локации чужого бота как "автовыбор" с
    конкретными нодами — то самое правдоподобное вранье, которого весь этот
    модуль обязан избегать.

    Источник данных для фильтра — ТЕКУЩАЯ привязка хоста к боту
    (`ProxyHost.bots`), не историческая: снимок состава её не хранит, а
    рендер подписки тоже всегда смотрит на текущую конфигурацию, а не на
    снимок на день рендера. Если привязку хоста к боту меняли ПОСЛЕ
    `day_index` — история отразит сегодняшнюю принадлежность, а не тогдашнюю
    (тот хост, что тогда показывался юзеру, но с тех пор переехал к другому
    боту, из истории исчезнет; и наоборот, хост, привязанный к боту юзера
    только сегодня, задним числом покажется так, будто был доступен всегда).
    Это ограничение источника — панель принадлежность хост↔бот не снимает
    посуточно, только адреса/веса.

    Ограничение статуса подписки: журнал отвечает на вопрос "что выбрал бы
    алгоритм подмножества за эти сутки", а не "была ли подписка вообще
    доступна юзеру в этот день". Живая выдача при отозванной или истёкшей
    подписке адреса вовсе не отдаёт — показывает заглушку (см. is_revoked/
    is_expired в build_address_context и app/routers/subscription.py), и
    `reconstruct` этого не воспроизводит. Восстановить статус подписки
    задним числом нельзя: `User.expire` перезаписывается при каждом
    продлении, `User.sub_revoked_at` хранит только момент ПОСЛЕДНЕГО отзыва,
    истории переходов между статусами в модели нет вовсе — гадать по этим
    полям означало бы построить вторую версию той же лжи, от которой весь
    этот модуль защищает, только на другом основании. Следствие для
    читающего ответ: за сутки, когда подписка была недоступна (отозвана/
    истекла), история всё равно покажет адреса, которых юзер фактически не
    получал — это дыра в данных, а не баг восстановления.
    """
    day_start = day_start_at(day_index)
    day_end = day_start_at(day_index + 1)

    dbuser = db.query(User).filter(User.id == user_id).first()
    offset = int(getattr(dbuser, "address_rotation_offset", 0) or 0) if dbuser else 0
    user_bot_username = dbuser.bot_username if dbuser else None

    composition = crud.get_host_composition(db, day_index)
    all_hosts = db.query(ProxyHost).order_by(ProxyHost.id).all()
    # Та же логика, что и в рендере подписки: пустой bot_usernames = хост
    # доступен всем ботам, отсеивать не надо; юзер без своего бота видит хосты
    # как раньше (краевой случай рендера — намеренно воспроизведён без изменений).
    hosts = [
        host
        for host in all_hosts
        if not (host.bot_usernames and user_bot_username and user_bot_username not in host.bot_usernames)
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
