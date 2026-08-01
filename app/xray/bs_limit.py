"""Чистые функции для по-нодного лимита БС-нод (NPVPN-1456).

Без зависимостей от БД/окружения — тестируются как cascade_config/inbound_filter.
"""


def period_keys(now):
    """Маркер месяца счётчика 'YYYY-MM' — ленивый сброс при смене месяца."""
    return now.strftime("%Y-%m")


def bs_counter_step(existing, delta, yyyymm):
    """Новые значения счётчика с ленивым сбросом месяца.

    existing — dict с ключами monthly_used/monthly_period либо None (строки ещё нет).
    """
    existing = existing or {}
    monthly_base = existing.get("monthly_used", 0) if existing.get("monthly_period") == yyyymm else 0
    return {
        "monthly_used": monthly_base + delta,
        "monthly_period": yyyymm,
    }


def diff_blocks(desired, current):
    """desired/current — множества (node_id, user_id). → (to_block, to_unblock)."""
    return desired - current, current - desired


def aggregate_bs_usage(rows, yyyymm):
    """rows: iterable of dict(user_id, monthly_used, monthly_period).
    → {user_id: monthly_used}, считая только актуальный месяц."""
    totals = {}
    for r in rows:
        if r.get("monthly_period") != yyyymm:
            continue
        uid = r["user_id"]
        totals[uid] = totals.get(uid, 0) + (r.get("monthly_used") or 0)
    return totals


def over_limit(monthly_used, monthly_limit):
    """True, если превышен заданный (>0) месячный лимит. 0/None = лимит не задан."""
    if monthly_limit and monthly_used >= monthly_limit:
        return True
    return False


def monthly_extra_overflow(monthly_used, monthly_limit):
    """Сколько месячного расхода сверх базового monthly_limit (идёт из купленного пула)."""
    if not monthly_limit:
        return 0
    return max(0, int(monthly_used) - int(monthly_limit))


def monthly_extra_consume_delta(old_monthly_used, new_monthly_used, monthly_limit):
    """Прирост списания из пула bs_extra при обновлении агрегата monthly_used."""
    return monthly_extra_overflow(new_monthly_used, monthly_limit) - monthly_extra_overflow(
        old_monthly_used, monthly_limit
    )


def monthly_effective_limit(monthly_limit, bs_extra_remaining):
    """Месячный потолок: база + остаток купленного пула."""
    if not monthly_limit:
        return 0
    return int(monthly_limit) + int(bs_extra_remaining or 0)


def carry_over_pool(pool, prev_used, monthly_limit):
    """Пул, переносимый на новый месяц: из купленного вычитается расход сверх базы.

    Сгорает только потраченное — неизрасходованная часть пула живёт дальше.
    monthly_limit == 0 (лимит не задан) → пул не трогаем.
    """
    if not monthly_limit:
        return int(pool or 0)
    return max(0, int(pool or 0) - max(0, int(prev_used) - int(monthly_limit)))


def over_limit_monthly_pool(monthly_used, monthly_limit, bs_extra_remaining):
    """Блок: месячный лимит+пул исчерпаны."""
    if not monthly_limit:
        return False
    return int(monthly_used) >= monthly_effective_limit(monthly_limit, bs_extra_remaining)


def pick_bs_bar(monthly_used, monthly_limit_eff):
    """(used, total) для месячного лимита; None, если лимит не задан."""
    if not monthly_limit_eff:
        return None
    return monthly_used, monthly_limit_eff


def bs_stub_remark(text_list):
    """Имя сервера-заглушки БС-лимита из настройки sub_bs_limit_server_text.

    БС-хост заменяется заглушкой НА СВОЁМ МЕСТЕ (один хост → одна заглушка),
    поэтому многострочный текст склеивается в одно имя сервера. Пустые строки
    отбрасываются. Принимает список строк, одну строку или None.
    """
    if not text_list:
        return ""
    lines = [text_list] if isinstance(text_list, str) else list(text_list)
    parts = [str(x).strip() for x in lines]
    return " ".join(p for p in parts if p)


def strip_blocked_clients(config, blocked_user_ids):
    """Копия config без клиентов заблокированных user_id во всех инбаундах.

    Матчинг по префиксу email '<uid>.' (email клиента = '<user_id>.<username>').
    Пустой набор → исходный объект без копирования (no-op). Затронутые инбаунды
    пересобираются новыми dict, поэтому функция корректна даже при поверхностном
    config.copy() и не мутирует вход.
    """
    if not blocked_user_ids:
        return config
    cfg = config.copy()
    prefixes = tuple(f"{uid}." for uid in blocked_user_ids)
    new_inbounds = []
    for inbound in cfg["inbounds"]:
        settings = inbound.get("settings")
        clients = settings.get("clients") if settings else None
        if not clients:
            new_inbounds.append(inbound)
            continue
        new_settings = dict(settings)
        new_settings["clients"] = [c for c in clients if not str(c.get("email", "")).startswith(prefixes)]
        new_inbound = dict(inbound)
        new_inbound["settings"] = new_settings
        new_inbounds.append(new_inbound)
    cfg["inbounds"] = new_inbounds
    return cfg
