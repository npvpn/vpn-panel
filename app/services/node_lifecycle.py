"""Изменение ноды исключает переподключение и необратимый сбор статистики."""

from collections.abc import Callable
from contextlib import contextmanager

from app import xray
from app.db import Session, crud
from app.db.models import Node
from app.models.node import NodeModify
from app.utils.usage_runtime import UsageBusyError, usage_state
from app.xray.node_operations import NodeBusyError


@contextmanager
def _mutation(node_id: int):
    try:
        # Check accounting first: a rejected edit must not cancel a reconnect.
        with usage_state.mutation(node_id), xray.operations.node_mutation(node_id):
            try:
                yield
            finally:
                usage_state.retire_node(node_id)
    except UsageBusyError as exc:
        raise NodeBusyError() from exc


def modify_node(db: Session, dbnode: Node, modified_node: NodeModify, schedule: Callable[..., None]) -> Node:
    node_id = int(dbnode.id)
    scheduler = xray.operations.get_node_scheduler()
    with scheduler.edit(node_id), usage_state.edit(node_id):
        updated = crud.update_node(db, dbnode, modified_node)
        transport = xray.nodes.get(node_id)
        if transport is not None:
            vars(transport)["_superseded"] = True
    # Only admission here: no network or waiting in the HTTP thread pool.
    xray.operations.apply_node(node_id, accounting=usage_state)
    return updated


def remove_node(db: Session, dbnode: Node) -> None:
    with _mutation(int(dbnode.id)):
        try:
            crud.remove_node(db, dbnode)
            xray.operations.remove_node(int(dbnode.id))
        finally:
            # Only after admission: rejected deletes preserve pending edits.
            usage_state.resume(int(dbnode.id))
