"""Контракт управления одним TCP-слушателем на ноде."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

Revision = Annotated[int, Field(strict=True, ge=0, le=2147483647)]
Port = Annotated[int, Field(strict=True, ge=1, le=65535)]
Name = Annotated[str, Field(min_length=1, max_length=256)]
Outcome = Literal["pending", "applied", "rejected", "rollback_failed"]


class PilotIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: UUID
    expected_revision: Revision
    target: Name
    enabled: StrictBool


class PilotTarget(BaseModel):
    address: Name
    port: Port
    exit_node_id: Annotated[int, Field(strict=True, gt=0, le=2147483647)]
    inbound_tag: Name


class PilotCommand(PilotIntent):
    expected_destination: PilotTarget | None = None


class PilotState(BaseModel):
    revision: Revision
    target: Name | None
    enabled: StrictBool
    listen_address: Name
    listen_port: Port
    confirmed_destination: PilotTarget | None = None
    targets: dict[Name, PilotTarget]
    listener: Literal["up", "down", "external", "unknown"]
    backend: Literal["up", "down", "unknown"]

    @model_validator(mode="after")
    def current_target_exists(self):
        if (
            (self.enabled or self.target is not None)
            and self.target not in self.targets
            and self.confirmed_destination is None
        ):
            raise ValueError("Current target missing from policy")
        return self


class PilotResult(BaseModel):
    operation_id: UUID
    outcome: Outcome
    revision: Revision | None
    detail: Annotated[str, Field(max_length=4096)]


class PilotHistory(PilotResult, PilotIntent):
    model_config = ConfigDict(from_attributes=True)
    operator: str
    created_at: datetime
    exit_node_id: int
    inbound_tag: str
    target_address: str
    target_port: int


class PilotView(BaseModel):
    supported: bool
    state: PilotState | None
    history: list[PilotHistory]
