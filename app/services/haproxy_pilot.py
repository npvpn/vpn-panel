"""Долговечное намерение панели, отдельное от владельца жизненного цикла Xray."""

import hashlib
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app import xray
from app.db.models import Node, PilotOperation, ProxyInbound
from app.models.haproxy_pilot import (
    PilotCommand,
    PilotHistory,
    PilotIntent,
    PilotResult,
    PilotState,
    PilotTarget,
    PilotView,
)
from app.models.node import NodeProtocol, NodeStatus
from app.xray.node import NodeAPIError, ReSTXRayNode


def conflict(detail: str):
    return HTTPException(409, detail)


@dataclass(frozen=True)
class Peer:
    node: ReSTXRayNode
    session_id: str
    endpoint: dict

    def request(self, path: str, **params):
        if getattr(self.node, "_superseded", False) or self.node._session_id != self.session_id:
            raise NodeAPIError(0, "Сессия ноды изменилась")
        return self.node.pilot_request(self.session_id, path, **params)


class PilotService:
    def __init__(self, sessions: sessionmaker[Session], node_id: int):
        self.sessions = sessions
        self.node_id = node_id

    def _peer(self) -> Peer | None:
        with self.sessions() as db:
            node = db.get(Node, self.node_id)
            if node is None:
                raise HTTPException(404, "Нода не найдена")
            if node.protocol != NodeProtocol.rest:
                return None
            transport = xray.nodes.get(self.node_id)
            if (
                not isinstance(transport, ReSTXRayNode)
                or node.config_apply_pending
                or node.config_apply_endpoint
                or node.status != NodeStatus.connected
                or getattr(transport, "_superseded", False)
                or not node.control_session_id
                or node.control_session_id != transport._session_id
                or (node.address, node.port, node.api_port) != (transport.address, transport.port, transport.api_port)
                or not getattr(transport, "_node_cert", None)
            ):
                raise NodeAPIError(0, "Нет действующей REST-сессии для этого адреса ноды")
            endpoint = dict(
                address=transport.address,
                port=transport.port,
                api_port=transport.api_port,
                certificate=hashlib.sha256(transport._node_cert.encode()).hexdigest(),
            )
            return Peer(transport, node.control_session_id, endpoint)

    def _capable_peer(self):
        peer = self._peer()
        if peer is None:
            return None
        info = peer.request("/")
        if not isinstance(info, dict):
            raise NodeAPIError(0, "Нода вернула некорректные сведения")
        capabilities = info.get("capabilities", {})
        if not isinstance(capabilities, dict):
            raise NodeAPIError(0, "Не удалось прочитать возможности ноды")
        version = capabilities.get("haproxy_pilot")
        return peer if type(version) is int and version == 1 else None

    def _state(self, peer: Peer):
        try:
            state = PilotState.model_validate(peer.request("/haproxy-pilot/status"))
        except ValidationError as exc:
            raise NodeAPIError(0, "Некорректный статус маршрута") from exc
        if peer != self._peer():
            raise NodeAPIError(0, "Сессия ноды изменилась во время наблюдения")
        with self.sessions() as db:
            self._check_history(db, state)
        return state

    def _check_history(self, db: Session, state: PilotState):
        latest = db.scalars(
            select(PilotOperation)
            .where(
                PilotOperation.node_id == self.node_id,
                PilotOperation.archived_at.is_(None),
                PilotOperation.outcome == "applied",
            )
            .order_by(PilotOperation.revision.desc())
            .limit(1)
        ).first()
        if not latest or latest.revision is None:
            return
        if state.revision < latest.revision:
            raise NodeAPIError(0, "Ревизия ноды старше подтверждённой панелью")
        if state.revision == latest.revision:
            destination = state.confirmed_destination or state.targets.get(latest.target)
            if (state.enabled, state.target) != (latest.enabled, latest.target) or not self._matches_target(
                latest, destination
            ):
                raise NodeAPIError(0, "Статус ноды расходится с подтверждённой историей")

    @staticmethod
    def _matches_target(row: PilotOperation, target: PilotTarget | None):
        return target is not None and (target.exit_node_id, target.inbound_tag, target.address, target.port) == (
            row.exit_node_id,
            row.inbound_tag,
            row.target_address,
            row.target_port,
        )

    def _view(self, supported: bool, state: PilotState | None, operation_id: UUID | None = None):
        with self.sessions() as db:
            records = db.scalars(
                select(PilotOperation)
                .where(PilotOperation.node_id == self.node_id, PilotOperation.archived_at.is_(None))
                .order_by(PilotOperation.created_at.desc(), PilotOperation.operation_id.desc())
                .limit(100)
            )
            history = [PilotHistory.model_validate(row) for row in records]
            if operation_id is not None and all(row.operation_id != operation_id for row in history):
                addressed = db.get(PilotOperation, str(operation_id))
                if addressed and addressed.node_id == self.node_id and addressed.archived_at is None:
                    history.append(PilotHistory.model_validate(addressed))
            return PilotView(supported=supported, state=state, history=history)

    def _pending(self):
        with self.sessions() as db:
            return db.scalar(select(PilotOperation).where(PilotOperation.pending_node_id == self.node_id))

    def _record_result(self, row: PilotOperation, payload: object):
        try:
            result = PilotResult.model_validate(payload)
        except ValidationError as exc:
            raise NodeAPIError(0, "Не удалось проверить результат операции") from exc
        if str(result.operation_id) != row.operation_id or (
            result.outcome == "applied" and result.revision != row.expected_revision + 1
        ):
            raise NodeAPIError(0, "Результат не соответствует отправленной операции")
        with self.sessions.begin() as db:
            db.execute(
                update(PilotOperation)
                .where(
                    PilotOperation.operation_id == row.operation_id,
                    PilotOperation.outcome == "pending",
                    PilotOperation.archived_at.is_(None),
                )
                .values(
                    outcome=result.outcome,
                    detail=result.detail,
                    revision=result.revision,
                    pending_node_id=self.node_id if result.outcome == "pending" else None,
                )
            )

    def _reconcile(self, peer: Peer, row: PilotOperation, state: PilotState | None = None) -> bool:
        if row.endpoint != peer.endpoint:
            raise NodeAPIError(0, "Для сверки операции нужен прежний адрес и сертификат ноды")
        try:
            result = peer.request("/haproxy-pilot/result", operation_id=row.operation_id)
        except NodeAPIError as exc:
            if exc.status_code != 404:
                raise
            if state is None or state.revision <= row.expected_revision:
                return False
            # Result was read AFTER observing a newer revision. Even an in-flight
            # copy of the original command cannot be accepted at that old revision.
            self._record_result(
                row,
                dict(
                    operation_id=row.operation_id,
                    outcome="rejected",
                    revision=state.revision,
                    detail="Нода перешла на новую ревизию без применения этой операции",
                ),
            )
            return True
        # The result endpoint addresses only the UUID. A known UUID on the node
        # bypasses preflight in validate and compares the full original command.
        validation = peer.request("/haproxy-pilot/validate", **self._wire_command(row))
        if not isinstance(validation, dict) or validation.get("valid") is not True:
            raise NodeAPIError(0, "Нода не подтвердила параметры сохранённой операции")
        self._record_result(row, result)
        return True

    def status(self) -> PilotView:
        pending = self._pending()
        try:
            peer = self._capable_peer()
            if peer is None:
                return self._view(False, None)
            state = self._state(peer)
            if pending and self._reconcile(peer, pending, state):
                state = self._state(peer)
            return self._view(True, state)
        except NodeAPIError as exc:
            if pending:
                return self._view(True, None)
            raise HTTPException(503, "Не удалось проверить состояние маршрута на ноде") from exc

    def _existing(self, db: Session, command: PilotCommand):
        row = db.get(PilotOperation, str(command.operation_id))
        if row and row.archived_at is not None:
            raise conflict("Операция относится к удалённой регистрации ноды")
        if row and command.expected_destination and not self._matches_target(row, command.expected_destination):
            raise conflict("UUID уже использован с другим назначением")
        if row and (row.node_id, row.expected_revision, row.target, row.enabled) != (
            self.node_id,
            command.expected_revision,
            command.target,
            command.enabled,
        ):
            raise conflict("UUID уже использован с другими параметрами")
        return row

    def _binding(self, db: Session, target: PilotTarget):
        exit_node = db.get(Node, target.exit_node_id)
        if (
            exit_node is None
            or exit_node.status == NodeStatus.disabled
            or db.scalar(select(ProxyInbound.id).where(ProxyInbound.tag == target.inbound_tag)) is None
            or (exit_node.inbounds and target.inbound_tag not in [inbound.tag for inbound in exit_node.inbounds])
        ):
            raise conflict("Назначение не связано с действующей выходной нодой и инбаундом панели")

    def _reserve(self, command: PilotCommand, operator: str, state: PilotState, peer: Peer):
        with self.sessions() as db:
            # Lock serializes competing inserts on MySQL. The unique pending_node_id
            # also protects SQLite and different panel processes during a retry.
            if db.get_bind().dialect.name == "sqlite":
                # SQLite ignores FOR UPDATE. Take the writer lock before reading
                # the registration, including against concurrent delete/re-create.
                db.connection().exec_driver_sql("BEGIN IMMEDIATE")
            registration = db.scalar(select(Node).where(Node.id == self.node_id).with_for_update())
            if (
                registration is None
                or registration.control_session_id != peer.session_id
                or registration.config_apply_pending
                or (registration.address, registration.port, registration.api_port)
                != (peer.node.address, peer.node.port, peer.node.api_port)
            ):
                raise conflict("Регистрация или сессия ноды изменилась")
            row = self._existing(db, command)
            if row:
                return row, False
            closing_current = (
                not command.enabled and command.target == state.target and state.confirmed_destination is not None
            )
            target = state.confirmed_destination if closing_current else state.targets.get(command.target)
            if state.revision != command.expected_revision:
                raise conflict("Ревизия маршрута изменилась")
            if target is None:
                raise conflict("Назначение отсутствует в политике ноды")
            if command.expected_destination is not None and command.expected_destination != target:
                raise conflict("Назначение изменилось после просмотра. Обновите статус маршрута")
            if state.listener in ("unknown", "external"):
                raise conflict("Владелец слушателя не подтверждён")
            self._check_history(db, state)
            if not closing_current:
                self._binding(db, target)
            row = PilotOperation(
                **command.model_dump(mode="json", exclude={"expected_destination"}),
                node_id=self.node_id,
                pending_node_id=self.node_id,
                operator=operator,
                endpoint=peer.endpoint,
                target_address=target.address,
                target_port=target.port,
                exit_node_id=target.exit_node_id,
                inbound_tag=target.inbound_tag,
                outcome="pending",
                detail="Ожидается подтверждение ноды",
            )
            db.add(row)
            try:
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                other = self._existing(db, command)
                if other:
                    return other, False
                raise conflict("Дождитесь результата предыдущей операции") from exc
            db.refresh(row)
            return row, True

    @staticmethod
    def _wire_command(row: PilotOperation):
        command = PilotIntent.model_validate(row, from_attributes=True)
        return {
            **command.model_dump(mode="json"),
            "expected_destination": {
                "exit_node_id": row.exit_node_id,
                "inbound_tag": row.inbound_tag,
                "address": row.target_address,
                "port": row.target_port,
            },
        }

    def _dispatch(self, peer: Peer, row: PilotOperation):
        if peer != self._peer() or peer.endpoint != row.endpoint:
            raise NodeAPIError(0, "Сессия или адрес ноды изменились")
        body = self._wire_command(row)
        try:
            # Apply journals the exact candidate before the node runs preflight.
            # A separate preflight here could reject a command which a concurrent
            # retry already has in flight.
            result = peer.request("/haproxy-pilot/apply", **body)
        except NodeAPIError as exc:
            if exc.status_code not in (409, 422):
                raise
            # Another request with the same UUID could already have applied the
            # candidate. A result in the node's journal takes precedence.
            if self._reconcile(peer, row, self._state(peer)):
                return
            raise
        self._record_result(row, result)

    def apply(self, command: PilotCommand, operator: str) -> PilotView:
        with self.sessions() as db:
            row = self._existing(db, command)
        try:
            peer = self._capable_peer()
            if peer is None:
                raise conflict("Нода не поддерживает управление маршрутом")
            created = False
            if row is None:
                row, created = self._reserve(command, operator, self._state(peer), peer)
            if row.outcome == "pending":
                # Retries use the original authorized candidate. The node compares
                # it with its *current* policy under its journal lock and durably
                # rejects a removed/remapped target without running a worker.
                if created or not self._reconcile(peer, row):
                    self._dispatch(peer, row)
            return self._view(True, self._state(peer), command.operation_id)
        except NodeAPIError as exc:
            if row:
                return self._view(True, None, command.operation_id)
            raise HTTPException(503, "Не удалось подтвердить состояние ноды") from exc
