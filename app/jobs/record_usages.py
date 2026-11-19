from collections import defaultdict
from datetime import date, datetime, timedelta
from operator import attrgetter
from typing import Any

from pymysql.err import OperationalError
from sqlalchemy import and_, bindparam, insert, select, text, update
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from sqlalchemy.sql.dml import Insert

from app import logger, scheduler, xray
from app.db import GetDB, crud
from app.db.models import Admin, BotBsDaily, Node, NodeUsage, NodeUserBsUsage, NodeUserUsage, System, User
from app.models.node import NodeStatus
from app.utils.concurrency import get_usage_executor
from app.utils.usage_runtime import StaleObservationError, completed_results, ready_apis, usage_state
from app.xray.bs_limit import bs_counter_step, period_keys
from config import (
    DISABLE_RECORDING_NODE_USAGE,
    DISABLE_RECORDING_NODE_USER_USAGE,
    JOB_CLEANUP_NODE_USER_USAGE_INTERVAL,
    JOB_RECORD_NODE_USAGES_INTERVAL,
    JOB_RECORD_USER_USAGES_INTERVAL,
    NODE_USER_USAGE_CLEANUP_BATCH_SIZE,
    NODE_USER_USAGE_RETENTION_DAYS,
    XRAY_THREAD_POOL_SIZE,
)
from xray_api import XRay as XRayAPI

usage_state.configure(
    periods={"user": JOB_RECORD_USER_USAGES_INTERVAL, "node": JOB_RECORD_NODE_USAGES_INTERVAL},
    workers=XRAY_THREAD_POOL_SIZE,
)


def safe_execute(db: Session, stmt, params=None):
    if db.bind.name == "mysql":
        if isinstance(stmt, Insert):
            stmt = stmt.prefix_with("IGNORE")

        tries = 0
        done = False
        while not done:
            try:
                db.connection().execute(stmt, params)
                db.commit()
                done = True
            except OperationalError as err:
                # 1213 — deadlock, 1205 — lock wait timeout. Оба транзиентны,
                # ретраим, иначе джоб падает и статистика тика теряется.
                if err.args[0] in (1213, 1205) and tries < 3:
                    db.rollback()
                    tries += 1
                    continue
                raise err

    else:
        db.connection().execute(stmt, params)
        db.commit()


def record_user_stats(params: list, node_id: int | None, consumption_factor: int = 1):
    if not params:
        return

    now = datetime.utcnow()
    created_at = datetime.fromisoformat(now.strftime("%Y-%m-%dT%H:00:00"))

    with GetDB() as db:
        # make user usage row if doesn't exist
        select_stmt = select(NodeUserUsage.user_id).where(
            and_(NodeUserUsage.node_id == node_id, NodeUserUsage.created_at == created_at)
        )
        existings = [r[0] for r in db.execute(select_stmt).fetchall()]
        uids_to_insert = set()

        for p in params:
            uid = int(p["uid"])
            if uid in existings:
                continue
            uids_to_insert.add(uid)

        if uids_to_insert:
            stmt = insert(NodeUserUsage).values(
                user_id=bindparam("uid"),
                created_at=created_at,
                node_id=node_id,
                used_traffic=0,
                last_seen_at=now,
            )
            safe_execute(db, stmt, [{"uid": uid} for uid in uids_to_insert])

        # record
        stmt = (
            update(NodeUserUsage)
            .values(
                used_traffic=NodeUserUsage.used_traffic + bindparam("value") * consumption_factor,
                # Тот же UPDATE, что уже идёт каждый тик — дополнительных запросов к БД нет.
                last_seen_at=now,
            )
            .where(
                and_(
                    NodeUserUsage.user_id == bindparam("uid"),
                    NodeUserUsage.node_id == node_id,
                    NodeUserUsage.created_at == created_at,
                )
            )
        )
        safe_execute(db, stmt, params)


def record_bot_bs_daily(db, node_id: int, deltas: dict[int, int], day: date, billable: bool = True) -> None:
    """Складывает дельты БС-трафика в суточный агрегат по ботам (NPVPN-2044).

    Вызывается из record_bs_user_stats — единственного места, где дельта уже
    посчитана, коэффициент ноды применён, а нода гарантированно БС (вызов стоит
    под `if node_id in bs_node_ids`, и node_id=None туда не попадает).

    billable — приходит от вызывающего готовым (по Node.owner_bot_id ноды
    node_id), а не высчитывается здесь отдельным запросом: джоба тикает раз в
    10 секунд по каждой БС-ноде, лишний SELECT на горячем пути не нужен
    (NPVPN-2044.1). Применяется ТОЛЬКО при вставке новой строки: при конфликте
    (повторный тик того же бота/ноды/дня) billable не трогаем — классификация
    замораживается в момент первой записи строки за сутки и не должна задним
    числом меняться, если владелец ноды сменится в тот же день.

    Не коммитит: должна лечь той же транзакцией, что инкремент node_user_bs_usage.
    """
    if not deltas:
        return

    bot_by_user = dict(
        db.query(User.id, User.bot_id).filter(User.id.in_(list(deltas.keys())), User.bot_id.isnot(None)).all()
    )
    if not bot_by_user:
        return

    per_bot: dict[int, int] = {}
    for uid, delta in deltas.items():
        bot_id = bot_by_user.get(uid)
        if bot_id is None:
            continue
        per_bot[bot_id] = per_bot.get(bot_id, 0) + int(delta)

    # Один bulk-UPSERT на все боты ноды, а не оператор на бота: джоба тикает
    # каждые 10 секунд по каждой БС-ноде, и на одной ноде сидят юзеры многих
    # ботов — поштучная запись превратила бы единицы запросов в сотни на горячем
    # пути панели (у неё уже была беда с нагрузкой, NPVPN-1170).
    rows = [
        {"bot_id": bot_id, "node_id": node_id, "day": day, "used_bytes": used, "billable": billable}
        for bot_id, used in per_bot.items()
    ]
    # Any, потому что диалектные Insert у mysql и sqlite — разные типы;
    # тот же приём, что в app/db/crud.py:write_host_composition_snapshot.
    stmt: Any
    if db.bind is not None and db.bind.dialect.name == "mysql":
        mysql_stmt = mysql_insert(BotBsDaily).values(rows)
        stmt = mysql_stmt.on_duplicate_key_update(used_bytes=BotBsDaily.used_bytes + mysql_stmt.inserted.used_bytes)
    else:
        sqlite_stmt = sqlite_insert(BotBsDaily).values(rows)
        stmt = sqlite_stmt.on_conflict_do_update(
            index_elements=["bot_id", "node_id", "day"],
            set_={"used_bytes": BotBsDaily.used_bytes + sqlite_stmt.excluded.used_bytes},
        )
    db.execute(stmt)


def record_bs_user_stats(params: list, node_id: int, consumption_factor: int = 1, billable: bool = True):
    """Инкремент node_user_bs_usage для одной БС-ноды (ленивый сброс месяца).

    Купленный пул (User.bs_extra) в течение месяца не трогается — переносится на
    новый месяц нормализацией периода в начале этой же транзакции.

    billable — про владельца ноды (NPVPN-2044.1), прокидывается в
    record_bot_bs_daily как есть, см. его докстринг.
    """
    if not params:
        return

    yyyymm = period_keys(datetime.utcnow())

    with GetDB() as db:
        deltas = {}
        for p in params:
            uid = int(p["uid"])
            deltas[uid] = deltas.get(uid, 0) + int(p["value"] * consumption_factor)

        uids = list(deltas.keys())
        existing_rows = (
            db.query(
                NodeUserBsUsage.user_id,
                NodeUserBsUsage.monthly_used,
                NodeUserBsUsage.monthly_period,
            )
            .filter(
                NodeUserBsUsage.node_id == node_id,
                NodeUserBsUsage.user_id.in_(uids),
            )
            .all()
        )
        existing = {
            r.user_id: {
                "monthly_used": r.monthly_used,
                "monthly_period": r.monthly_period,
            }
            for r in existing_rows
        }

        # Одним запросом отбираем только тех, у кого период пула реально отстал:
        # normalize_bs_extra_period берёт SELECT ... FOR UPDATE до проверки периода, а
        # внутри месяца это no-op — иначе каждый тик (раз в 10 с) лочил бы строку users
        # на каждого активного юзера до конца транзакции. Порядок по id детерминированный,
        # чтобы не плодить взаимные блокировки с транзакциями API.
        stale_users = (
            db.query(User.id)
            .filter(
                User.id.in_(uids),
                User.bs_extra_period.is_not(None),
                User.bs_extra_period < yyyymm,
            )
            .order_by(User.id)
            .all()
        )
        if stale_users:
            from app.services.panel_settings import get_bs_monthly_limit

            monthly_limit = get_bs_monthly_limit(db)
            # Перенос пула на новый месяц — до апдейта счётчиков, пока строки прошлого
            # периода ещё не перезаписаны.
            for (uid,) in stale_users:
                crud.normalize_bs_extra_period(db, uid, monthly_limit, yyyymm, persist=True)

        to_insert, to_update = [], []
        for uid, delta in deltas.items():
            vals = bs_counter_step(existing.get(uid), delta, yyyymm)
            if uid in existing:
                to_update.append({"uid": uid, **vals})
            else:
                to_insert.append({"user_id": uid, "node_id": node_id, **vals})

        # Оба DML идут через db.connection() (Core), а не db.execute() (ORM): ORM-овый
        # executemany-UPDATE с дополнительным WHERE в SQLAlchemy 2.0 всегда падает с
        # InvalidRequestError "bulk synchronize of persistent objects not supported…".
        # Коммита внутри нет намеренно — usage и перенос пула выше должны лечь
        # одной транзакцией (db.commit() в конце функции).
        if to_insert:
            stmt = insert(NodeUserBsUsage)
            if db.bind.name == "mysql":
                stmt = stmt.prefix_with("IGNORE")
            db.connection().execute(stmt, to_insert)

        if to_update:
            stmt = (
                update(NodeUserBsUsage)
                .where(and_(NodeUserBsUsage.node_id == node_id, NodeUserBsUsage.user_id == bindparam("uid")))
                .values(
                    monthly_used=bindparam("monthly_used"),
                    monthly_period=bindparam("monthly_period"),
                )
            )
            db.connection().execute(stmt, to_update)

        # NPVPN-2044: тот же тик пишет суточный агрегат по ботам — одной
        # транзакцией с инкрементом, чтобы расход не мог попасть в одну таблицу
        # и потеряться в другой.
        record_bot_bs_daily(db, node_id, deltas, datetime.utcnow().date(), billable)

        db.commit()


def record_node_stats(params: dict, node_id: int | None):
    if not params:
        return

    created_at = datetime.fromisoformat(datetime.utcnow().strftime("%Y-%m-%dT%H:00:00"))

    with GetDB() as db:
        # make node usage row if doesn't exist
        select_stmt = select(NodeUsage.node_id).where(
            and_(NodeUsage.node_id == node_id, NodeUsage.created_at == created_at)
        )
        notfound = db.execute(select_stmt).first() is None
        if notfound:
            insert_stmt = insert(NodeUsage).values(created_at=created_at, node_id=node_id, uplink=0, downlink=0)
            safe_execute(db, insert_stmt)

        # record
        update_stmt = (
            update(NodeUsage)
            .values(uplink=NodeUsage.uplink + bindparam("up"), downlink=NodeUsage.downlink + bindparam("down"))
            .where(and_(NodeUsage.node_id == node_id, NodeUsage.created_at == created_at))
        )

        safe_execute(db, update_stmt, params)


def get_users_stats(api: XRayAPI):
    params = defaultdict(int)
    for stat in filter(attrgetter("value"), api.get_users_stats(reset=True, timeout=30)):
        params[stat.name.split(".", 1)[0]] += stat.value
    return [{"uid": uid, "value": value} for uid, value in params.items()]


def get_outbounds_stats(api: XRayAPI):
    return [
        {"up": stat.value, "down": 0} if stat.link == "uplink" else {"up": 0, "down": stat.value}
        for stat in filter(attrgetter("value"), api.get_outbounds_stats(reset=True, timeout=10))
    ]


def _usage_context():
    # До reset=True: при недоступной БД не забираем необратимую delta без
    # знания БС-владения. Один запрос метаданных на тик, не на ноду/скрейп.
    revision = usage_state.metadata_revision()
    with GetDB() as db:
        rows = (
            db.query(Node.id, Node.name, Node.is_bs, Node.owner_bot_id)
            .filter(
                Node.status != NodeStatus.disabled,
            )
            .all()
        )
    owners = {row.id: row.owner_bot_id for row in rows if row.is_bs}
    enabled = {row.id: row.name for row in rows}
    apis = {None: (xray.api, 1)}
    apis.update({node: value for node, value in ready_apis(xray.nodes).items() if node in enabled})
    tokens = usage_state.observe_nodes(enabled, revision=revision)
    apis = {node: value for node, value in apis.items() if node is None or node in tokens}
    return apis, owners, tokens


def _admin_totals(values, cache):
    missing = {p["uid"] for p in values} - cache.keys()
    if missing:
        try:
            with GetDB() as db:
                found = dict(db.query(User.id, User.admin_id).filter(User.id.in_(missing)).all())
            cache.update({uid: found.get(uid) for uid in missing})
        except Exception:
            usage_state.mark_failure("user", "admin_map")
            logger.exception("[record_user_usages] admin mapping failed; retaining primary user accounting")
            return {}, False
    totals = defaultdict(int)
    for value in values:
        admin_id = cache.get(value["uid"])
        if admin_id:
            totals[admin_id] += value["value"]
    return totals, True


def _record_user_totals(params, coefficient, admin_cache):
    if not params:
        return True
    values = [{"uid": int(p["uid"]), "value": int(p["value"] * coefficient)} for p in params]
    totals, mapped = _admin_totals(values, admin_cache)
    # Independent session after a failed lookup rollback: secondary admin
    # aggregate must not prevent the primary counter from recording delta.
    with GetDB() as db:
        stmt = (
            update(User)
            .where(User.id == bindparam("uid"))
            .values(
                used_traffic=User.used_traffic + bindparam("value"),
                online_at=datetime.utcnow(),
            )
        )
        safe_execute(db, stmt, values)
        if totals:
            stmt = (
                update(Admin)
                .where(Admin.id == bindparam("admin_id"))
                .values(
                    users_usage=Admin.users_usage + bindparam("value"),
                )
            )
            safe_execute(db, stmt, [{"admin_id": admin_id, "value": value} for admin_id, value in totals.items()])
    return mapped


def _write_usage(kind, node_id, stage, write):
    try:
        result = write()
    except Exception as exc:
        # Delta уже сброшена. Запись автоматически не повторяется: частично
        # зафиксированный инкремент нельзя ещё раз применять без receipt.
        usage_state.mark_failure(kind, stage)
        logger.error("[record_%s_usages] node=%s stage=%s failed: %s", kind, node_id, stage, exc, exc_info=True)
        return False
    return result is not False


def _record_user_node(params, node_id, coefficient, owners, admin_cache):
    success = _write_usage("user", node_id, "totals", lambda: _record_user_totals(params, coefficient, admin_cache))
    if not DISABLE_RECORDING_NODE_USER_USAGE:
        recorded = _write_usage("user", node_id, "history", lambda: record_user_stats(params, node_id, coefficient))
        success = recorded and success
        if node_id in owners:
            recorded = _write_usage(
                "user",
                node_id,
                "bs",
                lambda: record_bs_user_stats(params, node_id, coefficient, owners[node_id] is None),
            )
            success = recorded and success
    return success


def record_user_usages():
    with usage_state.track_tick("user") as tick:
        try:
            apis, owners, tokens = _usage_context()
        except StaleObservationError:
            tick.failed = True
            usage_state.mark_failure("user", "metadata_changed")
            logger.debug("[record_user_usages] lifecycle changed before collection; retry next scheduled tick")
            return
        except Exception:
            usage_state.mark_failure("user", "metadata")
            tick.failed = True
            logger.exception("[record_user_usages] unable to load metadata before collecting deltas")
            return
        admin_cache = {}
        tasks = (
            (
                node_id,
                lambda node=node_id, api=api: usage_state.collect(node, tokens.get(node), lambda: get_users_stats(api)),
            )
            for node_id, (api, _factor) in apis.items()
        )
        for node_id, outcome in completed_results(get_usage_executor(), tasks, limit=XRAY_THREAD_POOL_SIZE):
            if outcome.error is not None:
                tick.failed = True
                usage_state.mark_failure("user", "collect")
                logger.warning("[record_user_usages] node=%s collection failed: %s", node_id, outcome.error)
                continue
            if _record_user_node(outcome.data, node_id, apis[node_id][1], owners, admin_cache):
                usage_state.mark_success(node_id, "user", tokens.get(node_id))
            else:
                tick.failed = True


def _record_node_total(params):
    up = sum(p["up"] for p in params)
    down = sum(p["down"] for p in params)
    if up or down:
        with GetDB() as db:
            safe_execute(db, update(System).values(uplink=System.uplink + up, downlink=System.downlink + down))


def record_node_usages():
    with usage_state.track_tick("node") as tick:
        try:
            apis, _owners, tokens = _usage_context()
        except StaleObservationError:
            tick.failed = True
            usage_state.mark_failure("node", "metadata_changed")
            logger.debug("[record_node_usages] lifecycle changed before collection; retry next scheduled tick")
            return
        except Exception:
            usage_state.mark_failure("node", "metadata")
            tick.failed = True
            logger.exception("[record_node_usages] unable to load metadata before collecting deltas")
            return
        tasks = (
            (
                node_id,
                lambda node=node_id, api=api: usage_state.collect(
                    node, tokens.get(node), lambda: get_outbounds_stats(api)
                ),
            )
            for node_id, (api, _factor) in apis.items()
        )
        for node_id, outcome in completed_results(get_usage_executor(), tasks, limit=XRAY_THREAD_POOL_SIZE):
            if outcome.error is not None:
                tick.failed = True
                usage_state.mark_failure("node", "collect")
                logger.warning("[record_node_usages] node=%s collection failed: %s", node_id, outcome.error)
                continue
            success = _write_usage("node", node_id, "totals", lambda data=outcome.data: _record_node_total(data))
            if not DISABLE_RECORDING_NODE_USAGE:
                recorded = _write_usage(
                    "node", node_id, "history", lambda data=outcome.data, node=node_id: record_node_stats(data, node)
                )
                success = success and recorded
            if success:
                usage_state.mark_success(node_id, "node", tokens.get(node_id))
            else:
                tick.failed = True


def cleanup_node_user_usages():
    if NODE_USER_USAGE_RETENTION_DAYS <= 0:
        return
    cutoff = datetime.utcnow() - timedelta(days=NODE_USER_USAGE_RETENTION_DAYS)
    with GetDB() as db:
        if db.bind.name == "mysql":
            result = db.execute(
                text("DELETE FROM node_user_usages WHERE created_at < :cutoff LIMIT :batch_size"),
                {"cutoff": cutoff, "batch_size": NODE_USER_USAGE_CLEANUP_BATCH_SIZE},
            )
        else:
            result = db.execute(
                text(
                    "DELETE FROM node_user_usages WHERE id IN "
                    "(SELECT id FROM node_user_usages WHERE created_at < :cutoff LIMIT :batch_size)"
                ),
                {"cutoff": cutoff, "batch_size": NODE_USER_USAGE_CLEANUP_BATCH_SIZE},
            )
        db.commit()
        deleted = result.rowcount
    if deleted > 0:
        logger.info(f"[cleanup] deleted {deleted} rows from node_user_usages (cutoff={cutoff})")


scheduler.add_job(
    record_user_usages, "interval", seconds=JOB_RECORD_USER_USAGES_INTERVAL, coalesce=True, max_instances=1
)
scheduler.add_job(
    record_node_usages, "interval", seconds=JOB_RECORD_NODE_USAGES_INTERVAL, coalesce=True, max_instances=1
)
scheduler.add_job(
    cleanup_node_user_usages, "interval", seconds=JOB_CLEANUP_NODE_USER_USAGE_INTERVAL, coalesce=True, max_instances=1
)
