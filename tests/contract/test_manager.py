"""Manager tests: state and resume, the verdict rules, and the dispatch trail."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
import yaml

from analysis_system.agents.base import BaseAgent
from analysis_system.contracts.base import (
    DataRef,
    ErrorDetail,
    ScopeToken,
    TaskRequest,
    TaskResult,
)
from analysis_system.manager.dispatcher import Dispatcher
from analysis_system.manager.state import (
    GateDecision,
    RunState,
    StateError,
    StateStore,
    TaskState,
    frozen_tasks,
    should_skip,
)
from analysis_system.manager.verifier import verify
from analysis_system.services.audit import AuditLog
from analysis_system.services.boundary import Manifest, load_manifest
from analysis_system.services.scoped_storage import ScopedStorage
from analysis_system.settings import LAYER_NAMES, LayerPaths, Settings, load_settings

NOW = datetime(2026, 8, 31, 9, 0, tzinfo=UTC)
MANIFEST_DIR = Path(__file__).resolve().parents[2] / "config" / "manifests"

TEST_MANIFEST = {
    "agent_id": "t9_tester",
    "version": 1,
    "allow": {"read": ["staging://**"], "write": ["clean://**"], "tools": ["pandas"]},
    "limits": {"max_rows_dropped_pct": 5, "max_retries": 2},
    "must_return": {"schema": "TestResult", "required_fields": ["rows_out"]},
}


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings with every layer under a throwaway directory."""
    roots = {name: tmp_path / name for name in LAYER_NAMES}
    for root in roots.values():
        root.mkdir(parents=True, exist_ok=True)
    return load_settings().model_copy(update={"layers": LayerPaths(**roots)})


@pytest.fixture
def manifest_dir(tmp_path: Path) -> Path:
    """A directory holding the fake agent manifest."""
    directory = tmp_path / "manifests"
    directory.mkdir()
    (directory / "t9_tester.yaml").write_text(yaml.safe_dump(TEST_MANIFEST), encoding="utf-8")
    return directory


@pytest.fixture
def audit(tmp_path: Path) -> AuditLog:
    """An audit log for the run."""
    run_dir = tmp_path / "runs" / "r_1"
    run_dir.mkdir(parents=True)
    return AuditLog(run_dir / "audit.jsonl", "r_1")


def ref(path: str = "clean://out.parquet", digest: str = "a" * 64) -> DataRef:
    """A minimal data reference."""
    return DataRef(path=path, format="parquet", content_hash=digest)


def result(**overrides: object) -> TaskResult:
    """A clean result from the fake agent."""
    fields: dict[str, object] = {
        "task_id": "t_01",
        "agent_id": "t9_tester",
        "status": "OK",
        "output_refs": (ref(),),
        "metrics": {"rows_dropped_pct": 0.0},
        "payload": {"rows_out": 3},
    }
    fields.update(overrides)
    return TaskResult(**fields)  # type: ignore[arg-type]


def token(scope_agent: str = "t9_tester") -> ScopeToken:
    """A token matching the fake manifest."""
    return ScopeToken(
        run_id="r_1",
        task_id="t_01",
        agent_id=scope_agent,
        allow_read=("staging://**",),
        allow_write=("clean://**",),
        allow_tools=("pandas",),
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )


def fake_manifest(manifest_dir: Path) -> Manifest:
    """Load the fake manifest."""
    return load_manifest("t9_tester", manifest_dir)


# --- state and resume ---------------------------------------------------------


def test_state_round_trips_through_the_file(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    state = RunState(run_id="r_1", created_at=NOW, updated_at=NOW)
    state = state.with_task(TaskState(task_id="t_01", agent_id="a2_profiler", phase="OK"))
    store.save(state)
    assert store.load().tasks["t_01"].phase == "OK"


def test_a_finished_task_with_unchanged_inputs_is_skipped() -> None:
    state = RunState(run_id="r_1", created_at=NOW, updated_at=NOW).with_task(
        TaskState(task_id="t_01", agent_id="a2_profiler", phase="OK", input_hashes=("h1",))
    )
    assert should_skip(state, "t_01", ("h1",))


def test_a_finished_task_whose_input_changed_is_rerun() -> None:
    # Resuming onto different data would silently mix two runs together.
    state = RunState(run_id="r_1", created_at=NOW, updated_at=NOW).with_task(
        TaskState(task_id="t_01", agent_id="a2_profiler", phase="OK", input_hashes=("h1",))
    )
    assert not should_skip(state, "t_01", ("h2",))


def test_a_failed_task_is_never_skipped() -> None:
    state = RunState(run_id="r_1", created_at=NOW, updated_at=NOW).with_task(
        TaskState(task_id="t_01", agent_id="a2_profiler", phase="FAILED", input_hashes=("h1",))
    )
    assert not should_skip(state, "t_01", ("h1",))


def test_an_unknown_task_is_never_skipped() -> None:
    state = RunState(run_id="r_1", created_at=NOW, updated_at=NOW)
    assert not should_skip(state, "t_99", ())


def test_a_gate_decision_is_stored_as_data_and_replayed(tmp_path: Path) -> None:
    # Without this, a run containing a gate could never be reproducible.
    store = StateStore(tmp_path / "state.json")
    state = RunState(run_id="r_1", created_at=NOW, updated_at=NOW).with_gate(
        GateDecision(gate_id="gate_1", approved=("trim_whitespace",), decided_at=NOW)
    )
    store.save(state)
    replayed = store.load()
    assert replayed.gates["gate_1"].approved == ("trim_whitespace",)


def test_loading_state_from_a_different_run_is_refused(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    store.save(RunState(run_id="r_1", created_at=NOW, updated_at=NOW))
    with pytest.raises(StateError, match="r_1"):
        store.load_or_create("r_2")


def test_load_or_create_starts_a_fresh_run_when_there_is_nothing(tmp_path: Path) -> None:
    state = StateStore(tmp_path / "state.json").load_or_create("r_new", now=NOW)
    assert state.run_id == "r_new"
    assert state.phase == "RUNNING"
    assert state.tasks == {}


# --- verdicts -----------------------------------------------------------------


def test_a_clean_result_passes(manifest_dir: Path) -> None:
    verdict = verify(result(), fake_manifest(manifest_dir), token(), attempts=1)
    assert verdict.decision == "PASS"
    assert verdict.accepted


def test_a_boundary_violation_is_escalated_never_retried(manifest_dir: Path) -> None:
    violation = result(
        status="BOUNDARY_VIOLATION",
        output_refs=(),
        payload={},
        error=ErrorDetail(code="BOUNDARY_RUNTIME", message="ghi ra raw://"),
    )
    verdict = verify(violation, fake_manifest(manifest_dir), token(), attempts=1)
    assert verdict.decision == "ESCALATE"


def test_a_budget_halt_is_escalated_never_retried(manifest_dir: Path) -> None:
    halted = result(status="HALTED_BUDGET", output_refs=(), payload={})
    verdict = verify(halted, fake_manifest(manifest_dir), token(), attempts=1)
    assert verdict.decision == "ESCALATE"


def test_a_retryable_failure_is_retried_within_the_ceiling(manifest_dir: Path) -> None:
    failure = result(
        status="FAILED",
        output_refs=(),
        payload={},
        error=ErrorDetail(code="TIMEOUT", message="qua han", retryable=True),
    )
    assert verify(failure, fake_manifest(manifest_dir), token(), attempts=1).decision == "RETRY"


def test_a_retryable_failure_escalates_once_the_ceiling_is_spent(manifest_dir: Path) -> None:
    failure = result(
        status="FAILED",
        output_refs=(),
        payload={},
        error=ErrorDetail(code="TIMEOUT", message="qua han", retryable=True),
    )
    assert verify(failure, fake_manifest(manifest_dir), token(), attempts=2).decision == "ESCALATE"


def test_a_non_retryable_failure_escalates_immediately(manifest_dir: Path) -> None:
    failure = result(
        status="FAILED",
        output_refs=(),
        payload={},
        error=ErrorDetail(code="BAD_INPUT", message="schema sai", retryable=False),
    )
    assert verify(failure, fake_manifest(manifest_dir), token(), attempts=1).decision == "ESCALATE"


def test_dropping_too_many_rows_is_retried_then_escalated(manifest_dir: Path) -> None:
    greedy = result(metrics={"rows_dropped_pct": 12.0})
    manifest = fake_manifest(manifest_dir)
    assert verify(greedy, manifest, token(), attempts=1).decision == "RETRY"
    assert verify(greedy, manifest, token(), attempts=2).decision == "ESCALATE"


def test_needs_review_goes_to_a_human_gate(manifest_dir: Path) -> None:
    review = result(status="NEEDS_REVIEW")
    assert verify(review, fake_manifest(manifest_dir), token(), attempts=1).decision == "GATE"


# --- dispatch -----------------------------------------------------------------


class TinyAgent(BaseAgent):
    """Writes one small table where it is allowed to."""

    agent_id = "t9_tester"

    def execute(self, request: TaskRequest, files: ScopedStorage) -> TaskResult:
        written = files.save_parquet(pd.DataFrame({"x": [1, 2, 3]}), "clean://out.parquet")
        return TaskResult(
            task_id=request.scope.task_id,
            agent_id=self.agent_id,
            status="OK",
            output_refs=(written,),
            metrics={"rows_out": 3.0, "rows_dropped_pct": 0.0},
            payload={"rows_out": 3},
        )


def test_a_token_is_cut_from_the_manifest_not_assembled_by_hand(
    audit: AuditLog, manifest_dir: Path
) -> None:
    dispatcher = Dispatcher("r_1", audit)
    issued = dispatcher.issue_scope("t_01", fake_manifest(manifest_dir), now=NOW)
    assert issued.allow_write == ("clean://**",)
    assert issued.allow_tools == ("pandas",)
    assert issued.limits.max_retries == 2
    assert "SCOPE_ISSUED" in audit.events()


def test_dispatch_writes_the_full_audit_trail(
    settings: Settings, audit: AuditLog, manifest_dir: Path
) -> None:
    dispatcher = Dispatcher("r_1", audit)
    manifest = fake_manifest(manifest_dir)
    scope = dispatcher.issue_scope("t_01", manifest, now=NOW)
    outcome = dispatcher.dispatch(TinyAgent(settings, manifest_dir), scope, now=NOW)

    assert outcome.is_ok, outcome.error
    assert audit.events() == ["SCOPE_ISSUED", "TASK_STARTED", "TASK_COMPLETED"]
    completed = audit.read_all()[-1]
    assert completed.status == "OK"
    assert completed.output_hash is not None


def test_a_refused_agent_is_logged_as_a_boundary_violation(
    settings: Settings, audit: AuditLog, manifest_dir: Path
) -> None:
    dispatcher = Dispatcher("r_1", audit)
    manifest = fake_manifest(manifest_dir)
    scope = dispatcher.issue_scope("t_01", manifest, now=NOW)
    # Run far past the token expiry so pre-flight refuses.
    outcome = dispatcher.dispatch(
        TinyAgent(settings, manifest_dir), scope, now=NOW + timedelta(hours=2)
    )
    assert outcome.status == "BOUNDARY_VIOLATION"
    assert "BOUNDARY_VIOLATION" in audit.events()
    assert audit.unresolved_violations()


# --- which tasks are facts rather than proposals -------------------------------


def test_a_finished_task_is_frozen() -> None:
    state = RunState(run_id="r", created_at=NOW, updated_at=NOW).with_task(
        TaskState(task_id="a", agent_id="a1_ingest", phase="OK"), now=NOW
    )
    assert frozen_tasks(state) == {"a"}


def test_a_task_waiting_on_a_person_is_frozen() -> None:
    state = RunState(run_id="r", created_at=NOW, updated_at=NOW).with_task(
        TaskState(task_id="a", agent_id="a3_cleaner", phase="AWAITING_APPROVAL"), now=NOW
    )
    assert frozen_tasks(state) == {"a"}


def test_a_task_whose_gate_was_answered_is_frozen() -> None:
    # The decision is about that task. Rewriting it would change what a person
    # approved into something they did not.
    state = RunState(run_id="r", created_at=NOW, updated_at=NOW).with_gate(
        GateDecision(gate_id="gate_a", approved=("x",), decided_at=NOW), now=NOW
    )
    assert frozen_tasks(state) == {"a"}


def test_a_task_that_only_failed_is_not_frozen() -> None:
    # Nothing settled about it, and rewriting it is the point of replanning.
    state = RunState(run_id="r", created_at=NOW, updated_at=NOW).with_task(
        TaskState(task_id="a", agent_id="a7_analyst", phase="FAILED"), now=NOW
    )
    assert frozen_tasks(state) == set()
