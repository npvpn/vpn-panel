from collections import defaultdict
from datetime import datetime, timedelta
from operator import attrgetter

from pymysql.err import OperationalError
from sqlalchemy import and_, bindparam, insert, select, text, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.dml import Insert

from app import logger, scheduler, xray
from app.db import GetDB, crud
from app.db.models import Admin, BotSettings, Node, NodeUsage, NodeUserBsUsage, NodeUserUsage, System, User
from app.models.bot import apply_bot_settings_fallback
from app.utils.concurrency import get_xray_executor
from app.xray.bs_limit import bs_counter_step, period_keys
from config import (
    DISABLE_RECORDING_NODE_USAGE,
    DISABLE_RECORDING_NODE_USER_USAGE,
    JOB_CLEANUP_NODE_USER_USAGE_INTERVAL,
    JOB_RECORD_NODE_USAGES_INTERVAL,
    JOB_RECORD_USER_USAGES_INTERVAL,
    NODE_USER_USAGE_CLEANUP_BATCH_SIZE,
    NODE_USER_USAGE_RETENTION_DAYS,
)
from xray_api import XRay as XRayAPI
from xray_api import exc as xray_exc


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

    created_at = datetime.fromisoformat(datetime.utcnow().strftime("%Y-%m-%dT%H:00:00"))

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
                user_id=bindparam("uid"), created_at=created_at, node_id=node_id, used_traffic=0
            )
            safe_execute(db, stmt, [{"uid": uid} for uid in uids_to_insert])

        # record
        stmt = (
            update(NodeUserUsage)
            .values(used_traffic=NodeUserUsage.used_traffic + bindparam("value") * consumption_factor)
            .where(
                and_(
                    NodeUserUsage.user_id == bindparam("uid"),
                    NodeUserUsage.node_id == node_id,
                    NodeUserUsage.created_at == created_at,
                )
            )
        )
        safe_execute(db, stmt, params)


def record_bs_user_stats(params: list, node_id: int, consumption_factor: int = 1):
    """Инкремент node_user_bs_usage для одной БС-ноды (ленивый сброс месяца).

    Списание из User.bs_extra (купленный пул) — в той же транзакции, что и usage,
    по приросту агрегата monthly_used сверх bs_monthly_limit бота.
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

        old_monthly_aggs = {uid: crud.get_bs_usage_totals(db, uid, yyyymm) for uid in uids}

        user_bot = dict(db.query(User.id, User.bot_id).filter(User.id.in_(uids)).all())
        bot_monthly_limits = {}
        for bot_id, data in db.query(BotSettings.bot_id, BotSettings.data).all():
            settings = apply_bot_settings_fallback(data)
            bot_monthly_limits[bot_id] = settings.get("bs_monthly_limit") or 0

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
        # Коммита внутри нет намеренно — usage и списание bs_extra ниже должны лечь
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

        for uid in uids:
            new_monthly_agg = crud.get_bs_usage_totals(db, uid, yyyymm)
            monthly_limit = bot_monthly_limits.get(user_bot.get(uid), 0)
            crud.apply_bs_extra_pool_consumption(db, uid, old_monthly_aggs[uid], new_monthly_agg, monthly_limit)

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
    try:
        params = defaultdict(int)
        for stat in filter(attrgetter("value"), api.get_users_stats(reset=True, timeout=30)):
            params[stat.name.split(".", 1)[0]] += stat.value
        params = list({"uid": uid, "value": value} for uid, value in params.items())
        return params
    except xray_exc.XrayError:
        return []


def get_outbounds_stats(api: XRayAPI):
    try:
        params = [
            {"up": stat.value, "down": 0} if stat.link == "uplink" else {"up": 0, "down": stat.value}
            for stat in filter(attrgetter("value"), api.get_outbounds_stats(reset=True, timeout=10))
        ]
        return params
    except xray_exc.XrayError:
        return []


def record_user_usages():
    api_instances = {None: xray.api}
    usage_coefficient = {None: 1}  # default usage coefficient for the main api instance

    for node_id, node in list(xray.nodes.items()):
        if node.connected and node.started:
            api_instances[node_id] = node.api
            usage_coefficient[node_id] = node.usage_coefficient  # fetch the usage coefficient

    executor = get_xray_executor()
    futures = {node_id: executor.submit(get_users_stats, api) for node_id, api in api_instances.items()}
    # Сбой одной ноды не должен ронять весь джоб и терять статистику остальных.
    api_params = {}
    for node_id, future in futures.items():
        try:
            api_params[node_id] = future.result()
        except Exception as e:
            logger.warning(f"[record_user_usages] failed to collect stats for node {node_id}: {type(e).__name__}: {e}")
            api_params[node_id] = []

    users_usage = defaultdict(int)
    for node_id, params in api_params.items():
        coefficient = usage_coefficient.get(node_id, 1)  # get the usage coefficient for the node
        for param in params:
            users_usage[param["uid"]] += int(param["value"] * coefficient)  # apply the usage coefficient
    users_usage = list({"uid": uid, "value": value} for uid, value in users_usage.items())
    if not users_usage:
        return

    admin_usage = defaultdict(int)
    try:
        with GetDB() as db:
            user_ids = [int(u["uid"]) for u in users_usage]
            user_admin_map = dict(db.query(User.id, User.admin_id).filter(User.id.in_(user_ids)).all())
        for user_usage in users_usage:
            admin_id = user_admin_map.get(int(user_usage["uid"]))
            if admin_id:
                admin_usage[admin_id] += user_usage["value"]
    except Exception as e:
        # Не можем посчитать admin-агрегат — это не повод терять учёт трафика
        # самих юзеров, просто пропускаем admin-обновление этого тика.
        logger.warning(f"[record_user_usages] failed to build admin usage map: {type(e).__name__}: {e}")
        admin_usage = defaultdict(int)

    # record users usage
    try:
        with GetDB() as db:
            stmt = (
                update(User)
                .where(User.id == bindparam("uid"))
                .values(used_traffic=User.used_traffic + bindparam("value"), online_at=datetime.utcnow())
            )

            safe_execute(db, stmt, users_usage)

            admin_data = [{"admin_id": admin_id, "value": value} for admin_id, value in admin_usage.items()]
            if admin_data:
                admin_update_stmt = (
                    update(Admin)
                    .where(Admin.id == bindparam("admin_id"))
                    .values(users_usage=Admin.users_usage + bindparam("value"))
                )
                safe_execute(db, admin_update_stmt, admin_data)
    except Exception as e:
        # Счётчики xray уже сброшены (reset=True), трафик этого тика потерян
        # безвозвратно — но джоб не должен умирать и пропускать следующие тики.
        logger.error(f"[record_user_usages] failed to write user/admin usage: {type(e).__name__}: {e}")

    if DISABLE_RECORDING_NODE_USER_USAGE:
        return

    # id всех БС-нод — для них дополнительно ведём node_user_bs_usage.
    try:
        with GetDB() as db:
            bs_node_ids = {nid for (nid,) in db.query(Node.id).filter(Node.is_bs.is_(True)).all()}
    except Exception as e:
        logger.warning(f"[record_user_usages] failed to load BS node ids: {type(e).__name__}: {e}")
        bs_node_ids = set()

    for node_id, params in api_params.items():
        try:
            record_user_stats(params, node_id, usage_coefficient[node_id])
        except Exception as e:
            logger.warning(
                f"[record_user_usages] failed to record node_user_usage for node {node_id}: {type(e).__name__}: {e}"
            )
        # node_id=None (главный xray-инстанс) никогда не попадает в bs_node_ids
        # (там только целочисленные id нод из БД), поэтому БС-учёт его не трогает.
        if node_id in bs_node_ids:
            try:
                record_bs_user_stats(params, node_id, usage_coefficient[node_id])
            except Exception as e:
                logger.warning(
                    f"[record_user_usages] failed to record node_user_bs_usage for "
                    f"node {node_id}: {type(e).__name__}: {e}"
                )


def record_node_usages():
    api_instances = {None: xray.api}
    for node_id, node in list(xray.nodes.items()):
        if node.connected and node.started:
            api_instances[node_id] = node.api

    executor = get_xray_executor()
    futures = {node_id: executor.submit(get_outbounds_stats, api) for node_id, api in api_instances.items()}
    api_params = {node_id: future.result() for node_id, future in futures.items()}

    total_up = 0
    total_down = 0
    for node_id, params in api_params.items():
        for param in params:
            total_up += param["up"]
            total_down += param["down"]
    if not (total_up or total_down):
        return

    # record nodes usage
    with GetDB() as db:
        stmt = update(System).values(uplink=System.uplink + total_up, downlink=System.downlink + total_down)
        safe_execute(db, stmt)

    if DISABLE_RECORDING_NODE_USAGE:
        return

    for node_id, params in api_params.items():
        record_node_stats(params, node_id)


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
