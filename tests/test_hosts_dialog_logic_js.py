"""Логика диалога хостов (NPVPN-2215): исполняем настоящие .ts-модули в Node.

- hostsFilter.selectVisibleHosts — какие хосты видны в списке. Баг: строка
  пропадала посреди правки, как только переставала подходить под поиск или
  «Только активные», и закрывала окно своих настроек.
- hostValues.isSameHostValues — изменён ли хост/форма: по нему ставится пометка
  «есть несохранённые изменения» и переспрашивается закрытие.

Node ≥ 22.18 снимает типы с .ts сам; обвязка tests/js/hosts_dialog_harness.mjs
без зависимостей.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_HARNESS = Path(__file__).parent / "js" / "hosts_dialog_harness.mjs"
_NODE = shutil.which("node")


def _node_strips_types() -> bool:
    if _NODE is None:
        return False
    proc = subprocess.run(
        [_NODE, "-p", "Boolean(process.features.typescript)"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return proc.stdout.strip() == "true"


pytestmark = pytest.mark.skipif(not _node_strips_types(), reason="нужен Node.js ≥ 22.18 (исполняет .ts без сборки)")

ALL = {"search": "", "inboundFilter": "", "activeOnly": False}


def _run(scenario: dict) -> dict:
    proc = subprocess.run(
        [_NODE, str(_HARNESS), json.dumps(scenario)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _visible(*steps: tuple[list[dict], dict]) -> list[list[int]]:
    """Шаги (хосты, фильтры) подряд; id строк — по позиции: r0, r1, …"""
    payload = [
        {"rowIds": [f"r{i}" for i in range(len(hosts))], "hosts": hosts, "filters": {**ALL, **filters}}
        for hosts, filters in steps
    ]
    return _run({"op": "visible", "steps": payload})["steps"]


def _host(remark: str = "", *, disabled: bool = False, inbound: str = "in", address: str = "") -> dict:
    return {"remark": remark, "address": address, "inbound_tag": inbound, "is_disabled": disabled}


def _same(a, b) -> bool:
    return _run({"op": "same", "a": a, "b": b})["same"]


# --- какие хосты видны -------------------------------------------------------


def test_filters_by_search_inbound_and_active():
    """Поиск — по remark и address без учёта регистра; инбаунд и активность — точно."""
    hosts = [
        _host("VPN Netherlands"),
        _host("Austria", address="vpn.example"),
        _host("VPN Off", disabled=True),
        _host("VPN Other", inbound="other"),
    ]
    assert _visible((hosts, {"search": "vpn"})) == [[0, 1, 2, 3]]
    assert _visible((hosts, {"search": "vpn", "activeOnly": True})) == [[0, 1, 3]]
    assert _visible((hosts, {"search": "vpn", "inboundFilter": "in"})) == [[0, 1, 2]]


def test_renamed_host_stays_visible_under_same_search():
    """Баг NPVPN-2215: «VPN x» → «VP x» при поиске «VPN» — строка не пропадает."""
    search = {"search": "VPN"}
    before = [_host("VPN x"), _host("Other")]
    after = [_host("VP x"), _host("Other")]
    assert _visible((before, search), (after, search)) == [[0], [0]]


def test_disabled_host_stays_visible_under_active_only():
    """Выключили хост при «Только активные» — строка остаётся до смены фильтра."""
    active = {"activeOnly": True}
    assert _visible(([_host("a")], active), ([_host("a", disabled=True)], active)) == [[0], [0]]


def test_changing_filters_drops_hosts_that_no_longer_match():
    """Новый поиск пересобирает список честно: переименованный хост уже не находится."""
    after = [_host("VP x")]
    assert _visible(
        ([_host("VPN x")], {"search": "VPN"}), (after, {"search": "VPN"}), (after, {"search": "VPN x"})
    ) == [
        [0],
        [0],
        [],
    ]


def test_search_whitespace_and_case_do_not_reset_shown_hosts():
    """Пробелы по краям и регистр поиска — тот же фильтр, показанные строки остаются."""
    after = [_host("VP x")]
    assert _visible(([_host("VPN x")], {"search": "vpn"}), (after, {"search": " VPN "})) == [[0], [0]]


def test_host_that_starts_matching_after_edit_appears():
    """Правка, после которой хост начал подходить, показывает его сразу."""
    search = {"search": "VPN"}
    assert _visible(([_host("x")], search), ([_host("VPN x")], search)) == [[], [0]]


def test_rows_are_tracked_by_id_not_position():
    """Строки опознаются по id, а не по позиции: вставка сверху не сбивает «показанных»."""
    search = {"search": "VPN"}
    first = _run(
        {
            "op": "visible",
            "steps": [
                {"rowIds": ["a"], "hosts": [_host("VPN a")], "filters": {**ALL, **search}},
                {"rowIds": ["a"], "hosts": [_host("VP a")], "filters": {**ALL, **search}},
                {"rowIds": ["new", "a"], "hosts": [_host("zzz"), _host("VP a")], "filters": {**ALL, **search}},
            ],
        }
    )["steps"]
    # «a» сдвинулась на позицию 1 и осталась видна; новая строка тоже видна.
    assert first == [[0], [0], [0, 1]]


def test_added_host_is_visible_even_if_it_does_not_match_search():
    """Только что добавленный/продублированный хост виден, хоть и не подходит под поиск.

    Иначе хост добавлялся, но в списке его не было — непонятно, добавился ли.
    """
    search = {"search": "VPN"}
    out = _run(
        {
            "op": "visible",
            "steps": [
                {"rowIds": ["a", "b"], "hosts": [_host("VPN a"), _host("Other")], "filters": {**ALL, **search}},
                {
                    "rowIds": ["new", "a", "b"],
                    "hosts": [_host("Austria"), _host("VPN a"), _host("Other")],
                    "filters": {**ALL, **search},
                },
            ],
        }
    )["steps"]
    assert out == [[0], [0, 1]]


def test_reloaded_list_is_filtered_from_scratch():
    """Список перезагружен (у всех строк новые id) — это не «добавленные», фильтр честный."""
    search = {"search": "VPN"}
    out = _run(
        {
            "op": "visible",
            "steps": [
                {"rowIds": ["a", "b"], "hosts": [_host("VPN a"), _host("Other")], "filters": {**ALL, **search}},
                {"rowIds": ["c", "d"], "hosts": [_host("VPN a"), _host("Other")], "filters": {**ALL, **search}},
            ],
        }
    )["steps"]
    assert out == [[0], [0]]


def test_first_load_after_empty_list_is_filtered():
    """Первая загрузка хостов в пустую форму — тоже не «добавление»."""
    search = {"search": "VPN"}
    out = _run(
        {
            "op": "visible",
            "steps": [
                {"rowIds": [], "hosts": [], "filters": {**ALL, **search}},
                {"rowIds": ["a", "b"], "hosts": [_host("VPN a"), _host("Other")], "filters": {**ALL, **search}},
            ],
        }
    )["steps"]
    assert out == [[], [0]]


# --- фильтры при ошибке валидации --------------------------------------------


def _reveal(hosts: list[dict], filters: dict) -> dict:
    return _run({"op": "filtersRevealingHosts", "args": [hosts, {**ALL, **filters}]})["result"]


def test_reveal_keeps_filters_when_invalid_hosts_are_visible():
    """Хост с ошибкой и так виден — фильтры пользователя не трогаем."""
    filters = {"search": "VPN", "inboundFilter": "in", "activeOnly": True}
    assert _reveal([_host("VPN a")], filters) == {**ALL, **filters}


def test_reveal_clears_search_hiding_invalid_host():
    """Баг из ревью: ошибка в хосте, скрытом поиском, — не видно ни строки, ни ошибки."""
    assert _reveal([_host("Other")], {"search": "VPN", "activeOnly": True}) == {**ALL, "activeOnly": True}


def test_reveal_clears_inbound_filter_hiding_invalid_host():
    """Хост с ошибкой в другом инбаунде — сбрасываем только фильтр инбаунда."""
    out = _reveal([_host("VPN a", inbound="other")], {"search": "VPN", "inboundFilter": "in"})
    assert out == {**ALL, "search": "VPN"}


def test_reveal_shows_disabled_invalid_host():
    """Хост с ошибкой выключен — снимаем «Только активные»."""
    assert _reveal([_host("a", disabled=True)], {"activeOnly": True}) == ALL


# --- порядок на вкладке «По ботам» ---------------------------------------------


def _bot_order(*steps: tuple[list[str], list[bool], str]) -> list[list[int]]:
    payload = [{"rowIds": ids, "isAvailable": avail, "key": key} for ids, avail, key in steps]
    return _run({"op": "botOrder", "steps": payload})["steps"]


def test_bot_tab_available_hosts_go_first_keeping_global_order():
    """Доступные боту — наверху, остальные ниже; внутри групп — общий порядок хостов."""
    ids = ["a", "b", "c", "d"]
    assert _bot_order((ids, [False, True, False, True], "bot1")) == [[1, 3, 0, 2]]


def test_bot_tab_toggle_does_not_move_row():
    """Щелчок переключателя не двигает строку — иначе она уезжает из-под курсора."""
    ids = ["a", "b"]
    assert _bot_order((ids, [False, True], "bot1"), (ids, [True, True], "bot1"), (ids, [False, False], "bot1")) == [
        [1, 0],
        [1, 0],
        [1, 0],
    ]


def test_bot_tab_order_is_refreshed_when_bot_or_filters_change():
    """Новый бот или фильтр — группы пересчитываются по текущему состоянию."""
    ids = ["a", "b"]
    assert _bot_order((ids, [False, True], "bot1"), (ids, [True, False], "bot1"), (ids, [True, False], "bot2")) == [
        [1, 0],
        [1, 0],
        [0, 1],
    ]


def test_bot_tab_added_row_is_grouped_by_current_state():
    """Добавленная строка встаёт в группу по текущей доступности, остальные не двигаются."""
    assert _bot_order(
        (["a", "b"], [False, True], "bot1"),
        (["new", "a", "b"], [True, True, True], "bot1"),
    ) == [[1, 0], [0, 2, 1]]


# --- выбор ботов в окне настроек хоста --------------------------------------


def _bindings(op: str, *args) -> list[str]:
    return _run({"op": op, "args": list(args)})["result"]


def test_select_all_adds_missing_bots_keeping_selected_order():
    """«Выбрать всех» добавляет недостающих в конец, уже выбранные не двигает и не дублирует."""
    assert _bindings("selectAllBots", ["b"], ["a", "b", "c"]) == ["b", "a", "c"]


def test_select_all_with_search_adds_only_found_bots():
    """При поиске «Выбрать всех» берёт только найденных — остальные не трогает."""
    assert _bindings("selectAllBots", [], ["partner1", "partner2"]) == ["partner1", "partner2"]


def test_unbinding_bot_drops_its_rental():
    """Баг: снятый в окне настроек бот оставался в аренде → сервер отвечал 400 при сохранении."""
    assert _bindings("withoutUnboundRentals", ["a", "b"], ["a"]) == ["a"]


def test_clearing_bots_drops_all_rentals():
    """«Очистить выбор» снимает и всю аренду."""
    assert _bindings("withoutUnboundRentals", ["a", "b"], []) == []


# --- изменён ли хост ---------------------------------------------------------


def test_same_values_with_input_noise_are_equal():
    """Число и строка, "" и null/отсутствие поля, порядок ботов — не изменения."""
    a = {"port": 443, "sni": None, "bot_usernames": ["b", "a"], "remark": "x"}
    b = {"port": "443", "sni": "", "bot_usernames": ["a", "b"], "remark": "x", "path": ""}
    assert _same(a, b) is True


def test_real_changes_are_detected():
    """Настоящие правки замечаются: текст, флаг, состав ботов."""
    base = {"remark": "x", "is_disabled": False, "bot_usernames": ["a"]}
    assert _same(base, {**base, "remark": "y"}) is False
    assert _same(base, {**base, "is_disabled": True}) is False
    assert _same(base, {**base, "bot_usernames": ["a", "b"]}) is False


def test_false_is_not_treated_as_empty():
    """Выключенный флаг — значение, а не пустота: false ≠ отсутствующему полю."""
    assert _same({"allowinsecure": False}, {}) is False


def test_host_order_in_list_matters():
    """Порядок хостов значим (это порядок выдачи) — перестановка = изменение."""
    a, b = {"remark": "a"}, {"remark": "b"}
    assert _same([a, b], [a, b]) is True
    assert _same([a, b], [b, a]) is False


@pytest.mark.parametrize("network", ["tcp", "grpc", "ws"])
def test_inbound_change_keeps_host_identity_and_clears_xhttp_extra(network):
    """Смена транспорта меняет только inbound и очищает несовместимый Extra."""
    host = {
        "host_id": 12,
        "inbound_tag": "OLD",
        "order": 7,
        "remark": "Austria",
        "port": 443,
        "sni": "edge.example",
        "node_ids": [3],
        "bot_usernames": ["a"],
        "rented_bot_usernames": ["a"],
        "xhttp_extra": '{"headers":{"X-Test":"value"}}',
    }
    result = _run({"op": "changeInbound", "host": host, "tag": "NEW", "network": network})
    assert result["host"] == {**host, "inbound_tag": "NEW", "xhttp_extra": ""}
    assert result["original"] == host


@pytest.mark.parametrize("network", ["xhttp", "splithttp"])
def test_inbound_change_between_xhttp_inbounds_keeps_extra(network):
    """XHTTP-совместимые inbound сохраняют Extra без скрытого сброса."""
    host = {"inbound_tag": "OLD", "xhttp_extra": '{"mode":"auto"}'}
    result = _run({"op": "changeInbound", "host": host, "tag": "NEW", "network": network})
    assert result["host"] == {**host, "inbound_tag": "NEW"}


def test_returning_to_xhttp_does_not_restore_cleared_extra():
    """Переход обратно не восстанавливает Extra из скрытого старого черновика."""
    host = {"host_id": 12, "inbound_tag": "XHTTP", "xhttp_extra": '{"mode":"auto"}'}
    moved = _run({"op": "changeInbound", "host": host, "tag": "TCP", "network": "tcp"})["host"]
    restored = _run({"op": "changeInbound", "host": moved, "tag": "XHTTP", "network": "xhttp"})["host"]
    assert restored == {"host_id": 12, "inbound_tag": "XHTTP", "xhttp_extra": ""}


def test_changed_inbound_stays_visible_under_original_filter():
    """Селект не убирает редактируемую строку из-под курсора при активном фильтре."""
    assert _visible(
        ([_host(inbound="OLD")], {"inboundFilter": "OLD"}), ([_host(inbound="NEW")], {"inboundFilter": "OLD"})
    ) == [[0], [0]]
