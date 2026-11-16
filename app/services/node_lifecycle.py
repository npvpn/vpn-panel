"""Изменение ноды исключает переподключение и необратимый сбор статистики."""

from collections.abc import Callable
from contextlib import contextmanager

from app import xray
from app.db import Session, crud
from app.db.models import Node
from app.models.node import NodeModify, NodeStatus
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
    with _mutation(int(dbnode.id)):
        updated = crud.update_node(db, dbnode, modified_node)
        xray.operations.remove_node(int(updated.id))
        if updated.status != NodeStatus.disabled:
            schedule(xray.operations.connect_node, node_id=updated.id, force=True, manual=True)
    return updated


def remove_node(db: Session, dbnode: Node) -> None:
    with _mutation(int(dbnode.id)):
        crud.remove_node(db, dbnode)
        xray.operations.remove_node(int(dbnode.id))
