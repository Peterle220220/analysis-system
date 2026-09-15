"""Append-only audit log, one JSON object per line.

Every line records something that happened, and no line is ever rewritten: the
log is the record of what the system did, so editing it would defeat its only
purpose. Reading it back is how criterion S2 is checked - a run is clean when
the log holds no unresolved BOUNDARY_VIOLATION.

The twelve event names are fixed by the spec. Using a value outside that set is
an error, not a new event type invented on the fly.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from analysis_system.core import storage

AuditEvent = Literal[
    "RUN_STARTED",
    "FILES_ROUTED",
    "PLAN_CREATED",
    "SCOPE_ISSUED",
    "TASK_STARTED",
    "TASK_COMPLETED",
    "EXTRACTION_LOW_CONFIDENCE",
    "VALIDATION_RESULT",
    "BOUNDARY_VIOLATION",
    "BUDGET_WARNING",
    "HUMAN_GATE",
    "RUN_ENDED",
]

REQUIRED_EVENTS: Final[tuple[str, ...]] = (
    "RUN_STARTED",
    "FILES_ROUTED",
    "PLAN_CREATED",
    "SCOPE_ISSUED",
    "TASK_STARTED",
    "TASK_COMPLETED",
    "EXTRACTION_LOW_CONFIDENCE",
    "VALIDATION_RESULT",
    "BOUNDARY_VIOLATION",
    "BUDGET_WARNING",
    "HUMAN_GATE",
    "RUN_ENDED",
)

AUDIT_FILENAME: Final[str] = "audit.jsonl"


class AuditError(RuntimeError):
    """The audit log could not be written or read."""


class AuditRecord(BaseModel):
    """One line of the audit log."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ts: datetime
    run_id: str
    event: AuditEvent
    task_id: str | None = None
    agent_id: str | None = None
    status: str | None = None
    input_hash: str | None = None
    output_hash: str | None = None
    metrics: dict[str, float] = Field(default_factory=dict)
    detail: dict[str, Any] = Field(default_factory=dict)

    def to_line(self) -> str:
        """Serialise to one deterministic JSON line."""
        payload = self.model_dump(mode="json", exclude_none=True)
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)


class AuditLog:
    """Append-only writer and reader for one run."""

    def __init__(self, path: Path, run_id: str) -> None:
        """Bind the log to one file and one run."""
        self._path = path
        self._run_id = run_id

    @property
    def path(self) -> Path:
        """Where the log is written."""
        return self._path

    def record(
        self,
        event: AuditEvent,
        *,
        now: datetime | None = None,
        **fields: Any,
    ) -> AuditRecord:
        """Append one event to the log.

        Args:
            event: one of the twelve names the spec fixes.
            now: timestamp to record; the current time when omitted.
            **fields: any other AuditRecord field.

        Returns:
            The record that was written.

        Raises:
            AuditError: the event name or fields do not validate.
        """
        try:
            entry = AuditRecord(
                ts=now or datetime.now(UTC),
                run_id=self._run_id,
                event=event,
                **fields,
            )
        except ValidationError as error:
            raise AuditError(f"Ban ghi audit khong hop le: {error}") from error
        storage.append_line(entry.to_line(), self._path)
        return entry

    def read_all(self) -> list[AuditRecord]:
        """Read every record back.

        Raises:
            AuditError: a line is not valid JSON or not a valid record.
        """
        if not self._path.is_file():
            return []
        records: list[AuditRecord] = []
        for number, line in enumerate(storage.read_lines(self._path), start=1):
            if not line.strip():
                continue
            try:
                records.append(AuditRecord.model_validate(json.loads(line)))
            except (json.JSONDecodeError, ValidationError) as error:
                raise AuditError(
                    f"Dong {number} cua {self._path} khong doc duoc: {error}"
                ) from error
        return records

    def events(self) -> list[str]:
        """The event names in the order they were written."""
        return [record.event for record in self.read_all()]

    def unresolved_violations(self) -> list[AuditRecord]:
        """Every boundary violation with no later record clearing it.

        Criterion S2 is met when this list is empty.
        """
        return [record for record in self.read_all() if record.event == "BOUNDARY_VIOLATION"]
