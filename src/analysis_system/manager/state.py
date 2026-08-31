"""Run state: what has happened, and what may be skipped when a run resumes.

State is written after every task so a run killed in the middle can pick up
where it stopped (criterion S3). A task is skipped on resume only when it
finished OK *and* the hashes of its inputs are unchanged - resuming onto
different data would silently mix two runs together.

Human decisions are stored here as data. Re-running the same run id replays the
stored decision instead of asking again, which is what makes a run with a gate
in it reproducible at all (criterion S1).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from analysis_system.contracts.base import DataRef, ErrorDetail
from analysis_system.services import storage

STATE_FILENAME: Final[str] = "state.json"

TaskPhase = Literal[
    "PENDING",
    "RUNNING",
    "OK",
    "FAILED",
    "BOUNDARY_VIOLATION",
    "HALTED_BUDGET",
    "AWAITING_APPROVAL",
]

RunPhase = Literal["RUNNING", "PAUSED_AWAITING_APPROVAL", "COMPLETED", "HALTED"]


class StateError(RuntimeError):
    """The state file is missing, malformed, or inconsistent."""


class TaskState(BaseModel):
    """What is known about one task."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: str
    agent_id: str
    phase: TaskPhase = "PENDING"
    attempts: int = 0
    input_hashes: tuple[str, ...] = ()
    output_refs: tuple[DataRef, ...] = ()
    metrics: dict[str, float] = Field(default_factory=dict)
    error: ErrorDetail | None = None
    updated_at: datetime | None = None

    @property
    def is_done(self) -> bool:
        """True when the task completed successfully."""
        return self.phase == "OK"


class GateDecision(BaseModel):
    """One human approval, recorded so it can be replayed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    gate_id: str
    approved: tuple[str, ...] = ()
    rejected: tuple[str, ...] = ()
    note: str = ""
    decided_at: datetime


class RunState(BaseModel):
    """Everything the Manager knows about one run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    phase: RunPhase = "RUNNING"
    created_at: datetime
    updated_at: datetime
    # What the run was started on. Stored so resuming never has to be told
    # again, and so a resume onto different data can be spotted.
    source: DataRef | None = None
    tasks: dict[str, TaskState] = Field(default_factory=dict)
    gates: dict[str, GateDecision] = Field(default_factory=dict)

    def with_source(self, source: DataRef) -> RunState:
        """Return a new state remembering the input it was started on."""
        return self.model_copy(update={"source": source})

    def task(self, task_id: str) -> TaskState | None:
        """Look up one task, if it is known."""
        return self.tasks.get(task_id)

    def with_task(self, task: TaskState, *, now: datetime | None = None) -> RunState:
        """Return a new state with one task replaced."""
        tasks = dict(self.tasks)
        tasks[task.task_id] = task
        return self.model_copy(update={"tasks": tasks, "updated_at": now or datetime.now(UTC)})

    def with_gate(self, decision: GateDecision, *, now: datetime | None = None) -> RunState:
        """Return a new state with one gate decision recorded."""
        gates = dict(self.gates)
        gates[decision.gate_id] = decision
        return self.model_copy(update={"gates": gates, "updated_at": now or datetime.now(UTC)})

    def with_phase(self, phase: RunPhase, *, now: datetime | None = None) -> RunState:
        """Return a new state in a different run phase."""
        return self.model_copy(update={"phase": phase, "updated_at": now or datetime.now(UTC)})


def should_skip(state: RunState, task_id: str, input_hashes: tuple[str, ...]) -> bool:
    """True when a resumed run may skip this task.

    Both conditions must hold: the task finished OK, and its inputs hash to
    exactly what they hashed to last time. A changed input means the stored
    output no longer describes the data, so the task has to run again.
    """
    task = state.task(task_id)
    if task is None or not task.is_done:
        return False
    return task.input_hashes == input_hashes


class StateStore:
    """Reads and writes runs/<run_id>/state.json."""

    def __init__(self, path: Path) -> None:
        """Bind the store to one state file."""
        self._path = path

    @property
    def path(self) -> Path:
        """Where the state is written."""
        return self._path

    def exists(self) -> bool:
        """True when a previous run left state behind."""
        return self._path.is_file()

    def load(self) -> RunState:
        """Read the stored state.

        Raises:
            StateError: the file is missing or does not validate.
        """
        if not self._path.is_file():
            raise StateError(f"Khong tim thay state: {self._path}")
        try:
            return RunState.model_validate_json(storage.read_text(self._path))
        except ValidationError as error:
            raise StateError(f"State {self._path} khong hop le:\n{error}") from error

    def save(self, state: RunState) -> Path:
        """Write the state atomically, so a kill never truncates it."""
        payload = state.model_dump_json(indent=2)
        return storage.write_text(payload, self._path)

    def load_or_create(self, run_id: str, *, now: datetime | None = None) -> RunState:
        """Load an existing run, or start a new one."""
        if self.exists():
            stored = self.load()
            if stored.run_id != run_id:
                raise StateError(
                    f"State tai {self._path} thuoc run {stored.run_id!r}, khong phai {run_id!r}."
                )
            return stored
        moment = now or datetime.now(UTC)
        return RunState(run_id=run_id, created_at=moment, updated_at=moment)
