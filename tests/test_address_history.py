"""address_history.reconstruct: восстановление выдачи адресов задним числом (NPVPN-2072).

Смысловое ядро журнала: то, ради чего собираются суточные снимки состава хостов
и весов нод. Тестируем функцию восстановления напрямую (не HTTP-слой) — тот же
подход, что в test_address_context_builder.py и test_host_composition_snapshot.py.
"""

from __future__ import annotations

import sys
import types
from datetime import timedelta

# app/__init__.py тяжёлый, а app.subscription.share тянет за собой весь стек
# генерации ссылок — тот же обход, что в соседних тестах NPVPN-2072.
for _name, _module in list(sys.modules.items()):
    if _name.startswith("app.") and not hasattr(_module, "__file__") and not hasattr(_module, "__path__"):
        del sys.modules[_name]

_share_stub = types.ModuleType("app.subscription.share")
_share_stub.generate_v2ray_links = lambda *args, **kwargs: []
sys.modules.setdefault("app.subscription.share", _share_stub)

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import xray  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.crud import write_host_composition_snapshot  # noqa: E402
from app.db.models import (  # noqa: E402
    Bot,
    Node,
    NodeWeightSnapshot,
    Proxy,
    ProxyHost,
    ProxyInbound,
    User,
    UserNodePin,
)
from app.models.proxy import ProxyTypes  # noqa: E402
from app.services.address_history import (  # noqa: E402
    day_start_at,
    list_pinnable_hosts,
    reconstruct,
    reconstruct_range,
)
from app.subscription.address_context import weighted_candidates  # noqa: E402
from app.xray.address_policy import pick_keys  # noqa: E402

if sys.modules.get("app.subscription.share") is _share_stub:
    del sys.modules["app.subscription.share"]

USER_ID = 1
DAY = 100


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _make_node(db, name: str, address: str, node_id: int | None = None) -> Node:
    node = Node(id=node_id, name=name, address=address, port=62050, api_port=62051)
    db.add(node)
    db.commit()
    db.refresh(node)
    return node


def _make_host(
    db,
    *,
    nodes: list[Node],
    remark: str = "host-remark",
    bots: list[Bot] | None = None,
    subset_enabled: bool = True,
    subset_size: int | None = 2,
    rotation_days: int | None = 1,
) -> ProxyHost:
    """Хост с пер-хостовыми настройками сужения (NPVPN-2072).

    rotation_days=1 делает epoch_start_day(user_id, day, 1) == day для любого юзера
    (сдвиг «размазки» внутри периода в один день не существует) — так тест не зависит
    от хеша смещения по юзеру.
    """
    inbound_tag = f"tag-{db.query(ProxyInbound).count()}"
    db.add(ProxyInbound(tag=inbound_tag))
    db.commit()
    host = ProxyHost(
        remark=remark,
        address="",
        inbound_tag=inbound_tag,
        address_subset_enabled=subset_enabled,
        address_subset_size=subset_size,
        address_rotation_days=rotation_days,
    )
    host.nodes = nodes
    if bots:
        host.bots = bots
    db.add(host)
    db.commit()
    db.refresh(host)
    return host


def _make_user(db, user_id: int = USER_ID, *, bot: Bot | None = None) -> User:
    user = User(id=user_id, username=f"u{user_id}", address_rotation_offset=0, bot=bot)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_bot(db, username: str) -> Bot:
    bot = Bot(username=username)
    db.add(bot)
    db.commit()
    db.refresh(bot)
    return bot


class _FakeXrayConfig:
    """Минимальная замена app.xray.config для песочницы (tests/conftest.py
    ставит app.xray заглушкой БЕЗ .config — реальный app/xray/__init__.py в
    ней не выполняется)."""

    def __init__(self, inbounds_by_protocol: dict) -> None:
        self.inbounds_by_protocol = inbounds_by_protocol


def _grant_inbound_access(
    monkeypatch, db, user: User, hosts: list[ProxyHost], *, proxy_type: ProxyTypes = ProxyTypes.VLESS
) -> None:
    """Даёт юзеру доступ к инбаундам перечисленных хостов (C2, NPVPN-2072).

    `User.inbounds` (app/db/models.py) читает теги из `xray.config.inbounds_by_protocol`
    — живого xray_config.json, а не из ProxyInbound в БД. В песочнице такого
    конфига нет вовсе (tests/conftest.py стабит app.xray пустым пакетом), поэтому
    заводим Proxy нужного протокола и монкейпатчим САМ АТРИБУТ `xray.config`
    (не его поле — он изначально отсутствует), как будто теги перечисленных
    хостов зарегистрированы в живом конфиге. Без этого reconstruct отфильтровал
    бы ВСЕ хосты C2-фильтром по инбаундам — тест ничего не проверил бы про сам
    фильтр."""
    db.add(Proxy(user_id=user.id, type=proxy_type, settings={}))
    db.commit()
    monkeypatch.setattr(
        xray,
        "config",
        _FakeXrayConfig({proxy_type: [{"tag": host.inbound_tag} for host in hosts]}),
        raising=False,
    )


def test_reconstructs_auto_assignment_from_snapshots(db, monkeypatch):
    """Без пина ответ собирается хешем по снимкам весов и состава за те сутки."""
    user = _make_user(db)
    nodes = [_make_node(db, f"n{i}", f"1.2.3.{i}") for i in range(1, 5)]
    host = _make_host(db, nodes=nodes)
    _grant_inbound_access(monkeypatch, db, user, [host])

    payload = [{"node_id": n.id, "address": n.address} for n in nodes]
    write_host_composition_snapshot(db, DAY, host.id, payload)
    db.commit()

    weights = {nodes[0].id: 10.0, nodes[1].id: 20.0, nodes[2].id: 5.0, nodes[3].id: 1.0}
    for node_id, weight in weights.items():
        db.add(NodeWeightSnapshot(epoch_index=DAY, node_id=node_id, weight=weight))
    db.commit()

    result = reconstruct(db, USER_ID, DAY)

    assert len(result) == 1
    assignment = result[0]
    assert assignment.host_id == host.id
    assert assignment.remark == "host-remark"
    assert assignment.source == "auto"
    assert assignment.restorable is True

    # Сверяем с реальным алгоритмом выдачи (тот же pick_keys/weighted_candidates,
    # что использует AddressContext.pick), а не с переизобретённой в тесте копией.
    node_ids = [n.id for n in nodes]
    candidates = list(weighted_candidates(weights, node_ids).items())
    expected_nodes = set(pick_keys(USER_ID, candidates, 2, DAY))
    assert set(assignment.node_ids) == expected_nodes
    assert len(assignment.addresses) == 2


def test_pin_wins_over_recomputation(db, monkeypatch):
    """Пин, активный на ту дату, и есть ответ — пересчёт не применяется."""
    user = _make_user(db)
    nodes = [_make_node(db, f"n{i}", f"1.2.3.{i}") for i in range(1, 5)]
    host = _make_host(db, nodes=nodes)
    _grant_inbound_access(monkeypatch, db, user, [host])

    payload = [{"node_id": n.id, "address": n.address} for n in nodes]
    write_host_composition_snapshot(db, DAY, host.id, payload)
    db.commit()
    # Намеренно НЕТ снимка весов — если бы пин не выигрывал, auto-ветка
    # свалилась бы в "unknown". Пин обязан вернуть ответ без весов вовсе.

    pinned_node = nodes[2]
    db.add(
        UserNodePin(
            user_id=USER_ID,
            host_id=host.id,
            node_ids=[pinned_node.id],
            created_at=day_start_at(DAY),
            expires_at=day_start_at(DAY + 5),
            created_by="support",
        )
    )
    db.commit()

    result = reconstruct(db, USER_ID, DAY)

    assert len(result) == 1
    assignment = result[0]
    assert assignment.source == "pin"
    assert assignment.restorable is True
    assert assignment.node_ids == [pinned_node.id]
    assert assignment.addresses == [pinned_node.address]


def test_expired_pin_does_not_affect_later_dates(db, monkeypatch):
    """Истёкший пин виден в своей дате и не влияет на последующие."""
    user = _make_user(db)
    nodes = [_make_node(db, f"n{i}", f"1.2.3.{i}") for i in range(1, 3)]
    host = _make_host(db, nodes=nodes)
    _grant_inbound_access(monkeypatch, db, user, [host])

    payload = [{"node_id": n.id, "address": n.address} for n in nodes]
    # Состав неизменен оба дня.
    write_host_composition_snapshot(db, DAY, host.id, payload)
    write_host_composition_snapshot(db, DAY + 1, host.id, payload)
    db.commit()

    pinned_node = nodes[0]
    db.add(
        UserNodePin(
            user_id=USER_ID,
            host_id=host.id,
            node_ids=[pinned_node.id],
            created_at=day_start_at(DAY),
            expires_at=day_start_at(DAY + 1),  # истекает ровно на границе суток DAY -> DAY+1
            created_by="support",
        )
    )
    db.commit()

    on_pin_day = reconstruct(db, USER_ID, DAY)
    assert on_pin_day[0].source == "pin"
    assert on_pin_day[0].node_ids == [pinned_node.id]

    # На DAY+1 адресов всего 2 <= size(2) — авто-ветке веса не нужны, поэтому
    # честно возвращается полный состав, а не "unknown".
    on_later_day = reconstruct(db, USER_ID, DAY + 1)
    assert on_later_day[0].source == "auto"
    assert set(on_later_day[0].node_ids) == {n.id for n in nodes}


def test_missing_snapshot_reports_unknown_rather_than_guessing(db, monkeypatch):
    """Снимка за дату нет — честно сообщаем, что восстановить нельзя, а не молчим
    пустым списком и не подсовываем правдоподобную догадку."""
    user = _make_user(db)
    nodes_a = [_make_node(db, f"a{i}", f"9.9.9.{i}") for i in range(1, 5)]
    host_missing_composition = _make_host(db, nodes=nodes_a)
    # Намеренно НЕ пишем снимок состава для этого хоста на DAY.

    nodes_b = [_make_node(db, f"b{i}", f"8.8.8.{i}") for i in range(1, 5)]
    host_missing_weights = _make_host(db, nodes=nodes_b)
    write_host_composition_snapshot(
        db, DAY, host_missing_weights.id, [{"node_id": n.id, "address": n.address} for n in nodes_b]
    )
    db.commit()
    _grant_inbound_access(monkeypatch, db, user, [host_missing_composition, host_missing_weights])
    # Состав есть, но снимка весов на DAY нет, а 4 адреса > size(2) — реальное
    # сужение было бы, угадывать веса нельзя.

    result = reconstruct(db, USER_ID, DAY)
    by_host = {a.host_id: a for a in result}

    assert len(result) == 2  # оба хоста присутствуют в ответе, не пропущены молча

    missing_composition = by_host[host_missing_composition.id]
    assert missing_composition.source == "unknown"
    assert missing_composition.restorable is False
    assert missing_composition.node_ids == []
    assert missing_composition.addresses == []

    missing_weights = by_host[host_missing_weights.id]
    assert missing_weights.source == "unknown"
    assert missing_weights.restorable is False
    assert missing_weights.node_ids == []
    assert missing_weights.addresses == []


def test_day_start_at_roundtrips_with_day_index():
    from app.subscription.address_context_builder import day_index

    day = 42
    start = day_start_at(day)
    assert day_index(start) == day
    assert day_index(start + timedelta(hours=23, minutes=59)) == day
    assert day_index(start + timedelta(days=1)) == day + 1


def test_hides_hosts_restricted_to_other_bots(db, monkeypatch):
    """История не должна показывать юзеру локации, которые ему в принципе не
    могли достаться: тот же фильтр по bot_usernames, что и рендер подписки
    (app/subscription/share.py). Хост, привязанный только к чужому боту,
    обязан выпасть из ответа; хост без ограничений (bot_usernames пуст) —
    остаться."""
    bot_a = _make_bot(db, "bot_a")
    bot_b = _make_bot(db, "bot_b")
    user = _make_user(db, bot=bot_a)

    nodes_restricted = [_make_node(db, f"r{i}", f"7.7.7.{i}") for i in range(1, 3)]
    host_for_bot_b = _make_host(db, nodes=nodes_restricted, remark="only-bot-b", bots=[bot_b])

    nodes_open = [_make_node(db, f"o{i}", f"6.6.6.{i}") for i in range(1, 3)]
    host_unrestricted = _make_host(db, nodes=nodes_open, remark="open-to-all")

    for host, nodes in ((host_for_bot_b, nodes_restricted), (host_unrestricted, nodes_open)):
        write_host_composition_snapshot(db, DAY, host.id, [{"node_id": n.id, "address": n.address} for n in nodes])
    db.commit()
    _grant_inbound_access(monkeypatch, db, user, [host_for_bot_b, host_unrestricted])

    result = reconstruct(db, USER_ID, DAY)
    host_ids = {a.host_id for a in result}

    assert host_unrestricted.id in host_ids
    assert host_for_bot_b.id not in host_ids


def test_hides_hosts_outside_users_inbounds(db, monkeypatch):
    """C2 (Critical, финальное ревью, NPVPN-2072): триальный/неоплативший юзер
    с урезанными excluded_inbounds не должен увидеть в истории локацию
    исключённого тега — тот же источник, что и рендер подписки читает
    (User.inbounds, app/db/models.py, учитывает Proxy.excluded_inbounds)."""
    user = _make_user(db)
    nodes_visible = [_make_node(db, f"v{i}", f"5.5.5.{i}") for i in range(1, 3)]
    host_visible = _make_host(db, nodes=nodes_visible, remark="visible")
    nodes_excluded = [_make_node(db, f"e{i}", f"4.4.4.{i}") for i in range(1, 3)]
    host_excluded = _make_host(db, nodes=nodes_excluded, remark="excluded")

    for host, nodes in ((host_visible, nodes_visible), (host_excluded, nodes_excluded)):
        write_host_composition_snapshot(db, DAY, host.id, [{"node_id": n.id, "address": n.address} for n in nodes])
    db.commit()

    # Оба тега зарегистрированы в xray.config (т.е. у юзера в принципе есть
    # прокси этого протокола), но host_excluded попадает в excluded_inbounds
    # прокси юзера — именно так живая выдача режет доступ неоплатившим.
    _grant_inbound_access(monkeypatch, db, user, [host_visible, host_excluded])
    proxy = db.query(Proxy).filter(Proxy.user_id == user.id).one()
    excluded_inbound = db.query(ProxyInbound).filter(ProxyInbound.tag == host_excluded.inbound_tag).one()
    proxy.excluded_inbounds = [excluded_inbound]
    db.commit()

    result = reconstruct(db, USER_ID, DAY)
    host_ids = {a.host_id for a in result}

    assert host_visible.id in host_ids
    assert host_excluded.id not in host_ids


def test_hides_hosts_for_protocol_without_any_proxy(db, monkeypatch):
    """C2: тег зарегистрирован в xray.config, но у юзера ВООБЩЕ нет прокси
    этого протокола (не создан, а не просто исключён) — живая выдача такой
    хост тоже не рендерит (`for protocol, tags in inbounds.items(): settings =
    proxies.get(protocol); if not settings: continue`, app/subscription/share.py)."""
    user = _make_user(db)
    nodes = [_make_node(db, f"n{i}", f"2.2.2.{i}") for i in range(1, 3)]
    host = _make_host(db, nodes=nodes, remark="no-proxy-for-protocol")
    write_host_composition_snapshot(db, DAY, host.id, [{"node_id": n.id, "address": n.address} for n in nodes])
    db.commit()

    # Тег присутствует в конфиге, но Proxy для юзера НЕ создаём вовсе.
    monkeypatch.setattr(xray, "config", _FakeXrayConfig({ProxyTypes.VLESS: [{"tag": host.inbound_tag}]}), raising=False)

    result = reconstruct(db, USER_ID, DAY)

    assert result == []


def test_disabled_host_hidden_from_history(db, monkeypatch):
    """M3 (финальное ревью, NPVPN-2072): reconstruct фильтрует is_disabled так
    же, как джоба снимков (snapshot_host_composition.py: `.filter(ProxyHost.
    is_disabled.isnot(True))`) — иначе выключенный хост со старым снимком (со
    времён до выключения) показался бы как нечто, что юзер мог бы получить
    СЕГОДНЯШНИМ запросом."""
    user = _make_user(db)
    nodes = [_make_node(db, f"n{i}", f"3.3.3.{i}") for i in range(1, 3)]
    host = _make_host(db, nodes=nodes, remark="disabled-host")
    write_host_composition_snapshot(db, DAY, host.id, [{"node_id": n.id, "address": n.address} for n in nodes])
    db.commit()
    _grant_inbound_access(monkeypatch, db, user, [host])

    host.is_disabled = True
    db.commit()

    result = reconstruct(db, USER_ID, DAY)

    assert result == []


def test_rotation_after_day_makes_auto_epoch_unknown(db, monkeypatch):
    """C1 (Critical, финальное ревью, NPVPN-2072): кнопка «Перемешать» не
    должна задним числом фальсифицировать историю. Ротация (address_rotation_
    offset_at) случилась ПОСЛЕ day_index — offset, действовавший В day_index,
    неизвестен (это могло быть более раннее значение, а известна только
    ПОСЛЕДНЯЯ ротация), поэтому epoch для pick_keys не восстановим — весь
    auto-ответ уходит в "unknown", а не пересчитывается СЕГОДНЯШНИМ offset."""
    user = _make_user(db)
    nodes = [_make_node(db, f"n{i}", f"1.2.3.{i}") for i in range(1, 5)]
    host = _make_host(db, nodes=nodes)
    _grant_inbound_access(monkeypatch, db, user, [host])

    payload = [{"node_id": n.id, "address": n.address} for n in nodes]
    write_host_composition_snapshot(db, DAY, host.id, payload)
    for node, weight in zip(nodes, (10.0, 20.0, 5.0, 1.0), strict=True):
        db.add(NodeWeightSnapshot(epoch_index=DAY, node_id=node.id, weight=weight))
    db.commit()

    user.address_rotation_offset = 1
    user.address_rotation_offset_at = day_start_at(DAY + 1).replace(tzinfo=None)
    db.commit()

    result = reconstruct(db, USER_ID, DAY)

    assert len(result) == 1
    assignment = result[0]
    assert assignment.source == "unknown"
    assert assignment.restorable is False
    assert assignment.node_ids == []
    assert assignment.addresses == []


def test_rotation_before_day_keeps_auto_restorable(db, monkeypatch):
    """C1: ротация ДО этих суток — offset уже был текущим значением весь
    day_index, эпоха восстановима как обычно (с ЭТИМ offset, не с нулевым)."""
    user = _make_user(db)
    nodes = [_make_node(db, f"n{i}", f"1.2.3.{i}") for i in range(1, 5)]
    host = _make_host(db, nodes=nodes)
    _grant_inbound_access(monkeypatch, db, user, [host])

    payload = [{"node_id": n.id, "address": n.address} for n in nodes]
    write_host_composition_snapshot(db, DAY, host.id, payload)
    weights = {nodes[0].id: 10.0, nodes[1].id: 20.0, nodes[2].id: 5.0, nodes[3].id: 1.0}
    for node_id, weight in weights.items():
        db.add(NodeWeightSnapshot(epoch_index=DAY, node_id=node_id, weight=weight))
    db.commit()

    user.address_rotation_offset = 1
    user.address_rotation_offset_at = day_start_at(DAY - 1).replace(tzinfo=None)
    db.commit()

    result = reconstruct(db, USER_ID, DAY)

    assert len(result) == 1
    assignment = result[0]
    assert assignment.source == "auto"
    assert assignment.restorable is True

    # period_days=1 => _smear==0 => epoch_for(..., offset=1) == DAY + 1: сверяем
    # с реальным pick_keys на ЭТОЙ эпохе (не DAY, offset=0), чтобы доказать, что
    # offset действительно учтён, а не просто проигнорирован.
    node_ids = [n.id for n in nodes]
    candidates = list(weighted_candidates(weights, node_ids).items())
    expected_nodes = set(pick_keys(USER_ID, candidates, 2, DAY + 1))
    assert set(assignment.node_ids) == expected_nodes


def test_pin_restorable_even_when_rotation_gates_auto(db, monkeypatch):
    """C1: ветка пина не зависит от offset/epoch вовсе — пин обязан остаться
    restorable=True даже в сутки, для которых auto-ответ того же хоста ушёл
    бы в unknown из-за C1-гейта."""
    user = _make_user(db)
    nodes = [_make_node(db, f"n{i}", f"1.2.3.{i}") for i in range(1, 5)]
    host = _make_host(db, nodes=nodes)
    _grant_inbound_access(monkeypatch, db, user, [host])

    payload = [{"node_id": n.id, "address": n.address} for n in nodes]
    write_host_composition_snapshot(db, DAY, host.id, payload)

    pinned_node = nodes[0]
    db.add(
        UserNodePin(
            user_id=USER_ID,
            host_id=host.id,
            node_ids=[pinned_node.id],
            created_at=day_start_at(DAY),
            expires_at=day_start_at(DAY + 5),
            created_by="support",
        )
    )
    db.commit()

    user.address_rotation_offset = 1
    user.address_rotation_offset_at = day_start_at(DAY + 1).replace(tzinfo=None)
    db.commit()

    result = reconstruct(db, USER_ID, DAY)

    assert len(result) == 1
    assignment = result[0]
    assert assignment.source == "pin"
    assert assignment.restorable is True
    assert assignment.node_ids == [pinned_node.id]


def test_disabled_host_shows_full_composition_not_a_guessed_subset(db, monkeypatch):
    """Критический регресс: сужение на хосте выключено — юзеру шёл ПОЛНЫЙ состав хоста.
    Дефолт хоста — address_subset_enabled=False, то есть это состояние ЛЮБОГО хоста,
    на котором фичу не включали. История обязана показать все адреса, а не выдумать
    сужение до двух, которого в реальности не было."""
    user = _make_user(db)
    nodes = [_make_node(db, f"n{i}", f"1.2.3.{i}") for i in range(1, 5)]
    host = _make_host(db, nodes=nodes, subset_enabled=False)
    _grant_inbound_access(monkeypatch, db, user, [host])

    payload = [{"node_id": n.id, "address": n.address} for n in nodes]
    write_host_composition_snapshot(db, DAY, host.id, payload)
    db.commit()
    # Намеренно НЕТ снимка весов — при выключенном флаге они и не должны
    # понадобиться: сужения нет, значит и весов не спрашиваем.

    result = reconstruct(db, USER_ID, DAY)

    assert len(result) == 1
    assignment = result[0]
    assert assignment.source == "auto"
    assert assignment.restorable is True
    assert set(assignment.node_ids) == {n.id for n in nodes}
    assert set(assignment.addresses) == {n.address for n in nodes}


def test_pin_applies_even_when_host_subset_disabled(db, monkeypatch):
    """Пины не зависят от настроек сужения хоста — то же решение, что уже
    реализовано в build_address_context (закрепление — административное
    действие саппорта для отладки именно там, где фича ещё выключена)."""
    user = _make_user(db)
    nodes = [_make_node(db, f"n{i}", f"1.2.3.{i}") for i in range(1, 5)]
    host = _make_host(db, nodes=nodes, subset_enabled=False)
    _grant_inbound_access(monkeypatch, db, user, [host])

    payload = [{"node_id": n.id, "address": n.address} for n in nodes]
    write_host_composition_snapshot(db, DAY, host.id, payload)
    db.commit()

    pinned_node = nodes[1]
    db.add(
        UserNodePin(
            user_id=USER_ID,
            host_id=host.id,
            node_ids=[pinned_node.id],
            created_at=day_start_at(DAY),
            expires_at=day_start_at(DAY + 5),
            created_by="support",
        )
    )
    db.commit()

    result = reconstruct(db, USER_ID, DAY)

    assert len(result) == 1
    assignment = result[0]
    assert assignment.source == "pin"
    assert assignment.restorable is True
    assert assignment.node_ids == [pinned_node.id]
    assert assignment.addresses == [pinned_node.address]


def test_pinnable_hosts_scoped_to_users_bot(db, monkeypatch):
    """Юзер бота A видит свои локации и не видит локации, разрешённые только
    боту B — тот же фильтр по bot_usernames, что и в reconstruct/рендере
    подписки. Иначе саппорт мог бы создать закрепление на локацию, которая
    этому юзеру никогда не достанется."""
    bot_a = _make_bot(db, "bot_a")
    bot_b = _make_bot(db, "bot_b")
    user = _make_user(db, bot=bot_a)

    nodes_a = [_make_node(db, f"a{i}", f"9.9.9.{i}") for i in range(1, 3)]
    host_a = _make_host(db, nodes=nodes_a, remark="only-bot-a", bots=[bot_a])

    nodes_b = [_make_node(db, f"b{i}", f"8.8.8.{i}") for i in range(1, 3)]
    host_b = _make_host(db, nodes=nodes_b, remark="only-bot-b", bots=[bot_b])
    _grant_inbound_access(monkeypatch, db, user, [host_a, host_b])

    result = list_pinnable_hosts(db, user)
    host_ids = {h.host_id for h in result}

    assert host_ids == {host_a.id}


def test_pinnable_hosts_excludes_static_address_hosts(db, monkeypatch):
    """Легаси-хост со статическим адресом (address != "") не попадает в
    список: соответствия "адрес ↔ нода" там нет по построению, POST /pins
    его и так отклонит 400-й — показывать в форме то, что заведомо будет
    отклонено, незачем."""
    user = _make_user(db)

    nodes = [_make_node(db, f"n{i}", f"5.5.5.{i}") for i in range(1, 3)]
    node_based_host = _make_host(db, nodes=nodes, remark="node-based")

    db.add(ProxyInbound(tag="static-tag"))
    db.commit()
    static_host = ProxyHost(remark="static-legacy", address="static.example.com", inbound_tag="static-tag")
    db.add(static_host)
    db.commit()
    _grant_inbound_access(monkeypatch, db, user, [node_based_host, static_host])

    result = list_pinnable_hosts(db, user)
    host_ids = {h.host_id for h in result}

    assert node_based_host.id in host_ids
    assert static_host.id not in host_ids


def test_pinnable_hosts_returns_full_node_set_not_a_subset(db, monkeypatch):
    """Список нод локации — полный состав хоста, а не подмножество, которое
    когда-либо выбрал автовыбор/пин: форма закрепления обязана предлагать
    выбор из ВСЕХ нод хоста."""
    user = _make_user(db)
    nodes = [_make_node(db, f"n{i}", f"4.4.4.{i}") for i in range(1, 6)]
    host = _make_host(db, nodes=nodes, remark="five-nodes")
    _grant_inbound_access(monkeypatch, db, user, [host])

    result = list_pinnable_hosts(db, user)

    assert len(result) == 1
    assert result[0].host_id == host.id
    assert {n.node_id for n in result[0].nodes} == {n.id for n in nodes}
    assert {n.name for n in result[0].nodes} == {n.name for n in nodes}


def test_pinnable_hosts_excludes_disabled_nodes(db, monkeypatch):
    """I2 (финальное ревью, NPVPN-2072): форма закрепления не должна предлагать
    disabled-ноду — в живую выдачу такая нода не попадает (_visible_nodes,
    app/xray/host_addresses.py), пин на неё создался бы, прошёл валидацию и
    молча не работал бы (AddressContext.pick пересекает пин с фактическим
    составом, где disabled-ноды нет — пересечение пустое)."""
    from app.models.node import NodeStatus

    user = _make_user(db)
    live_node = _make_node(db, "live", "4.4.4.1")
    disabled_node = _make_node(db, "disabled", "4.4.4.2")
    disabled_node.status = NodeStatus.disabled
    db.commit()
    host = _make_host(db, nodes=[live_node, disabled_node], remark="mixed")
    _grant_inbound_access(monkeypatch, db, user, [host])

    result = list_pinnable_hosts(db, user)

    assert len(result) == 1
    assert {n.node_id for n in result[0].nodes} == {live_node.id}


def test_pinnable_hosts_excludes_hosts_outside_users_inbounds(db, monkeypatch):
    """Не предлагать для закрепления недоступные юзеру локации (дополнение к
    C2, финальное ревью, NPVPN-2072): юзер с excluded_inbounds, исключающими
    тег локации, не должен увидеть её в форме создания закрепления. Иначе
    саппорт создал бы пин, получил 200, увидел его во вкладке «Закрепления»
    как действующий — а в подписке этой локации нет вовсе, пин не применится
    никогда. Тот же по сути дефект, что чинили по I2 для disabled-нод, только
    уровнем выше: там отсекалась нода, здесь — целая локация."""
    user = _make_user(db)
    nodes_visible = [_make_node(db, f"v{i}", f"5.5.5.{i}") for i in range(1, 3)]
    host_visible = _make_host(db, nodes=nodes_visible, remark="visible")
    nodes_excluded = [_make_node(db, f"e{i}", f"4.4.4.{i}") for i in range(1, 3)]
    host_excluded = _make_host(db, nodes=nodes_excluded, remark="excluded")

    # Оба тега зарегистрированы в xray.config, но host_excluded попадает в
    # excluded_inbounds прокси юзера.
    _grant_inbound_access(monkeypatch, db, user, [host_visible, host_excluded])
    proxy = db.query(Proxy).filter(Proxy.user_id == user.id).one()
    excluded_inbound = db.query(ProxyInbound).filter(ProxyInbound.tag == host_excluded.inbound_tag).one()
    proxy.excluded_inbounds = [excluded_inbound]
    db.commit()

    result = list_pinnable_hosts(db, user)
    host_ids = {h.host_id for h in result}

    assert host_visible.id in host_ids
    assert host_excluded.id not in host_ids


def test_exhausted_node_is_excluded_from_reconstructed_day(db, monkeypatch):
    """Порог исчерпания виден и в журнале: за те сутки ноды, добравшей лимит, у юзера не было.

    Свежего расхода за прошедший день у нас нет, поэтому исчерпание выводится из снимка
    весов: вес — это остаток лимита, значит «остаток ≤ 10% лимита» равносильно «расход
    достиг 90%» (см. exhausted_from_snapshot).
    """
    user = _make_user(db)
    nodes = [_make_node(db, f"n{i}", f"1.2.3.{i}") for i in range(1, 5)]
    for node in nodes:
        node.hosting_traffic_limit_bytes = 1000
    db.commit()
    host = _make_host(db, nodes=nodes)
    _grant_inbound_access(monkeypatch, db, user, [host])

    write_host_composition_snapshot(db, DAY, host.id, [{"node_id": n.id, "address": n.address} for n in nodes])
    # Две первые ноды выбрали 90% и больше (остаток 100 и 0 при лимите 1000), две другие целы.
    for node, weight in zip(nodes, [100.0, 0.0, 900.0, 800.0], strict=True):
        db.add(NodeWeightSnapshot(epoch_index=DAY, node_id=node.id, weight=weight))
    db.commit()

    assignment = reconstruct(db, USER_ID, DAY)[0]

    assert assignment.source == "auto"
    assert assignment.restorable is True
    assert set(assignment.node_ids) == {nodes[2].id, nodes[3].id}


def test_reconstruct_matches_live_pick_with_exhaustion(db, monkeypatch):
    """Журнал и живая выдача обязаны считать одно и то же — формула у них общая."""
    from app.subscription.address_context import AddressContext, HostSubsetSettings

    user = _make_user(db)
    nodes = [_make_node(db, f"n{i}", f"1.2.3.{i}") for i in range(1, 6)]
    for node in nodes:
        node.hosting_traffic_limit_bytes = 1000
    db.commit()
    host = _make_host(db, nodes=nodes)
    _grant_inbound_access(monkeypatch, db, user, [host])

    write_host_composition_snapshot(db, DAY, host.id, [{"node_id": n.id, "address": n.address} for n in nodes])
    weights = {nodes[0].id: 50.0, nodes[1].id: 900.0, nodes[2].id: 700.0, nodes[3].id: 300.0, nodes[4].id: 20.0}
    for node_id, weight in weights.items():
        db.add(NodeWeightSnapshot(epoch_index=DAY, node_id=node_id, weight=weight))
    db.commit()

    from_history = reconstruct(db, USER_ID, DAY)[0]

    live = AddressContext(
        user_id=USER_ID,
        day_index=DAY,
        weights_by_day={DAY: weights},
        # Ноды 1 и 5 добрали больше 90% лимита — ровно те, что даёт exhausted_from_snapshot.
        exhausted=frozenset({nodes[0].id, nodes[4].id}),
        enabled=True,
    ).pick(
        [n.address for n in nodes],
        [n.id for n in nodes],
        addresses_from_nodes=True,
        host_id=host.id,
        settings=HostSubsetSettings(enabled=True, size=2, rotation_days=1),
    )

    assert from_history.addresses == live


def test_per_host_size_is_reconstructed_per_host(db, monkeypatch):
    """Два хоста на одном парке нод с разными размерами — журнал показывает разные наборы."""
    user = _make_user(db)
    nodes = [_make_node(db, f"n{i}", f"1.2.3.{i}") for i in range(1, 5)]
    two = _make_host(db, nodes=nodes, remark="two", subset_size=2)
    three = _make_host(db, nodes=nodes, remark="three", subset_size=3)
    _grant_inbound_access(monkeypatch, db, user, [two, three])

    payload = [{"node_id": n.id, "address": n.address} for n in nodes]
    for host in (two, three):
        write_host_composition_snapshot(db, DAY, host.id, payload)
    for node in nodes:
        db.add(NodeWeightSnapshot(epoch_index=DAY, node_id=node.id, weight=100.0))
    db.commit()

    by_remark = {a.remark: a for a in reconstruct(db, USER_ID, DAY)}

    assert len(by_remark["two"].node_ids) == 2
    assert len(by_remark["three"].node_ids) == 3


def test_range_matches_per_day_reconstruction(db, monkeypatch):
    """Диапазонный журнал обязан совпадать с поденным: оптимизация не меняет ответ."""
    user = _make_user(db)
    nodes = [_make_node(db, f"n{i}", f"1.2.3.{i}") for i in range(1, 5)]
    for node in nodes:
        node.hosting_traffic_limit_bytes = 1000
    db.commit()
    host = _make_host(db, nodes=nodes)
    _grant_inbound_access(monkeypatch, db, user, [host])

    payload = [{"node_id": n.id, "address": n.address} for n in nodes]
    # Снимок состава есть не за все сутки, веса — тоже: в ответе должны оказаться и
    # восстановимые дни, и "unknown".
    for day in (DAY - 3, DAY - 1, DAY):
        write_host_composition_snapshot(db, day, host.id, payload)
    for day in (DAY - 1, DAY):
        for node, weight in zip(nodes, [100.0, 0.0, 900.0, 800.0], strict=True):
            db.add(NodeWeightSnapshot(epoch_index=day, node_id=node.id, weight=weight))
    db.commit()

    by_day = reconstruct_range(db, USER_ID, DAY - 4, DAY)

    assert sorted(by_day) == list(range(DAY - 4, DAY + 1))
    for day, assignments in by_day.items():
        expected = reconstruct(db, USER_ID, day)
        assert [a.model_dump() for a in assignments] == [a.model_dump() for a in expected], f"день {day}"


def test_range_does_not_scale_queries_with_days(db, monkeypatch):
    """Главное свойство правки: число запросов не растёт вместе с длиной диапазона.

    Раньше каждые сутки стоили отдельного чтения юзера, хостов, пинов, снимка и
    лимитов — при 90 днях это сотни последовательных запросов внутри обработчика.
    """
    from sqlalchemy import event

    user = _make_user(db)
    nodes = [_make_node(db, f"n{i}", f"1.2.3.{i}") for i in range(1, 5)]
    host = _make_host(db, nodes=nodes)
    _grant_inbound_access(monkeypatch, db, user, [host])
    write_host_composition_snapshot(db, DAY, host.id, [{"node_id": n.id, "address": n.address} for n in nodes])
    db.commit()

    counter = {"n": 0}

    def count(*args, **kwargs):
        counter["n"] += 1

    def measure(first_day: int) -> int:
        # expunge_all — чтобы ленивые подгрузки relationship (hosts.bots/nodes) повторялись
        # одинаково в обоих замерах: иначе второй вызов выигрывал бы за счёт identity map
        # сессии, а не за счёт самой правки.
        db.expunge_all()
        counter["n"] = 0
        reconstruct_range(db, USER_ID, first_day, DAY)
        return counter["n"]

    event.listen(db.bind, "before_cursor_execute", count)
    try:
        week = measure(DAY - 6)
        quarter = measure(DAY - 89)
    finally:
        event.remove(db.bind, "before_cursor_execute", count)

    assert week == quarter, f"запросы выросли с длиной диапазона: {week} -> {quarter}"
    assert quarter <= 10, f"слишком много запросов на диапазон: {quarter}"
