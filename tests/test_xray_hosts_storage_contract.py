"""Контракт storage-словаря хоста, который строит app/xray/__init__.py::hosts().

BsContext._matches (app/subscription/bs_context.py) читает host.get("node_ids") or ().
Функцию hosts() нельзя выполнить в песочнице напрямую — она тянет GetDB/crud (БД,
рантайм xray), поэтому контракт проверяется по AST исходника: в dict-литерале хоста
должен быть ключ "node_ids", и в него должен класться результат резолвера
resolve_host_node_ids(host) из app/xray/host_addresses.py — того самого, который
согласован с resolve_host_addresses (NPVPN-1652). Если ключ пропадёт/переименуется
или в него положат другое значение (например, host.node_ids — ВСЕ ноды, включая
disabled, чьих адресов в подписке уже нет), БС-логика (заглушки лимита) молча
разъедется с адресами хоста, а обычные тесты
BsContext/subscription (которые строят словари хостов руками, не через hosts())
этого не заметят — этот тест ловит именно такой разрыв.

Тем же способом проверяется ключ "routing_profile_id" (NPVPN-2024): клиентский routing
выбирается по профилю ХОСТА, и этот словарь — единственный стык между колонкой
hosts.routing_profile_id и рендером подписки. Если ключ пропадёт,
host.get("routing_profile_id") вернёт None и ВСЕ хосты молча уедут на документ
`default` — тесты рендера строят словари хостов руками и этого не увидят.
"""

from __future__ import annotations

import ast
import pathlib

_SOURCE_PATH = pathlib.Path(__file__).parent.parent / "app" / "xray" / "__init__.py"

# Ключи, по которым узнаём именно словарь хоста среди любых других dict-литералов
# внутри hosts() (тест не должен ломаться от появления посторонних словарей).
_HOST_DICT_MARKER_KEYS = {"remark", "address", "port"}


def _dict_keys(node: ast.Dict) -> set[str]:
    return {key.value for key in node.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)}


def _host_dict_literal() -> ast.Dict:
    tree = ast.parse(_SOURCE_PATH.read_text())
    hosts_func = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "hosts")
    host_dicts = [
        node
        for node in ast.walk(hosts_func)
        if isinstance(node, ast.Dict) and _HOST_DICT_MARKER_KEYS <= _dict_keys(node)
    ]
    assert len(host_dicts) == 1, (
        "ожидался ровно один dict-литерал хоста (с ключами remark/address/port) внутри "
        "hosts() — структура функции изменилась, проверь тест вручную"
    )
    return host_dicts[0]


def _value_for_key(host_dict: ast.Dict, key: str) -> ast.expr:
    for key_node, value_node in zip(host_dict.keys, host_dict.values, strict=True):
        if isinstance(key_node, ast.Constant) and key_node.value == key:
            return value_node
    raise AssertionError(f'ключ "{key}" пропал из dict-литерала хоста в app/xray/__init__.py::hosts()')


def test_hosts_storage_dict_has_node_ids_key():
    """В storage-словаре хоста есть ключ "node_ids" — единственный источник БС-признака."""
    assert "node_ids" in _dict_keys(_host_dict_literal())


def test_hosts_storage_node_ids_value_comes_from_resolver():
    """В "node_ids" кладётся именно resolve_host_node_ids(host), а не host.node_ids.

    host.node_ids (проперти модели) — ВСЕ привязанные ноды, включая disabled; адреса же
    (resolve_host_addresses) при пустом host.address disabled-ноды исключают. Подмена
    значения обратно на host.node_ids снова разведёт эти множества — тест краснеет.
    """
    value = _value_for_key(_host_dict_literal(), "node_ids")

    assert isinstance(value, ast.Call), 'значение "node_ids" должно быть вызовом резолвера'
    assert isinstance(value.func, ast.Name) and value.func.id == "resolve_host_node_ids", (
        'значение "node_ids" должно строиться через resolve_host_node_ids() из app/xray/host_addresses.py'
    )
    assert [arg.id for arg in value.args if isinstance(arg, ast.Name)] == ["host"], (
        "resolve_host_node_ids должен вызываться от хоста текущей итерации"
    )


def test_hosts_storage_address_and_node_ids_share_the_same_host():
    """Адрес и node_ids резолвятся от ОДНОГО и того же host (инвариант согласованности)."""
    host_dict = _host_dict_literal()
    address = _value_for_key(host_dict, "address")

    assert isinstance(address, ast.Call) and isinstance(address.func, ast.Name)
    assert address.func.id == "resolve_host_addresses"
    assert [arg.id for arg in address.args if isinstance(arg, ast.Name)] == ["host"]


def test_hosts_storage_dict_has_routing_profile_id_key():
    """В storage-словаре хоста есть ключ "routing_profile_id" — единственный источник
    профиля клиентского routing для рендера подписки (share.py читает его с хоста)."""
    assert "routing_profile_id" in _dict_keys(_host_dict_literal())


def test_hosts_storage_routing_profile_id_comes_from_the_host_column():
    """В "routing_profile_id" кладётся именно host.routing_profile_id.

    Профиль живёт на ХОСТЕ, а не на ноде (NPVPN-2024): подмена значения на что-то
    производное от нод вернула бы первый, отменённый подход — тест краснеет.
    """
    value = _value_for_key(_host_dict_literal(), "routing_profile_id")

    assert isinstance(value, ast.Attribute) and value.attr == "routing_profile_id", (
        'значение "routing_profile_id" должно быть атрибутом routing_profile_id'
    )
    assert isinstance(value.value, ast.Name) and value.value.id == "host", (
        "routing_profile_id должен читаться с хоста текущей итерации (host.routing_profile_id)"
    )
