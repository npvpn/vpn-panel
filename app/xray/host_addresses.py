from app.models.node import NodeStatus


def visible_nodes(host) -> list:
    """Ноды хоста, которые он реально «представляет» клиенту.

    Инвариант: адреса (resolve_host_addresses) и node_ids (resolve_host_node_ids)
    строятся по ОДНОМУ И ТОМУ ЖЕ множеству нод — иначе БС-признак/БС-блокировка
    хоста могут относиться к ноде, чей адрес в подписку уже не попадает.

    - статический host.address (в т.ч. домен-маскировка) → хост отдаёт этот адрес
      всегда, за ним стоят ВСЕ привязанные ноды, включая disabled: disabled в панели
      не значит, что сервер физически выключен, и БС-лимит по такой ноде обходить
      нельзя;
    - пустой host.address → адреса собираются от нод, disabled из них исключены
      (удалённые ноды уже выпали из связи через FK CASCADE), поэтому и node_ids
      считаем только по живым.

    Публичная (без ведущего "_"): переиспользуется за пределами этого файла —
    app/services/address_history.py и app/routers/user.py (список нод локации
    для формы закрепления и валидация /pins, NPVPN-2072) должны видеть тот же
    набор нод, что и рендер подписки, а не отдельно собранную копию.
    """
    if host.address:
        return list(host.nodes)
    return [node for node in host.nodes if node.status != NodeStatus.disabled]


def resolve_host_addresses(host) -> list[str]:
    """Адреса хоста для подписки.

    Приоритет у статического host.address (обратная совместимость). Если он
    пуст — собираем Node.address связанных нод (см. visible_nodes).
    """
    if host.address:
        return [i.strip() for i in host.address.split(",")]
    return [node.address for node in visible_nodes(host)]


def resolve_host_node_ids(host) -> list[int]:
    """Ноды хоста, по которым определяется его БС-признак и БС-блокировки (NPVPN-1652).

    Согласовано с resolve_host_addresses: см. инвариант в visible_nodes.
    """
    return [node.id for node in visible_nodes(host)]


def host_has_bs_node(host) -> bool:
    """Хост — БС, если среди видимых нод есть хотя бы одна с is_bs.

    То же множество, что у адресов и node_ids: суффикс расхода в имени не должен
    появляться у хоста, чья БС-нода клиенту уже не отдаётся.
    """
    return any(node.is_bs for node in visible_nodes(host))


def host_allowed_for_bot(visibility: str, bot_usernames: list[str], user_bot_username: str | None) -> bool:
    """Хост доступен этому юзеру по видимости хоста и привязке к боту.

    NPVPN-2044: видимость читается из колонки `hosts.visibility`, а не выводится
    из пустого списка привязок. Прежний фолбэк «пустой bot_usernames значит всем»
    убран: пока он жив, выбор хостов партнёром не значит ничего — партнёр и так
    получает всё непривязанное, и тарифицировать аренду нечем.

    `shared` старше привязки: хост, объявленный общим, виден всем ботам панели
    независимо от того, привязан ли к нему кто-то вручную.

    Единый предикат для ТРЁХ вызывающих (NPVPN-2072, I4): рендера подписки
    (`app/subscription/share.py`), восстановления истории (`reconstruct`) и
    списка локаций для формы закрепления (`list_pinnable_hosts`) — оба сервиса
    журнала живут в `app/services/address_history.py`. Предикат нарочно лежит в
    этом листовом модуле (без pydantic/crud/БД), а не в address_history.py: именно
    разъезд копий этого условия по share.py и остальным местам дал Critical-
    находку раньше в этой фиче — share.py горячий путь подписки и не должен
    тянуть за собой тяжёлый сервисный слой ради одной проверки. Поэтому
    видимость приходит ПАРАМЕТРОМ, а модуль не начинает ходить в БД, и значение
    "shared" остаётся здесь литералом (импорт константы вернул бы зависимость
    от app.db.models) — литерал закреплён тестом.
    """
    if visibility == "shared":
        return True
    return bool(user_bot_username) and user_bot_username in bot_usernames
