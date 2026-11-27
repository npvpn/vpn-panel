import asyncio
import time
from concurrent.futures import CancelledError
from contextlib import contextmanager

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, WebSocket
from sqlalchemy.exc import IntegrityError
from starlette.websockets import WebSocketDisconnect

from app import logger, xray
from app.db import Session, crud, get_db
from app.db.models import Node as DBNode
from app.dependencies import get_dbnode, validate_dates
from app.models.admin import Admin
from app.models.node import (
    NodeCreate,
    NodeHostInventory,
    NodeModify,
    NodeResponse,
    NodeSettings,
    NodesUsageResponse,
)
from app.models.proxy import ProxyHost
from app.services import node_lifecycle
from app.services.node_host_memberships import get_node_host_memberships
from app.utils import responses
from app.xray.node_operations import NodeBusyError

router = APIRouter(tags=["Node"], prefix="/api", responses={401: responses._401, 403: responses._403})


@contextmanager
def _node_conflict():
    try:
        yield
    except NodeBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def add_host_if_needed(new_node: NodeCreate, db: Session):
    """Add a host if specified in the new node settings."""
    if new_node.add_as_new_host:
        host = ProxyHost(
            remark=f"{new_node.name} ({{USERNAME}}) [{{PROTOCOL}} - {{TRANSPORT}}]",
            address=new_node.address,
        )
        for inbound_tag in xray.config.inbounds_by_tag:
            crud.add_host(db, inbound_tag, host)
        xray.hosts.update()


@router.get("/node/settings", response_model=NodeSettings)
def get_node_settings(db: Session = Depends(get_db), admin: Admin = Depends(Admin.check_sudo_admin)):
    """Retrieve the current node settings, including TLS certificate."""
    tls = crud.get_tls_certificate(db)
    return NodeSettings(certificate=tls.certificate)


@router.post("/node", response_model=NodeResponse, responses={409: responses._409})
def add_node(
    new_node: NodeCreate,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Add a new node to the database and optionally add it as a host."""
    try:
        dbnode = crud.create_node(db, new_node)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f'Node "{new_node.name}" already exists')

    bg.add_task(xray.operations.connect_node, node_id=dbnode.id)
    bg.add_task(add_host_if_needed, new_node, db)

    logger.info(f'New node "{dbnode.name}" added')
    return dbnode


@router.get("/node/{node_id}", response_model=NodeResponse)
def get_node(
    dbnode: DBNode = Depends(get_dbnode),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Retrieve details of a specific node by its ID."""
    return dbnode


@router.get("/node/{node_id}/hosts", response_model=NodeHostInventory)
def get_node_hosts(
    _: Admin = Depends(Admin.check_sudo_admin),
    dbnode: DBNode = Depends(get_dbnode),
    db: Session = Depends(get_db),
):
    """List the node's saved host roles and contributing composite sources."""
    return get_node_host_memberships(db, int(dbnode.id), set(xray.config.inbounds_by_tag))


@router.websocket("/node/{node_id}/logs")
async def node_logs(node_id: int, websocket: WebSocket, db: Session = Depends(get_db)):
    token = websocket.query_params.get("token") or websocket.headers.get("Authorization", "").removeprefix("Bearer ")
    admin = Admin.get_admin(token, db)
    if not admin:
        return await websocket.close(reason="Unauthorized", code=4401)

    if not admin.is_sudo:
        return await websocket.close(reason="You're not allowed", code=4403)

    if not xray.nodes.get(node_id):
        return await websocket.close(reason="Node not found", code=4404)

    if not xray.nodes[node_id].connected:
        return await websocket.close(reason="Node is not connected", code=4400)

    interval = websocket.query_params.get("interval")
    if interval:
        try:
            interval = float(interval)
        except ValueError:
            return await websocket.close(reason="Invalid interval value", code=4400)
        if interval > 10:
            return await websocket.close(reason="Interval must be more than 0 and at most 10 seconds", code=4400)

    await websocket.accept()

    cache = ""
    last_sent_ts = 0
    node = xray.nodes[node_id]
    with node.get_logs() as logs:
        while True:
            if not node == xray.nodes[node_id]:
                break

            if interval and time.time() - last_sent_ts >= interval and cache:
                try:
                    await websocket.send_text(cache)
                except (WebSocketDisconnect, RuntimeError):
                    break
                cache = ""
                last_sent_ts = time.time()

            if not logs:
                try:
                    await asyncio.wait_for(websocket.receive(), timeout=0.2)
                    continue
                except TimeoutError:
                    continue
                except (WebSocketDisconnect, RuntimeError):
                    break

            log = logs.popleft()

            if interval:
                cache += f"{log}\n"
                continue

            try:
                await websocket.send_text(log)
            except (WebSocketDisconnect, RuntimeError):
                break


@router.get("/nodes", response_model=list[NodeResponse])
def get_nodes(db: Session = Depends(get_db), _: Admin = Depends(Admin.check_sudo_admin)):
    """Retrieve a list of all nodes. Accessible only to sudo admins."""
    return crud.get_nodes(db)


@router.put("/node/{node_id}", response_model=NodeResponse, responses={409: responses._409})
def modify_node(
    modified_node: NodeModify,
    bg: BackgroundTasks,
    dbnode: DBNode = Depends(get_node),
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Update a node's details. Only accessible to sudo admins."""
    with _node_conflict():
        node_lifecycle.modify_node(db, dbnode, modified_node, bg.add_task)
    xray.hosts.update()
    logger.info(f'Node "{dbnode.name}" modified')
    return dbnode


@router.post("/node/{node_id}/reconnect")
def reconnect_node(
    dbnode: DBNode = Depends(get_node),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Trigger a reconnection for the specified node. Only accessible to sudo admins."""
    future = xray.operations.connect_node(node_id=dbnode.id, force=True, manual=True)
    if future.done():
        try:
            future.result()
        except (NodeBusyError, CancelledError) as exc:
            raise HTTPException(status_code=409, detail=str(NodeBusyError())) from exc
    return {"detail": "Reconnection task scheduled"}


@router.delete("/node/{node_id}", responses={409: responses._409})
def remove_node(
    dbnode: DBNode = Depends(get_node),
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.check_sudo_admin),
):
    """Delete a node and remove it from xray in the background."""
    with _node_conflict():
        node_lifecycle.remove_node(db, dbnode)

    xray.hosts.update()
    logger.info(f'Node "{dbnode.name}" deleted')
    return {}


@router.get("/nodes/usage", response_model=NodesUsageResponse)
def get_usage(
    db: Session = Depends(get_db),
    start: str = "",
    end: str = "",
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Retrieve usage statistics for nodes within a specified date range."""
    start, end = validate_dates(start, end)

    usages, traffic_source = crud.get_nodes_usage(db, start, end)

    return {"usages": usages, "traffic_source": traffic_source}
