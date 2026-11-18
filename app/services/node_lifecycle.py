"""Изменение ноды исключает переподключение и необратимый сбор статистики."""

from collections.abc import Callable
from contextlib import contextmanager

from app import logger, xray
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
    with scheduler.metadata(node_id):
        with scheduler.edit(node_id), usage_state.edit(node_id):
            updated = crud.update_node(db, dbnode, modified_node, commit=False)
            db.commit()
            transport = xray.nodes.get(node_id)
            if transport is not None:
                vars(transport)["_superseded"] = True
        # Commit and admission belong to one save. Refresh can fail after commit
        # without letting the superseded worker acknowledge the new settings.
        xray.operations.apply_node(node_id, accounting=usage_state)
    db.refresh(updated)
    return updated


def remove_node(db: Session, dbnode: Node) -> None:
    node_id = int(dbnode.id)
    with _mutation(node_id):
        paused = usage_state.is_paused(node_id)
        try:
            crud.remove_node(db, dbnode)
        except BaseException:
            db.rollback()
            if paused:
                try:
                    # Re-admit while mutation still excludes a concurrent save.
                    # Dispatch happens when the mutation guard is released.
                    xray.operations.apply_node(node_id, accounting=usage_state, recover=True)
                except Exception:
                    logger.exception("Failed to recover pending apply after delete failure: node_id=%s", node_id)
            raise
        else:
            try:
                xray.operations.remove_node(node_id)
            finally:
                usage_state.resume(node_id)
