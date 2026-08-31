"""Data contracts. Every Manager-to-agent exchange goes through these models.

Three rules hold everywhere:

* A ScopeToken is issued by the Manager and an agent can never mint one.
* A DataRef points at data and never carries it, so the Manager can plan without
  ever reading a data file.
* A TaskResult that fails validation is rejected outright. The Manager does not
  try to interpret a malformed result.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

URI_SEPARATOR: Final[str] = "://"

TaskStatus = Literal["OK", "FAILED", "HALTED_BUDGET", "BOUNDARY_VIOLATION", "NEEDS_REVIEW"]
DataFormat = Literal["parquet", "csv", "json", "duckdb_table", "blob"]


def _validate_layer_uri(value: str) -> str:
    """Reject anything that is not a layer URI.

    A system path in a contract would tie a run to one machine and let an agent
    address data outside its layer.
    """
    if URI_SEPARATOR not in value:
        raise ValueError(f"Phai la URI dang 'tang://duong/dan', nhan duoc: {value!r}")
    layer, _, remainder = value.partition(URI_SEPARATOR)
    if not layer or not remainder:
        raise ValueError(f"URI thieu ten tang hoac duong dan: {value!r}")
    if remainder.startswith("/"):
        raise ValueError(f"URI khong duoc dung duong dan tuyet doi: {value!r}")
    return value


class Limits(BaseModel):
    """The ceilings a single agent call must stay under."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_rows_dropped_pct: float | None = None
    max_runtime_s: int | None = None
    max_tokens: int | None = None
    max_retries: int = 3


class ScopeToken(BaseModel):
    """The authority the Manager grants an agent for one call.

    An agent receives this; it can never build one for itself.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    task_id: str
    agent_id: str
    allow_read: tuple[str, ...] = ()
    allow_write: tuple[str, ...] = ()
    allow_tools: tuple[str, ...] = ()
    params: dict[str, Any] = Field(default_factory=dict)
    limits: Limits = Limits()
    issued_at: datetime
    expires_at: datetime

    @field_validator("allow_read", "allow_write")
    @classmethod
    def _check_patterns(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for pattern in value:
            _validate_layer_uri(pattern)
        return value

    @model_validator(mode="after")
    def _check_window(self) -> ScopeToken:
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at phai sau issued_at")
        return self

    def is_expired(self, now: datetime | None = None) -> bool:
        """True once the token is past its expiry."""
        moment = now or datetime.now(UTC)
        return moment >= self.expires_at


class DataRef(BaseModel):
    """A pointer to data. It never embeds the data itself."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    format: DataFormat
    content_hash: str
    row_count: int | None = None
    schema_version: str = "1"

    @field_validator("path")
    @classmethod
    def _check_path(cls, value: str) -> str:
        return _validate_layer_uri(value)

    @property
    def layer(self) -> str:
        """The storage layer this reference lives in."""
        return self.path.partition(URI_SEPARATOR)[0]


class EvidenceRef(BaseModel):
    """Where a claim came from. Criterion S4 rests on this."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str
    locator: str
    value: str

    @field_validator("source")
    @classmethod
    def _check_source(cls, value: str) -> str:
        return _validate_layer_uri(value)


class ErrorDetail(BaseModel):
    """Why a task failed, and whether trying again could help."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    message: str
    retryable: bool = False


class TaskRequest(BaseModel):
    """One unit of work handed to an agent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: ScopeToken
    input_refs: tuple[DataRef, ...] = ()
    instruction: str


class TaskResult(BaseModel):
    """What an agent hands back. Anything malformed is rejected, not repaired."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: str
    agent_id: str
    status: TaskStatus
    output_refs: tuple[DataRef, ...] = ()
    metrics: dict[str, float] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)
    evidence: tuple[EvidenceRef, ...] = ()
    error: ErrorDetail | None = None

    @model_validator(mode="after")
    def _check_error_matches_status(self) -> TaskResult:
        if self.status == "OK" and self.error is not None:
            raise ValueError("status OK khong duoc kem error")
        if self.status in {"FAILED", "BOUNDARY_VIOLATION"} and self.error is None:
            raise ValueError(f"status {self.status} bat buoc phai co error")
        return self

    @property
    def is_ok(self) -> bool:
        """True when the agent reported success."""
        return self.status == "OK"
