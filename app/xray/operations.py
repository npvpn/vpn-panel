import _thread
import threading
import time
from datetime import datetime
from functools import cache
from types import SimpleNamespace
from typing import TYPE_CHECKING

from sqlalchemy.exc import SQLAlchemyError

from app import logger, xray
from app.db import GetDB, crud
from app.models.node import NodeProtocol, NodeStatus
from app.models.user import UserResponse
from app.utils.concurrency import get_node_executor, threaded_function
from app.utils.usage_runtime import usage_state
from app.xray.node import XRayNode
from app.xray.node_config import node_config_json, node_has_inbound
from app.xray.node_operations import NodeOperationScheduler, NodeOperationSuperseded, OperationKind
from config import (
    XRAY_NODE_CONNECT_CONCURRENCY,
    XRAY_NODE_CONNECT_RETRIES,
    XRAY_NODE_CONNECT_RETRY_DELAY,
)
from xray_api import XRay as XRayAPI
from xray_api.types.account import Account, XTLSFlows

if TYPE_CHECKING:
    from app.db import User as DBUser
    from app.db.models import Node as DBNode


def _is_closed_grpc_channel_error(exc: Exception) -> bool:
    if not isinstance(exc, ValueError):
        return False
    msg = str(exc).lower()
    return "closed channel" in msg or "channel closed" in msg


def _node_has_inbound(node, inbound_tag: str) -> bool:
    """Есть ли inbound_tag среди реально включённых на ноде тегов.

    `node.inbound_tags` заполняется после успешного start/restart набором тегов,
    с которым нода была поднята (см. node_has_inbound в app/xray/node_config.py).
    """
    return node_has_inbound(getattr(node, "inbound_tags", None), inbound_tag)


def _get_ready_nodes():
    """Return nodes that look ready based on cached flags only — no network calls.

    Network properties (`node.connected`, `node.started`) hit each node over HTTP and
    serialize the caller; one slow node × ~200 nodes can stall the starlette threadpool.
    """
    ready = []
    for node in list(xray.nodes.values()):
        try:
            if hasattr(node, "_started"):
                is_started = bool(getattr(node, "_started"))
                has_session = bool(getattr(node, "_session_id", None))
            elif hasattr(node, "started"):
                is_started = bool(getattr(node, "started"))
                has_session = True
            else:
                continue
        except Exception:
            continue
        if is_started and has_session:
            ready.append(node)
    return ready


@cache
def get_tls():
    from app.db import GetDB, get_tls_certificate

    with GetDB() as db:
        tls = get_tls_certificate(db)
        return {"key": tls.key, "certificate": tls.certificate}


def refresh_master_inbounds(db):
    """Перечитать теги инбаундов Master из БД в кеш xray.master_inbound_tags (in-place)."""
    from app import xray

    xray.master_inbound_tags[:] = crud.get_master_inbound_tags(db)


@threaded_function
def _add_user_to_inbound(api: XRayAPI, inbound_tag: str, account: Account):
    try:
        api.add_inbound_user(tag=inbound_tag, user=account, timeout=10)
    except xray.exc.EmailNotFoundError as e:
        # User may be absent on this inbound/node; removal is idempotent.
        logger.debug(
            f"[xray.add_user.call][error] inbound={inbound_tag} email={getattr(account, 'email', 'unknown')} error={type(e).__name__}: {e}"
        )
    except (xray.exc.ConnectionError, xray.exc.TimeoutError) as e:
        logger.warning(
            f"[xray.add_user.call][error] inbound={inbound_tag} email={getattr(account, 'email', 'unknown')} error={type(e).__name__}: {e}"
        )
    except Exception as e:
        if _is_closed_grpc_channel_error(e):
            logger.warning(
                f"[xray.add_user.call][error] inbound={inbound_tag} email={getattr(account, 'email', 'unknown')} error={type(e).__name__}: {e}"
            )
        else:
            logger.error(
                f"[xray.add_user.call][unexpected] inbound={inbound_tag} email={getattr(account, 'email', 'unknown')} error={type(e).__name__}: {e}"
            )


@threaded_function
def _remove_user_from_inbound(api: XRayAPI, inbound_tag: str, email: str):
    try:
        api.remove_inbound_user(tag=inbound_tag, email=email, timeout=10)
    except xray.exc.EmailNotFoundError as e:
        # User may be absent on this inbound/node; removal is idempotent.
        logger.debug(
            f"[xray.remove_user.call][error] inbound={inbound_tag} email={email} error={type(e).__name__}: {e}"
        )
    except (xray.exc.ConnectionError, xray.exc.TimeoutError) as e:
        logger.warning(
            f"[xray.remove_user.call][error] inbound={inbound_tag} email={email} error={type(e).__name__}: {e}"
        )
    except Exception as e:
        if _is_closed_grpc_channel_error(e):
            logger.warning(
                f"[xray.remove_user.call][error] inbound={inbound_tag} email={email} error={type(e).__name__}: {e}"
            )
        else:
            logger.error(
                f"[xray.remove_user.call][unexpected] inbound={inbound_tag} email={email} error={type(e).__name__}: {e}"
            )


@threaded_function
def _alter_inbound_user(api: XRayAPI, inbound_tag: str, account: Account):
    try:
        api.remove_inbound_user(tag=inbound_tag, email=account.email, timeout=10)
    except xray.exc.EmailNotFoundError as e:
        # User may be absent on this inbound/node; removal is idempotent.
        logger.debug(
            f"[xray.alter_user.call][skip] step=remove inbound={inbound_tag} email={account.email} error={type(e).__name__}: {e}"
        )
    except (xray.exc.ConnectionError, xray.exc.TimeoutError) as e:
        logger.warning(
            f"[xray.alter_user.call][error] step=remove inbound={inbound_tag} email={account.email} error={type(e).__name__}: {e}"
        )
    except Exception as e:
        if _is_closed_grpc_channel_error(e):
            logger.warning(
                f"[xray.alter_user.call][error] step=remove inbound={inbound_tag} email={account.email} error={type(e).__name__}: {e}"
            )
        else:
            logger.error(
                f"[xray.alter_user.call][unexpected] step=remove inbound={inbound_tag} email={account.email} error={type(e).__name__}: {e}"
            )
    try:
        api.add_inbound_user(tag=inbound_tag, user=account, timeout=10)
    except (xray.exc.EmailExistsError, xray.exc.ConnectionError, xray.exc.TimeoutError) as e:
        logger.warning(
            f"[xray.alter_user.call][error] step=add inbound={inbound_tag} email={account.email} error={type(e).__name__}: {e}"
        )
    except Exception as e:
        if _is_closed_grpc_channel_error(e):
            logger.warning(
                f"[xray.alter_user.call][error] step=add inbound={inbound_tag} email={account.email} error={type(e).__name__}: {e}"
            )
        else:
            logger.error(
                f"[xray.alter_user.call][unexpected] step=add inbound={inbound_tag} email={account.email} error={type(e).__name__}: {e}"
            )


def add_user(dbuser: "DBUser"):
    if dbuser is None:
        logger.warning("[xray.add_user] called with dbuser=None; skipping")
        return
    user = UserResponse.model_validate(dbuser)
    email = f"{dbuser.id}.{dbuser.username}"

    t0 = time.monotonic()
    ready_nodes = _get_ready_nodes()
    total_nodes = len(xray.nodes)

    for proxy_type, inbound_tags in user.inbounds.items():
        for inbound_tag in inbound_tags:
            inbound = xray.config.inbounds_by_tag.get(inbound_tag, {})

            try:
                proxy_settings = user.proxies[proxy_type].dict(no_obj=True)
            except KeyError:
                pass
            account = proxy_type.account_model(email=email, **proxy_settings)

            # XTLS currently only supports transmission methods of TCP and mKCP
            if getattr(account, "flow", None) and (
                inbound.get("network", "tcp") not in ("tcp", "kcp")
                or (inbound.get("network", "tcp") in ("tcp", "kcp") and inbound.get("tls") not in ("tls", "reality"))
                or inbound.get("header_type") == "http"
            ):
                account.flow = XTLSFlows.NONE

            _add_user_to_inbound(xray.api, inbound_tag, account)  # main core
            for node in ready_nodes:
                if not _node_has_inbound(node, inbound_tag):
                    continue
                try:
                    _add_user_to_inbound(node.api, inbound_tag, account)
                except Exception as e:
                    logger.warning(
                        f'[xray.add_user] node call failed user="{dbuser.username}" '
                        f'inbound="{inbound_tag}": {type(e).__name__}: {e}'
                    )
    logger.info(
        f"[xray.add_user] done email={email} nodes_ready={len(ready_nodes)} "
        f"nodes_total={total_nodes} dt={time.monotonic() - t0:.2f}s"
    )


def remove_user(dbuser: "DBUser"):
    if dbuser is None:
        logger.warning("[xray.remove_user] called with dbuser=None; skipping")
        return
    email = f"{dbuser.id}.{dbuser.username}"
    user = UserResponse.model_validate(dbuser)

    # Build set of factual inbounds for this user (actual protocol tags assigned)
    target_inbounds = set()
    try:
        for _, inbound_tags in user.inbounds.items():
            for inbound_tag in inbound_tags:
                target_inbounds.add(inbound_tag)
    except Exception:
        target_inbounds = set()

    # Fallback: if we could not determine factual inbounds, fallback to all configured
    if not target_inbounds:
        target_inbounds = set(xray.config.inbounds_by_tag.keys())

    try:
        total_inbounds = len(xray.config.inbounds_by_tag)
    except Exception:
        total_inbounds = 0
    try:
        total_nodes = len(xray.nodes)
    except Exception:
        total_nodes = 0
    logger.info(
        f"[xray.remove_user] start email={email} target_inbounds={len(target_inbounds)} total_inbounds={total_inbounds} nodes={total_nodes}"
    )

    ready_nodes = _get_ready_nodes()
    logger.info(f"[xray.remove_user] nodes_ready={len(ready_nodes)} nodes_total={total_nodes}")

    for inbound_tag in target_inbounds:
        _remove_user_from_inbound(xray.api, inbound_tag, email)
        for node in ready_nodes:
            if not _node_has_inbound(node, inbound_tag):
                continue
            # Не допускаем падения при недоступной ноде
            try:
                _remove_user_from_inbound(node.api, inbound_tag, email)
            except Exception as e:
                logger.warning(
                    f'XRAY node check/remove failed for user "{dbuser.username}" on inbound "{inbound_tag}": {type(e).__name__}: {e}'
                )


def update_user(dbuser: "DBUser"):
    if dbuser is None:
        logger.warning("[xray.update_user] called with dbuser=None; skipping")
        return
    user = UserResponse.model_validate(dbuser)
    email = f"{dbuser.id}.{dbuser.username}"

    t0 = time.monotonic()
    ready_nodes = _get_ready_nodes()
    total_nodes = len(xray.nodes)

    active_inbounds = []
    for proxy_type, inbound_tags in user.inbounds.items():
        for inbound_tag in inbound_tags:
            active_inbounds.append(inbound_tag)
            inbound = xray.config.inbounds_by_tag.get(inbound_tag, {})

            try:
                proxy_settings = user.proxies[proxy_type].dict(no_obj=True)
            except KeyError:
                pass
            account = proxy_type.account_model(email=email, **proxy_settings)

            # XTLS currently only supports transmission methods of TCP and mKCP
            if getattr(account, "flow", None) and (
                inbound.get("network", "tcp") not in ("tcp", "kcp")
                or (inbound.get("network", "tcp") in ("tcp", "kcp") and inbound.get("tls") not in ("tls", "reality"))
                or inbound.get("header_type") == "http"
            ):
                account.flow = XTLSFlows.NONE

            _alter_inbound_user(xray.api, inbound_tag, account)  # main core
            for node in ready_nodes:
                if not _node_has_inbound(node, inbound_tag):
                    continue
                try:
                    _alter_inbound_user(node.api, inbound_tag, account)
                except Exception as e:
                    logger.warning(
                        f'[xray.update_user] node alter failed user="{dbuser.username}" '
                        f'inbound="{inbound_tag}": {type(e).__name__}: {e}'
                    )

    for inbound_tag in xray.config.inbounds_by_tag:
        if inbound_tag in active_inbounds:
            continue
        # remove disabled inbounds
        _remove_user_from_inbound(xray.api, inbound_tag, email)
        for node in ready_nodes:
            if not _node_has_inbound(node, inbound_tag):
                continue
            try:
                _remove_user_from_inbound(node.api, inbound_tag, email)
            except Exception as e:
                logger.warning(
                    f"[xray.update_user] node remove (disabled inbound) failed "
                    f'user="{dbuser.username}" inbound="{inbound_tag}": {type(e).__name__}: {e}'
                )
    logger.info(
        f"[xray.update_user] done email={email} nodes_ready={len(ready_nodes)} "
        f"nodes_total={total_nodes} dt={time.monotonic() - t0:.2f}s"
    )


def update_user_by_id(user_id: int):
    """
    Safe wrapper to update a user in background tasks by reloading a fresh DB-bound instance.
    Prevents DetachedInstanceError when original dbuser is out of session.
    """
    with GetDB() as db:
        try:
            dbuser = crud.get_user_by_id(db, user_id)
            if not dbuser:
                return
            update_user(dbuser)
        except SQLAlchemyError:
            db.rollback()
            raise


def _user_inbound_tags(user) -> list:
    """Список фактических inbound-тегов пользователя (по всем proxy-типам)."""
    tags = []
    for _, inbound_tags in user.inbounds.items():
        for inbound_tag in inbound_tags:
            tags.append(inbound_tag)
    return tags


def remove_user_from_node(dbuser: "DBUser", node_id: int):
    """Снять пользователя ТОЛЬКО с указанной ноды (по её API), не трогая остальные."""
    if dbuser is None:
        return
    node = xray.nodes.get(node_id)
    if node is None:
        return  # нода не подключена — фильтрация стартового конфига снимет её при connect
    email = f"{dbuser.id}.{dbuser.username}"
    user = UserResponse.model_validate(dbuser)
    for inbound_tag in _user_inbound_tags(user):
        if not _node_has_inbound(node, inbound_tag):
            continue
        try:
            _remove_user_from_inbound(node.api, inbound_tag, email)
        except Exception as e:
            logger.warning(
                f"[xray.remove_user_from_node] node={node_id} "
                f'user="{dbuser.username}" inbound="{inbound_tag}": '
                f"{type(e).__name__}: {e}"
            )
    logger.info(f"[xray.remove_user_from_node] email={email} node_id={node_id}")


def add_user_to_node(dbuser: "DBUser", node_id: int):
    """Вернуть пользователя ТОЛЬКО на указанную ноду (по её API)."""
    if dbuser is None:
        return
    node = xray.nodes.get(node_id)
    if node is None:
        return
    email = f"{dbuser.id}.{dbuser.username}"
    user = UserResponse.model_validate(dbuser)
    for proxy_type, inbound_tags in user.inbounds.items():
        for inbound_tag in inbound_tags:
            if not _node_has_inbound(node, inbound_tag):
                continue
            inbound = xray.config.inbounds_by_tag.get(inbound_tag, {})
            try:
                proxy_settings = user.proxies[proxy_type].dict(no_obj=True)
            except KeyError:
                proxy_settings = {}
            account = proxy_type.account_model(email=email, **proxy_settings)
            if getattr(account, "flow", None) and (
                inbound.get("network", "tcp") not in ("tcp", "kcp")
                or (inbound.get("network", "tcp") in ("tcp", "kcp") and inbound.get("tls") not in ("tls", "reality"))
                or inbound.get("header_type") == "http"
            ):
                account.flow = XTLSFlows.NONE
            try:
                _add_user_to_inbound(node.api, inbound_tag, account)
            except Exception as e:
                logger.warning(
                    f"[xray.add_user_to_node] node={node_id} "
                    f'user="{dbuser.username}" inbound="{inbound_tag}": '
                    f"{type(e).__name__}: {e}"
                )
    logger.info(f"[xray.add_user_to_node] email={email} node_id={node_id}")


def _blocked_user_ids(db, node_id: int) -> set:
    """user_id, заблокированные на данной ноде (читать в открытой DB-сессии)."""
    from app.db.models import NodeUserBlock

    return {b.user_id for b in db.query(NodeUserBlock.user_id).filter(NodeUserBlock.node_id == node_id).all()}


def _find_inbound(config, tag):
    """Найти определение инбаунда по tag в общем xray-конфиге (None, если нет)."""
    for inbound in config.get("inbounds") or []:
        if inbound.get("tag") == tag:
            return inbound
    return None


def _cascade_kwargs(db, dbnode) -> dict:
    """Собрать kwargs для cascade_config из dbnode. Вызывать в открытой DB-сессии:
    резолвит маршруты/exit_node/cascade_params + читает определение cascade-инбаунда
    из общего xray-конфига и деривит publicKey, всё в plain-данные (без ORM-ссылок),
    чтобы не словить DetachedInstanceError после закрытия сессии.
    """
    # Ленивый импорт: app.db.models тянет за собой app.xray (через цепочку моделей),
    # а top-level импорт CascadeRoute здесь замыкал цикл и ломал инициализацию
    # app.db.models при старте сервера (config.py:db_models становился частичным).
    from app.db.models import CascadeRoute

    role = dbnode.role.value if dbnode.role else "direct"

    if role == "exit":
        params = dbnode.cascade_params or {}
        uuid = params.get("uuid")
        if not uuid:
            return {"role": "exit"}  # роль есть, но uuid ещё не сгенерён — нечего инъектить
        exit_routes = db.query(CascadeRoute).filter(CascadeRoute.exit_node_id == dbnode.id).all()
        clients = [{"inbound_tag": r.cascade_inbound_tag, "uuid": uuid} for r in exit_routes]
        return {"role": "exit", "cascade_clients": clients}

    if role == "entry":
        routes = []
        for r in dbnode.cascade_routes:
            exit_node = r.exit_node
            if not exit_node:
                continue
            uuid = (exit_node.cascade_params or {}).get("uuid")
            if not uuid:
                continue  # выходная ещё без служебного uuid — пропускаем маршрут
            inbound = _find_inbound(xray.config, r.cascade_inbound_tag)
            if not inbound:
                continue  # cascade-инбаунд отсутствует в каталоге
            reality = (inbound.get("streamSettings") or {}).get("realitySettings") or {}
            private_key = reality.get("privateKey")
            if not private_key:
                continue  # инбаунд не REALITY — пропускаем
            keys = xray.core.get_x25519(private_key=private_key)
            if not keys:
                continue
            server_names = reality.get("serverNames") or []
            short_ids = reality.get("shortIds") or []
            routes.append(
                {
                    "entry_inbound_tag": r.entry_inbound_tag,
                    "exit_node_id": r.exit_node_id,
                    "cascade_inbound_tag": r.cascade_inbound_tag,
                    "address": exit_node.address,
                    "port": inbound.get("port"),
                    "uuid": uuid,
                    "public_key": keys["public_key"],
                    "short_id": short_ids[0] if short_ids else "",
                    "sni": server_names[0] if server_names else "",
                    "fingerprint": reality.get("fingerprint") or "",
                }
            )
        strategy = getattr(dbnode.cascade_balancer_strategy, "value", None) or "random"
        return {"role": "entry", "entry_routes": routes, "strategy": strategy}

    return {"role": "direct"}


_node_lifecycle_locks: dict[int, _thread.RLock] = {}
_node_lifecycle_locks_guard = threading.Lock()
_node_operation_locks: dict[int, _thread.RLock] = {}
_node_operation_locks_guard = threading.Lock()


def _node_lifecycle_lock(node_id: int):
    with _node_lifecycle_locks_guard:
        if node_id not in _node_lifecycle_locks:
            _node_lifecycle_locks[node_id] = threading.RLock()
        return _node_lifecycle_locks[node_id]


def _node_operation_lock(node_id: int):
    with _node_operation_locks_guard:
        if node_id not in _node_operation_locks:
            _node_operation_locks[node_id] = threading.RLock()
        return _node_operation_locks[node_id]


_node_scheduler = None
_node_scheduler_lock = threading.Lock()


def _execute_node_operation(node_id, kind, config_factory):
    if kind == OperationKind.APPLY:
        return _apply_node_impl(node_id, config_factory)
    # A previous failed apply can leave the old endpoint in the registry.
    # Every command must finish that transition before using a transport again.
    # Defer through admission so accounting leases never occupy a worker slot.
    scheduler = get_node_scheduler()
    with scheduler.metadata(node_id):
        scheduler.check_current(node_id)
        with GetDB() as db:
            dbnode = crud.get_node_by_id(db, node_id)
            pending = dbnode is not None and getattr(dbnode, "config_apply_pending", False) is True
        if pending:
            apply_node(node_id)
            return False
    if kind == OperationKind.RESTART:
        with _node_operation_lock(node_id):
            return _restart_node_impl(node_id, config_factory=config_factory)
    return _connect_node_impl(node_id, force=kind == OperationKind.HARD, config_factory=config_factory)


def get_node_scheduler() -> NodeOperationScheduler:
    global _node_scheduler
    with _node_scheduler_lock:
        if _node_scheduler is None:
            _node_scheduler = NodeOperationScheduler(
                get_node_executor(),
                _execute_node_operation,
                lambda: xray.config.include_db_users(),
                concurrency=XRAY_NODE_CONNECT_CONCURRENCY,
            )
        return _node_scheduler


def node_mutation(node_id):
    return get_node_scheduler().mutation(node_id)


def apply_node(node_id: int, *, accounting=None, recover: bool = False):
    state = accounting if accounting is not None else usage_state
    scheduler = get_node_scheduler()
    with scheduler.metadata(node_id):
        if recover:
            # Health/startup snapshots can precede a completed acknowledgement.
            with GetDB() as db:
                dbnode = crud.get_node_by_id(db, node_id)
                if dbnode is None or not dbnode.config_apply_pending:
                    return None
            if scheduler.pending(node_id):
                return None
        state.pause(node_id)
        future = scheduler.prepare_apply(node_id, priority=not recover)
        state.when_idle(node_id, lambda: scheduler.ready(node_id, future))
    return future


def _stop_apply_endpoint(node_id, dbnode, old_endpoint):
    scheduler = get_node_scheduler()
    saved_session = old_endpoint.get("control_session_id") if old_endpoint else dbnode.control_session_id
    # After a panel restart the local registry is empty, but remote Xray
    # may still run. Recreate only the control transport and stop it.
    transport = xray.nodes.get(node_id)
    if old_endpoint is not None:
        # The registry can contain a transport for another saved target;
        # reconstruct from durable metadata, never from the latest PUT.
        remove_node(node_id, invalidate_slot=False)
        source = SimpleNamespace(
            id=node_id,
            usage_coefficient=dbnode.usage_coefficient,
            **{**old_endpoint, "protocol": NodeProtocol(old_endpoint["protocol"])},
        )
        transport = add_node(source)
    elif transport is None:
        transport = add_node(dbnode)
    if isinstance(saved_session, str) and saved_session:
        transport.adopt_control_session(saved_session)
    with scheduler.metadata(node_id):
        scheduler.check_current(node_id)
        # This worker now owns the old transport for stopping it. A new
        # edit will retire it again before any late session publication.
        vars(transport)["_superseded"] = False
    transport.stop()
    if old_endpoint is not None:
        with scheduler.metadata(node_id):
            # A completed stop is a fact even if a PUT superseded this intent.
            # Persist it before cleanup/starting another endpoint can fail.
            with GetDB() as db:
                current = crud.get_node_by_id(db, node_id)
                if current is None or not current.config_apply_pending:
                    return
                saved = current.config_apply_endpoint
                if isinstance(saved, dict) and all(
                    saved.get(key) == old_endpoint.get(key) for key in ("address", "port", "api_port", "protocol")
                ):
                    current.config_apply_endpoint = {**saved, "stopped": True}
                    db.commit()


def _record_apply_endpoint(node_id, target):
    scheduler = get_node_scheduler()
    # Record the next endpoint BEFORE it can start Xray. A crash or a new
    # PUT during its RPC must recover this endpoint, not the stopped one.
    with scheduler.metadata(node_id):
        scheduler.check_current(node_id)
        with GetDB() as db:
            current = crud.get_node_by_id(db, node_id)
            if current is None:
                return False
            current.config_apply_endpoint = {
                **target,
                "protocol": getattr(target["protocol"], "value", target["protocol"]),
                "control_session_id": None,
            }
            current.control_session_id = None
            db.commit()
    return True


def _apply_node_impl(node_id, config_factory):
    scheduler = get_node_scheduler()
    try:
        scheduler.check_current(node_id)
        with GetDB() as db:
            dbnode = crud.get_node_by_id(db, node_id)
            if dbnode is None:
                usage_state.resume(node_id)
                return False
            disabled = dbnode.status == NodeStatus.disabled
            endpoint = getattr(dbnode, "config_apply_endpoint", None)
            target = {key: getattr(dbnode, key, None) for key in ("address", "port", "api_port", "protocol")}
            old_endpoint = endpoint if isinstance(endpoint, dict) else None
        scheduler.check_current(node_id)
        changed_endpoint = old_endpoint is not None and any(old_endpoint[key] != target[key] for key in target)
        was_stopped = old_endpoint is not None and old_endpoint.get("stopped", False)
        if (disabled or changed_endpoint) and not was_stopped:
            _stop_apply_endpoint(node_id, dbnode, old_endpoint)
        remove_node(node_id, invalidate_slot=False)
        scheduler.check_current(node_id)
        if not disabled:
            if not _record_apply_endpoint(node_id, target):
                usage_state.resume(node_id)
                return False
            if not _connect_node_impl(node_id, force=True, config_factory=config_factory):
                return False
        with scheduler.metadata(node_id):
            scheduler.check_current(node_id)
            with GetDB() as db:
                dbnode = crud.get_node_by_id(db, node_id)
                if dbnode is not None:
                    dbnode.config_apply_pending = False
                    dbnode.config_apply_endpoint = None
                    if disabled:
                        if changed_endpoint:
                            dbnode.control_session_id = None
                        dbnode.message = None
                    db.commit()
            usage_state.resume(node_id)
        return True
    except NodeOperationSuperseded:
        raise
    except Exception as exc:
        with scheduler.metadata(node_id):
            scheduler.check_current(node_id)
            with GetDB() as db:
                dbnode = crud.get_node_by_id(db, node_id)
                if dbnode is not None:
                    dbnode.message = str(exc)
                    if dbnode.status != NodeStatus.disabled:
                        dbnode.status = NodeStatus.error
                    db.commit()
        raise


def node_operation_snapshot():
    if _node_scheduler is None:
        return {"active": 0, "pending": 0, "oldest_pending_seconds": 0, "outcomes": {}}
    return _node_scheduler.snapshot()


def remove_node(node_id: int, *, invalidate_slot: bool = True):
    """Remove local/remote transport after a protected lifecycle mutation.

    Admission cancels queued intents; running REST ownership is never stolen.
    add_node uses invalidate_slot=False inside its existing worker lease.
    """
    with _node_lifecycle_lock(node_id):
        if invalidate_slot:
            invalidate_connect_slot(node_id)
        if node_id in xray.nodes:
            try:
                xray.nodes[node_id].disconnect()
            except Exception:
                pass
            finally:
                try:
                    del xray.nodes[node_id]
                except KeyError:
                    pass


def release_remote_nodes() -> None:
    if _node_scheduler is not None:
        _node_scheduler.shutdown(wait=True)
    logger.info("Releasing node control sessions without stopping remote Xray")
    for node in list(xray.nodes.values()):
        try:
            release = getattr(node, "release_local", None)
            if release is not None:
                release()
        except Exception:
            logger.exception("Failed to release local node transport")


def _persist_control_session(node_id: int, session_id: str | None, *, endpoint=None) -> None:
    with GetDB() as db:
        if endpoint is None:
            crud.set_node_control_session(db, node_id, session_id)
            return
        dbnode = crud.get_node_by_id(db, node_id)
        if dbnode is None:
            return
        saved = dbnode.config_apply_endpoint
        if saved is not None and all(saved[key] == endpoint[key] for key in endpoint):
            dbnode.config_apply_endpoint = {**saved, "control_session_id": session_id}
        if all(getattr(dbnode, key) == value for key, value in endpoint.items()):
            dbnode.control_session_id = session_id
        db.commit()


def add_node(dbnode: "DBNode"):
    # Replace local object only — do not invalidate the connect slot of the caller
    # (connect_node may already hold it after Edit wiped xray.nodes).
    node_id = int(dbnode.id)
    with _node_lifecycle_lock(node_id):
        remove_node(dbnode.id, invalidate_slot=False)

        tls = get_tls()
        node = XRayNode(
            address=dbnode.address,
            port=dbnode.port,
            api_port=dbnode.api_port,
            ssl_key=tls["key"],
            ssl_cert=tls["certificate"],
            protocol=dbnode.protocol,
            usage_coefficient=dbnode.usage_coefficient,
        )
        xray.nodes[dbnode.id] = node
        vars(node)["_operation_check"] = lambda: get_node_scheduler().check_current(node_id)
        vars(node)["_operation_wait"] = lambda delay: get_node_scheduler().wait_current(node_id, delay)
        if hasattr(node, "set_control_session_listener"):
            endpoint = {key: getattr(dbnode, key) for key in ("address", "port", "api_port", "protocol")}

            def persist_session(session_id: str | None) -> None:
                with get_node_scheduler().metadata(node_id):
                    if xray.nodes.get(node_id) is node and not vars(node).get("_superseded", False):
                        _persist_control_session(node_id, session_id, endpoint=endpoint)

            node.set_control_session_listener(persist_session)

        return node


def _change_node_status(node_id: int, status: NodeStatus, message: str = None, version: str = None) -> bool:
    scheduler = get_node_scheduler()
    with scheduler.metadata(node_id):
        if not scheduler.is_current(node_id):
            return False
        with GetDB() as db:
            try:
                dbnode = crud.get_node_by_id(db, node_id)
                if not dbnode:
                    logger.warning("[node.status] node_id=%s not found for status=%s", node_id, status.value)
                    return False

                if dbnode.status == NodeStatus.disabled:
                    logger.info("[node.status] node_id=%s is disabled; status update skipped", node_id)
                    return False

                crud.update_node_status(db, dbnode, status, message, version)
                return True
            except SQLAlchemyError as exc:
                db.rollback()
                logger.error(
                    f"[node.status] failed to update node_id={node_id} status={status.value}: {type(exc).__name__}: {exc}"
                )
                raise


def connecting_age_seconds(node_id: int) -> float | None:
    """Seconds since node entered connecting (DB last_status_change), or None."""
    with GetDB() as db:
        dbnode = crud.get_node_by_id(db, node_id)
        if not dbnode or dbnode.status != NodeStatus.connecting:
            return None
        if not dbnode.last_status_change:
            return None
        return max(0.0, (datetime.utcnow() - dbnode.last_status_change).total_seconds())


global _connecting_nodes
_connecting_nodes: set[int] = set()
_connecting_started_at: dict[int, float] = {}
# Monotonic owner token per node_id: release only clears the slot if the token still matches.
# Idle invalidation bumps the token so an old thread's finally cannot
# drop a newer connect's lock (e.g. Edit → remove_node while a previous connect is in flight).
_connecting_generation: dict[int, int] = {}
_connecting_nodes_lock = threading.Lock()
_connect_semaphore = threading.Semaphore(max(1, XRAY_NODE_CONNECT_CONCURRENCY))


def is_connect_in_progress(node_id: int) -> bool:
    with _connecting_nodes_lock:
        return node_id in _connecting_nodes or (_node_scheduler is not None and _node_scheduler.pending(node_id))


def is_connect_stale(_node_id: int) -> bool:
    # Возраст не доказывает остановку sync-REST. Escalation допустим только
    # после завершения предыдущей команды, по DB age в health-check.
    return False


def _cleanup_node_connection(node) -> None:
    """Reset local session only — do not call remote /disconnect (it stops Xray).

    Used on hard reconnect (force=True). Soft path must not call this on network blips
    so the existing REST session_id can be reused for try_restore / soft start.
    """
    if node is None:
        return
    if hasattr(node, "_reset_local_state"):
        try:
            node._reset_local_state(recreate_session=True)
        except Exception:
            pass
    elif hasattr(node, "disconnect"):
        try:
            node.disconnect()
        except Exception:
            pass


def invalidate_connect_slot(node_id: int) -> None:
    """Cancel waiting intents without releasing a live execution guard."""
    if _node_scheduler is not None:
        _node_scheduler.cancel_pending(node_id)
    with _connecting_nodes_lock:
        if node_id in _connecting_nodes:
            return
        _connecting_generation[node_id] = _connecting_generation.get(node_id, 0) + 1
        _connecting_nodes.discard(node_id)
        _connecting_started_at.pop(node_id, None)


def _acquire_connect_slot(node_id: int, force: bool = False) -> int | None:
    """Execution guard для прямого вызова; работающий владелец не отбирается."""
    now = time.time()
    with _connecting_nodes_lock:
        if node_id in _connecting_nodes:
            logger.debug("[connect.slot] node_id=%s busy, force=%s does not steal ownership", node_id, force)
            return None

        gen = _connecting_generation.get(node_id, 0) + 1
        _connecting_generation[node_id] = gen
        _connecting_nodes.add(node_id)
        _connecting_started_at[node_id] = now
        return gen


def _release_connect_slot(node_id: int, generation: int | None = None):
    with _connecting_nodes_lock:
        if generation is not None and _connecting_generation.get(node_id) != generation:
            logger.debug(
                f"[connect_node] skip release for node_id={node_id}: "
                f"stale generation={generation} current={_connecting_generation.get(node_id)}"
            )
            return
        _connecting_nodes.discard(node_id)
        _connecting_started_at.pop(node_id, None)


def _connect_node_impl(node_id, config=None, force: bool = False, *, config_factory=None):
    slot_gen = _acquire_connect_slot(node_id, force=force)
    if slot_gen is None:
        return

    node_connect_lock = _node_operation_lock(node_id)
    node_connect_lock.acquire()
    dbnode = None
    node = None
    last_exc = None

    node_inbound_tags = []
    saved_session = None
    cascade_kwargs = {"role": "direct"}
    try:
        blocked_user_ids = set()
        with GetDB() as db:
            dbnode = crud.get_node_by_id(db, node_id)
            if dbnode:
                # читаем в открытой сессии, чтобы не словить DetachedInstanceError
                saved_session = dbnode.control_session_id if isinstance(dbnode.control_session_id, str) else None
                node_inbound_tags = [i.tag for i in dbnode.inbounds]
                cascade_kwargs = _cascade_kwargs(db, dbnode)
                blocked_user_ids = _blocked_user_ids(db, node_id)

        get_node_scheduler().check_current(node_id)
        if not dbnode:
            return

        if dbnode.status == NodeStatus.disabled:
            remove_node(dbnode.id)
            logger.info(f"[connect_node] skip disabled node_id={dbnode.id}")
            return

        # Soft retries leave status=connecting; do not rewrite it (would reset last_status_change
        # and wipe xray_version), so health can escalate via connecting_age_seconds.
        if dbnode.status != NodeStatus.connecting:
            status_changed = _change_node_status(node_id, NodeStatus.connecting)
            if not status_changed:
                logger.info(f"[connect_node] status update rejected for node_id={node_id}")
                return

        prepared_json = None

        def prepare_config_json():
            nonlocal config, prepared_json
            if prepared_json is None:
                if config is None:
                    config = config_factory() if config_factory is not None else xray.config.include_db_users()
                prepared_json = node_config_json(config, node_inbound_tags, cascade_kwargs, blocked_user_ids)
            return prepared_json

        # Background/health-check reconnects: one attempt per call; health check retries later.
        # Manual Reconnect (force=True): full in-process retry loop.
        retries = max(1, XRAY_NODE_CONNECT_RETRIES) if force else 1
        retry_delay = max(0, XRAY_NODE_CONNECT_RETRY_DELAY)
        get_node_scheduler().check_current(node_id)
        try:
            node = xray.nodes[dbnode.id]
        except KeyError:
            node = xray.operations.add_node(dbnode)

        if not force and saved_session and not getattr(node, "_session_id", None):
            adopt = getattr(node, "adopt_control_session", None)
            if adopt is not None:
                adopt(saved_session)

        for attempt in range(1, retries + 1):
            get_node_scheduler().check_current(node_id)
            _connect_semaphore.acquire()
            try:
                get_node_scheduler().check_current(node_id)
                path = "HARD" if force else "SOFT"
                has_session = bool(getattr(node, "_session_id", None))
                logger.debug(
                    f'[connect_node] {path} path start node_id={node_id} ("{dbnode.name}") '
                    f"attempt={attempt}/{retries} local_session="
                    f"{'yes' if has_session else 'no'}"
                )

                if force:
                    config_json = prepare_config_json()
                    # HARD: first attempt (or no local session) → new REST session + /restart.
                    # Later retries keep session and only /restart — avoids takeover storm when
                    # /connect succeeded but /restart timed out on a large config upload.
                    if has_session and attempt > 1:
                        logger.debug(
                            f'[connect_node] HARD decision node_id={node_id} ("{dbnode.name}"): '
                            f"reuse session → /restart only (no /connect)"
                        )
                        node.restart(config_json=config_json)
                    else:
                        logger.debug(
                            f'[connect_node] HARD decision node_id={node_id} ("{dbnode.name}"): '
                            f"cleanup local session → /connect → /restart (Xray will stop)"
                        )
                        _cleanup_node_connection(node)
                        node.connect()
                        get_node_scheduler().check_current(node_id)
                        node.restart(config_json=config_json)
                    logger.debug(
                        f'[connect_node] HARD done node_id={node_id} ("{dbnode.name}"): '
                        f"Xray restarted under new session"
                    )
                else:
                    # Soft path: keep existing session if still valid — reattach gRPC only.
                    # Do NOT wipe session_id / call /connect on transient network errors.
                    restored = False
                    try:
                        if hasattr(node, "try_restore"):
                            restored = node.try_restore()
                        get_node_scheduler().check_current(node_id)
                        if restored:
                            logger.debug(
                                f'[connect_node] SOFT decision node_id={node_id} ("{dbnode.name}"): '
                                f"try_restore=OK → reattach only (no /connect, no /start)"
                            )
                        else:
                            # No usable session, or session ok but core down → start().
                            # start() calls /connect only when session is missing/invalid.
                            logger.debug(
                                f'[connect_node] SOFT decision node_id={node_id} ("{dbnode.name}"): '
                                f"try_restore=False → start() "
                                f"( /connect only if session missing/invalid )"
                            )
                            node.start(config_json=prepare_config_json())
                    except NodeOperationSuperseded:
                        raise
                    except Exception as soft_exc:
                        if getattr(node, "_session_id", None):
                            # Session still remembered — do not escalate to error/hard /connect yet.
                            # IMPORTANT: do NOT mark DB status=connected here. That caused fake
                            # "Подключен" without xray_version and blocked recovery (health assumed OK).
                            # Leave status=connecting; health retries soft, then HARD after stale.
                            logger.debug(
                                f'[connect_node] SOFT deferred node_id={node_id} ("{dbnode.name}"): '
                                f"{type(soft_exc).__name__}: {soft_exc}; "
                                f"keep session_id, status=connecting, retry later (no /connect)"
                            )
                            return False
                        logger.debug(
                            f"[connect_node] SOFT failed without session node_id={node_id} "
                            f'("{dbnode.name}"): {type(soft_exc).__name__}: {soft_exc}'
                        )
                        raise

                get_node_scheduler().check_current(node_id)
                node.inbound_tags = set(node_inbound_tags)
                version = node.get_version()
                get_node_scheduler().check_current(node_id)
                if not _change_node_status(node_id, NodeStatus.connected, version=version):
                    get_node_scheduler().check_current(node_id)
                    return False
                logger.debug(f'[connect_node] DONE node_id={node_id} ("{dbnode.name}") path={path} xray=v{version}')
                logger.info(f'Connected to "{dbnode.name}" node, xray run on v{version}')
                return True
            except NodeOperationSuperseded:
                raise
            except Exception as exc:
                last_exc = exc
                if attempt < retries:
                    delay = retry_delay * attempt
                    logger.warning(
                        f"[connect_node] attempt {attempt}/{retries} failed for "
                        f"node_id={node_id} ({dbnode.name}): {type(exc).__name__}: {exc}. "
                        f"retry in {delay}s"
                    )
            finally:
                _connect_semaphore.release()

            if attempt < retries:
                delay = retry_delay * attempt
                if delay:
                    get_node_scheduler().wait_current(node_id, delay)

        if last_exc:
            raise last_exc

    except NodeOperationSuperseded:
        raise
    except Exception as exc:
        try:
            _change_node_status(node_id, NodeStatus.error, message=str(exc))
        except Exception as status_exc:
            logger.error(
                f"[connect_node] failed to mark node_id={node_id} as error: {type(status_exc).__name__}: {status_exc}"
            )
        if dbnode:
            logger.warning(f'Unable to connect to "{dbnode.name}" node: {type(exc).__name__}: {exc}')
        else:
            logger.warning(f"Unable to connect node_id={node_id}: {type(exc).__name__}: {exc}")
        return False
    finally:
        node_connect_lock.release()
        _release_connect_slot(node_id, slot_gen)
        if dbnode:
            try:
                logger.debug(f"[connect_node] released lock for node_id={node_id} ({dbnode.name})")
            except Exception:
                logger.debug(f"[connect_node] released lock for node_id={node_id}")
        else:
            logger.debug(f"[connect_node] released lock for node_id={node_id}")


def connect_node(node_id, config=None, force: bool = False, *, manual: bool = False):
    """config остаётся совместимым аргументом; snapshot свежий только при исполнении."""
    kind = OperationKind.HARD if force else OperationKind.SOFT
    return get_node_scheduler().request(node_id, kind, manual=manual)


def restart_node(node_id, config=None, *, manual: bool = True):
    return get_node_scheduler().request(node_id, OperationKind.RESTART, manual=manual)


def connect_nodes(node_ids):
    return get_node_scheduler().request_many([(node_id, OperationKind.SOFT) for node_id in node_ids])


def _restart_node_impl(node_id, config=None, *, config_factory=None):
    node_inbound_tags = []
    cascade_kwargs = {"role": "direct"}
    blocked_user_ids = set()
    with GetDB() as db:
        dbnode = crud.get_node_by_id(db, node_id)
        if dbnode:
            node_inbound_tags = [i.tag for i in dbnode.inbounds]
            cascade_kwargs = _cascade_kwargs(db, dbnode)
            blocked_user_ids = _blocked_user_ids(db, node_id)

    if not dbnode:
        return

    try:
        node = xray.nodes[dbnode.id]
    except KeyError:
        node = xray.operations.add_node(dbnode)

    if not node.connected:
        logger.debug(
            f'[restart_node] node_id={node_id} ("{dbnode.name}"): not connected → fallback to SOFT connect_node'
        )
        return _connect_node_impl(node_id, config, config_factory=config_factory)

    try:
        logger.info(f'Restarting Xray core of "{dbnode.name}" node')
        logger.debug(
            f'[restart_node] node_id={node_id} ("{dbnode.name}"): POST /restart '
            f"(Xray will stop/start; session kept if ping ok)"
        )

        if config is None:
            config = config_factory() if config_factory is not None else xray.config.include_db_users()

        get_node_scheduler().check_current(node_id)
        node.restart(config_json=node_config_json(config, node_inbound_tags, cascade_kwargs, blocked_user_ids))
        get_node_scheduler().check_current(node_id)
        node.inbound_tags = set(node_inbound_tags)
        logger.debug(f'[restart_node] done node_id={node_id} ("{dbnode.name}")')
        logger.info(f'Xray core of "{dbnode.name}" node restarted')
    except NodeOperationSuperseded:
        raise
    except Exception as e:
        try:
            _change_node_status(node_id, NodeStatus.error, message=str(e))
        except Exception as status_exc:
            logger.error(
                f"[restart_node] failed to mark node_id={node_id} as error: {type(status_exc).__name__}: {status_exc}"
            )
        logger.info(f"Unable to restart node {node_id}")
        try:
            node.disconnect()
        except Exception:
            logger.exception("[restart_node] failed to disconnect node_id=%s", node_id)
        return False


__all__ = [
    "add_user",
    "remove_user",
    "update_user_by_id",
    "remove_user_from_node",
    "add_user_to_node",
    "add_node",
    "remove_node",
    "connect_node",
    "restart_node",
    "is_connect_in_progress",
    "is_connect_stale",
    "invalidate_connect_slot",
    "connecting_age_seconds",
]
