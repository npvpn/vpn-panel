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


def host_allowed_for_bot(bot_usernames: list[str], user_bot_username: str | None) -> bool:
    """Хост доступен этому юзеру, если привязан к его боту.

    NPVPN-2044: единственное правило — «виден тому, кому привязан». Прежний
    фолбэк «пустой bot_usernames значит всем» убран, и колонка видимости тоже:
    флаг `shared` был тем же костылём под другим именем — помеченный им хост
    продолжал автоматически уезжать каждому новому боту, то есть ровно то
    поведение, от которого уходили. Пустая привязка теперь значит «никому».

    Единый предикат для ТРЁХ вызывающих (NPVPN-2072, I4): рендера подписки
    (`app/subscription/share.py`), восстановления истории (`reconstruct`) и
    списка локаций для формы закрепления (`list_pinnable_hosts`) — оба сервиса
    журнала живут в `app/services/address_history.py`. Предикат нарочно лежит в
    этом листовом модуле (без pydantic/crud/БД): именно разъезд копий этого
    условия по share.py и остальным местам дал Critical-находку раньше в этой
    фиче, а share.py — горячий путь подписки и не должен тянуть сервисный слой.
    """
    return bool(user_bot_username) and user_bot_username in bot_usernames
