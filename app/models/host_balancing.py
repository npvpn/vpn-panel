"""Проверяемый контракт настроек клиентской балансировки хоста."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    TypeAdapter,
    ValidationInfo,
    field_validator,
)

_DURATION = re.compile(r"(\d+(?:\.\d*)?|\.\d+)(ns|us|µs|μs|ms|s|m|h)")
_UNITS = {
    "ns": Decimal("0.000000001"),
    "us": Decimal("0.000001"),
    "µs": Decimal("0.000001"),
    "μs": Decimal("0.000001"),
    "ms": Decimal(".001"),
    "s": Decimal(1),
    "m": Decimal(60),
    "h": Decimal(3600),
}
_URL = TypeAdapter(AnyHttpUrl)


def duration_seconds(value: str) -> Decimal:
    """Неотрицательный Go duration в диапазоне int64 наносекунд."""
    if value == "0":
        return Decimal(0)
    parts = list(_DURATION.finditer(value))
    if not parts or "".join(p.group() for p in parts) != value:
        raise ValueError("Use a duration such as 200ms, 15s or 1m30s")
    result = sum((Decimal(p[1]) * _UNITS[p[2]] for p in parts), Decimal(0))
    if result > Decimal(2**63 - 1) / Decimal(10**9):
        raise ValueError("Duration exceeds Xray limit")
    return result


class _Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_default=True)


class BalancerCost(_Settings):
    match: str = Field(min_length=1)
    regexp: StrictBool = False
    value: Annotated[StrictFloat, Field(gt=0)]


class LeastLoadSettings(_Settings):
    expected: Annotated[StrictInt, Field(ge=0, le=2**31 - 1)] = 2
    maxRTT: str = "1s"
    tolerance: Annotated[StrictFloat, Field(ge=0, le=1)] = 0.1
    baselines: list[str] = Field(default_factory=list)
    costs: list[BalancerCost] = Field(default_factory=list)

    @field_validator("maxRTT")
    @classmethod
    def valid_max_rtt(cls, value):
        duration_seconds(value)
        return value

    @field_validator("baselines")
    @classmethod
    def valid_baselines(cls, values):
        if any(duration_seconds(v) <= 0 for v in values):
            raise ValueError("Baselines must be positive durations")
        return values


class PingProbe(_Settings):
    url: str = "https://www.google.com/generate_204"
    interval: str = "15s"
    enableConcurrency: StrictBool = False

    @field_validator("url")
    @classmethod
    def valid_url(cls, value):
        _URL.validate_python(value)
        return value

    @field_validator("interval")
    @classmethod
    def valid_interval(cls, value):
        if duration_seconds(value) <= 0:
            raise ValueError("Interval must be positive")
        return value


class BurstProbe(_Settings):
    url: str = "https://www.google.com/generate_204"
    interval: str = "15s"
    timeout: str = "3s"
    sampling: Annotated[StrictInt, Field(ge=1, le=2**31 - 1)] = 3
    connectivity: str = ""

    @field_validator("url", "connectivity")
    @classmethod
    def valid_url(cls, value, info):
        if value or info.field_name == "url":
            _URL.validate_python(value)
        return value

    @field_validator("interval", "timeout")
    @classmethod
    def valid_duration(cls, value, info):
        seconds = duration_seconds(value)
        if seconds <= 0 or (info.field_name == "interval" and seconds < 10):
            raise ValueError("Use a positive duration; burst interval must be at least 10s")
        return value


class HostBalancing(_Settings):
    strategy: Literal["random", "roundRobin", "leastPing", "leastLoad"]
    settings: LeastLoadSettings | None = None
    probe: PingProbe | BurstProbe | None = None

    @field_validator("settings", mode="before")
    @classmethod
    def strategy_settings(cls, value, info: ValidationInfo):
        if info.data.get("strategy") == "leastLoad":
            return LeastLoadSettings.model_validate(value if value is not None else {})
        if value is not None:
            raise ValueError("Only leastLoad accepts strategy settings")
        return None

    @field_validator("probe", mode="before")
    @classmethod
    def strategy_probe(cls, value, info: ValidationInfo):
        strategy = info.data.get("strategy")
        if strategy == "leastLoad":
            return BurstProbe.model_validate(value if value is not None else {})
        if strategy == "leastPing":
            return PingProbe.model_validate(value if value is not None else {})
        if value is not None:
            raise ValueError("This strategy does not use a probe")
        return None
