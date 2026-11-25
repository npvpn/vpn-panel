import time
import traceback

from app import app, logger, scheduler, xray
from app.db import GetDB, crud
from app.models.node import NodeStatus
from app.utils.malloc_trim import trim_malloc
from app.xray.node import NodeAPIError
from config import (
    JOB_CORE_HEALTH_CHECK_INTERVAL,
    XRAY_NODE_CONNECT_STALE_TIMEOUT,
    XRAY_NODE_ERROR_RECONNECT_INTERVAL,
    XRAY_NODE_MAX_CONCURRENT_CONNECTS,
)
from xray_api import exc as xray_exc

_error_reconnect_last: dict[int, float] = {}


def _should_force_reconnect(node_id: int, status: NodeStatus, now: float) -> bool:
    if status == NodeStatus.connecting:
        # Soft-defer leaves connecting without an active lock; escalate by DB age.
        age = xray.operations.connecting_age_seconds(node_id)
        return age is not None and age >= XRAY_NODE_CONNECT_STALE_TIMEOUT
    if status != NodeStatus.error:
        return False
    last_attempt = _error_reconnect_last.get(node_id, 0)
    if now - last_attempt >= XRAY_NODE_ERROR_RECONNECT_INTERVAL:
        _error_reconnect_last[node_id] = now
        return True
    return False


def _recover_pending_nodes(node_ids):
    for node_id in node_ids:
        try:
            xray.operations.apply_node(node_id, recover=True)
        except Exception:
            # Durable pending remains available for the next tick. One failed
            # admission must not abort other nodes or startup job registration.
            logger.exception("Failed to recover pending node settings: node_id=%s", node_id)


def core_health_check():
    config = None
    now = time.time()

    # Возвращаем уже освобождённые арены прошлых работ. Snapshot активной
    # команды живёт до её реального завершения, а не до следующего health tick.
    trim_malloc()

    def wave_config():
        """Snapshot только для локального core; ноды строят его после admission."""
        nonlocal config
        if config is None:
            config = xray.config.include_db_users()
        return config

    # main core
    if not xray.core.started:
        xray.core.restart(wave_config())

    with GetDB() as db:
        dbnodes = crud.get_nodes(db=db, enabled=True, include_pending=True)

    _recover_pending_nodes(node.id for node in dbnodes if node.config_apply_pending is True)
    reconnects_scheduled = 0
    max_reconnects = max(1, XRAY_NODE_MAX_CONCURRENT_CONNECTS)

    for dbnode in dbnodes:
        node_id = dbnode.id
        if dbnode.config_apply_pending is True:
            continue

        node = xray.nodes.get(node_id)
        if node is None:
            if reconnects_scheduled < max_reconnects:
                xray.operations.connect_node(node_id)
                reconnects_scheduled += 1
            continue

        if dbnode.status == NodeStatus.connected:
            if not node.connected:
                # Soft reconnect: try_restore / start without /connect when session is kept
                # across a transient ping failure (avoids node takeover + Xray stop).
                if reconnects_scheduled >= max_reconnects:
                    continue
                if xray.operations.is_connect_in_progress(node_id):
                    continue
                logger.debug(
                    f"[health] node_id={node_id} ({dbnode.name}): DB=connected but ping failed → "
                    f"schedule SOFT connect_node(force=False)"
                )
                xray.operations.connect_node(node_id)
                reconnects_scheduled += 1
                continue

            try:
                # Must hit the node REST API (GET /), not cached _started — ping alone
                # does not prove Xray is running (e.g. OOM killed the core).
                if not node.started:
                    raise AssertionError("Xray core is not started on node")
                node.api.get_sys_stats(timeout=2)
            except (ConnectionError, NodeAPIError, xray_exc.XrayError, AssertionError) as exc:
                logger.debug(
                    f"[health] node_id={node_id} ({dbnode.name}): session ok but core/API unhealthy "
                    f"({type(exc).__name__}: {exc}) → schedule restart_node (/restart)"
                )
                xray.operations.restart_node(node_id, manual=False)
            continue

        if dbnode.status not in (NodeStatus.error, NodeStatus.connecting):
            continue

        if reconnects_scheduled >= max_reconnects:
            break

        force = _should_force_reconnect(node_id, dbnode.status, now)

        # Neither queued nor running work can be replaced by elapsed stale age.
        if xray.operations.is_connect_in_progress(node_id):
            continue

        logger.debug(
            f"[health] node_id={node_id} ({dbnode.name}): status={dbnode.status.value} → "
            f"schedule {'HARD' if force else 'SOFT'} connect_node(force={force})"
        )
        xray.operations.connect_node(node_id, force=force)
        reconnects_scheduled += 1


@app.on_event("startup")
def start_core():
    logger.info("Generating Xray core config")

    start_time = time.time()
    config = xray.config.include_db_users()
    logger.info(f"Xray core config generated in {(time.time() - start_time):.2f} seconds")

    with GetDB() as db:
        xray.operations.refresh_master_inbounds(db)

    # main core
    logger.info("Starting main Xray core")
    try:
        xray.core.start(config)
    except Exception:
        traceback.print_exc()

    # nodes' core
    logger.info("Starting nodes Xray core")
    with GetDB() as db:
        dbnodes = crud.get_nodes(db=db, enabled=True, include_pending=True)
        node_ids = []
        pending_ids = []
        for dbnode in dbnodes:
            if dbnode.config_apply_pending is True:
                pending_ids.append(dbnode.id)
            else:
                node_ids.append(dbnode.id)
                crud.update_node_status(db, dbnode, NodeStatus.connecting)

    _recover_pending_nodes(pending_ids)
    xray.operations.connect_nodes(node_ids)

    scheduler.add_job(
        core_health_check, "interval", seconds=JOB_CORE_HEALTH_CHECK_INTERVAL, coalesce=True, max_instances=1
    )


@app.on_event("shutdown")
def app_shutdown():
    logger.info("Stopping main Xray core")
    xray.core.stop()
    xray.operations.release_remote_nodes()
