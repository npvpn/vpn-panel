import time
import traceback

from app import app, logger, scheduler, xray
from app.db import GetDB, crud
from app.models.node import NodeStatus
from app.xray.node import NodeAPIError
from config import (
    JOB_CORE_HEALTH_CHECK_INTERVAL,
    XRAY_NODE_ERROR_RECONNECT_INTERVAL,
    XRAY_NODE_MAX_CONCURRENT_CONNECTS,
)
from xray_api import exc as xray_exc

_error_reconnect_last: dict[int, float] = {}


def _should_force_reconnect(node_id: int, status: NodeStatus, now: float) -> bool:
    if status == NodeStatus.connecting and xray.operations.is_connect_stale(node_id):
        return True
    if status != NodeStatus.error:
        return False
    last_attempt = _error_reconnect_last.get(node_id, 0)
    if now - last_attempt >= XRAY_NODE_ERROR_RECONNECT_INTERVAL:
        _error_reconnect_last[node_id] = now
        return True
    return False


def core_health_check():
    config = None
    now = time.time()

    # main core
    if not xray.core.started:
        if not config:
            config = xray.config.include_db_users()
        xray.core.restart(config)

    with GetDB() as db:
        dbnodes = crud.get_nodes(db=db, enabled=True)

    reconnects_scheduled = 0
    max_reconnects = max(1, XRAY_NODE_MAX_CONCURRENT_CONNECTS)

    for dbnode in dbnodes:
        node_id = dbnode.id

        if node_id not in xray.nodes:
            xray.operations.add_node(dbnode)

        node = xray.nodes[node_id]

        if dbnode.status == NodeStatus.connected:
            if not node.connected:
                # Soft reconnect: try_restore / start without /connect when session is kept
                # across a transient ping failure (avoids node takeover + Xray stop).
                if reconnects_scheduled >= max_reconnects:
                    continue
                if not config:
                    config = xray.config.include_db_users()
                logger.debug(
                    f"[health] node_id={node_id} ({dbnode.name}): DB=connected but ping failed → "
                    f"schedule SOFT connect_node(force=False)"
                )
                xray.operations.connect_node(node_id, config)
                reconnects_scheduled += 1
                continue

            try:
                # Must hit the node REST API (GET /), not cached _started — ping alone
                # does not prove Xray is running (e.g. OOM killed the core).
                if not node.started:
                    raise AssertionError("Xray core is not started on node")
                node.api.get_sys_stats(timeout=2)
            except (ConnectionError, NodeAPIError, xray_exc.XrayError, AssertionError) as exc:
                if not config:
                    config = xray.config.include_db_users()
                logger.debug(
                    f"[health] node_id={node_id} ({dbnode.name}): session ok but core/API unhealthy "
                    f"({type(exc).__name__}: {exc}) → schedule restart_node (/restart)"
                )
                xray.operations.restart_node(node_id, config)
            continue

        if dbnode.status == NodeStatus.connecting:
            if xray.operations.is_connect_in_progress(node_id):
                continue
            # No active connect task — fall through and schedule reconnect below.

        if dbnode.status not in (NodeStatus.error, NodeStatus.connecting):
            continue

        if reconnects_scheduled >= max_reconnects:
            break

        if not config:
            config = xray.config.include_db_users()

        force = _should_force_reconnect(node_id, dbnode.status, now)
        if xray.operations.is_connect_in_progress(node_id) and not force:
            continue

        logger.debug(
            f"[health] node_id={node_id} ({dbnode.name}): status={dbnode.status.value} → "
            f"schedule {'HARD' if force else 'SOFT'} connect_node(force={force})"
        )
        xray.operations.connect_node(node_id, config, force=force)
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
        dbnodes = crud.get_nodes(db=db, enabled=True)
        node_ids = [dbnode.id for dbnode in dbnodes]
        for dbnode in dbnodes:
            crud.update_node_status(db, dbnode, NodeStatus.connecting)

    for node_id in node_ids:
        xray.operations.connect_node(node_id, config)

    scheduler.add_job(
        core_health_check, "interval", seconds=JOB_CORE_HEALTH_CHECK_INTERVAL, coalesce=True, max_instances=1
    )


@app.on_event("shutdown")
def app_shutdown():
    logger.info("Stopping main Xray core")
    xray.core.stop()

    logger.info("Stopping nodes Xray core")
    for node in list(xray.nodes.values()):
        try:
            node.disconnect()
        except Exception:
            pass
