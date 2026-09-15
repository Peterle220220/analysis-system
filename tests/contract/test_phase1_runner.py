"""End-to-end Phase 1: profile, pause at the gate, clean only what was approved.

This is where the Phase 1 definition of done is proved: a run that stops for a
human, survives being killed, resumes exactly where it stopped, and replays the
decision instead of asking twice.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from analysis_system.contracts.agents import ProfileInterpretation, ProposedRule, RuleProposal
from analysis_system.contracts.base import DataRef
from analysis_system.core import storage
from analysis_system.core.audit import AUDIT_FILENAME, AuditLog
from analysis_system.core.hashing import canonical_hash
from analysis_system.core.settings import LAYER_NAMES, LayerPaths, Settings, load_settings, resolve
from analysis_system.manager.gates import (
    GateError,
    GateStore,
    approved_rules_from,
    decide,
)
from analysis_system.manager.runner import GATE_RULES, TASK_CLEAN, TASK_PROFILE, Phase1Runner
from analysis_system.manager.state import StateStore
from analysis_system.services.llm import LlmClient, LlmRequest, LlmResponse

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
MANIFEST_DIR = Path(__file__).resolve().parents[2] / "config" / "manifests"
RUN_ID = "r_phase1"

PROPOSAL = RuleProposal(
    rules=[
        ProposedRule(rule_id="trim_whitespace", columns=("case_id",), reason="co khoang trang"),
        ProposedRule(rule_id="drop_exact_duplicates", reason="co dong trung"),
        ProposedRule(rule_id="normalize_unicode_nfc", reason="chuan hoa chu"),
    ],
    summary="ba rule de xuat",
)


class FixedProvider:
    """Answers with a fixed proposal, so the test is about orchestration only."""

    name = "test"

    def __init__(self, proposal: RuleProposal = PROPOSAL) -> None:
        self._proposal = proposal
        self.calls = 0

    def complete(self, request: LlmRequest) -> LlmResponse:
        self.calls += 1
        data = self._proposal if request.schema is RuleProposal else ProfileInterpretation()
        return LlmResponse(data=data, provider=self.name, model="test")


def frame() -> pd.DataFrame:
    """Forty rows with whitespace and one duplicate pair."""
    rows = [
        {"case_id": f"c{index}", "activity": "Create", "amount": str(index)}
        for index in range(1, 40)
    ]
    rows[0]["case_id"] = "  c1  "
    rows.append(dict(rows[-1]))
    return pd.DataFrame(rows)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    roots = {name: tmp_path / name for name in LAYER_NAMES}
    for root in roots.values():
        root.mkdir(parents=True, exist_ok=True)
    return load_settings().model_copy(update={"layers": LayerPaths(**roots)})


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    return tmp_path / "runs" / RUN_ID


@pytest.fixture
def source(settings: Settings) -> DataRef:
    data = frame()
    storage.write_parquet(data, resolve("staging://events.parquet", settings))
    return DataRef(
        path="staging://events.parquet",
        format="parquet",
        content_hash=canonical_hash(data),
        row_count=len(data.index),
    )


def runner(
    settings: Settings, run_dir: Path, provider: FixedProvider | None = None
) -> Phase1Runner:
    """A fresh runner, as a new process would build one."""
    llm = LlmClient(provider) if provider else None
    return Phase1Runner(settings, run_dir, llm=llm, manifest_dir=MANIFEST_DIR)


# --- the pause ----------------------------------------------------------------


def test_the_first_run_stops_at_the_gate_and_cleans_nothing(
    settings: Settings, run_dir: Path, source: DataRef
) -> None:
    outcome = runner(settings, run_dir, FixedProvider()).run(source, run_id=RUN_ID, now=NOW)

    assert outcome.is_paused
    assert outcome.paused_gate == GATE_RULES
    assert outcome.state.phase == "PAUSED_AWAITING_APPROVAL"
    # A2 finished; A3 has only proposed.
    assert outcome.state.tasks[TASK_PROFILE].phase == "OK"
    assert outcome.state.tasks[TASK_CLEAN].phase == "AWAITING_APPROVAL"
    assert not (settings.layers.clean / "events.parquet").exists()
    assert (settings.layers.profile / f"{RUN_ID}_profile.json").is_file()


def test_the_gate_file_lists_what_is_being_asked(
    settings: Settings, run_dir: Path, source: DataRef
) -> None:
    runner(settings, run_dir, FixedProvider()).run(source, run_id=RUN_ID, now=NOW)
    request = GateStore(run_dir).read(GATE_RULES)
    assert request.option_ids == (
        "trim_whitespace",
        "drop_exact_duplicates",
        "normalize_unicode_nfc",
    )
    assert request.payload["proposal"]["summary"] == "ba rule de xuat"


def test_the_process_exits_rather_than_waiting_for_a_person(
    settings: Settings, run_dir: Path, source: DataRef
) -> None:
    # The whole point of the two-step design: run() returns, it does not block.
    outcome = runner(settings, run_dir, FixedProvider()).run(source, run_id=RUN_ID, now=NOW)
    assert outcome.is_paused
    assert not outcome.is_complete


# --- approving and resuming ---------------------------------------------------


def approve(run_dir: Path, approved: tuple[str, ...], rejected: tuple[str, ...] = ()) -> None:
    """Record a decision exactly as the CLI approve command will."""
    gates = GateStore(run_dir)
    states = StateStore(run_dir / "state.json")
    state = states.load()
    decision = decide(
        gates.read(GATE_RULES), approved=approved, rejected=rejected, now=NOW + timedelta(minutes=1)
    )
    states.save(state.with_gate(decision, now=NOW + timedelta(minutes=1)))


def test_resuming_runs_only_the_approved_rules(
    settings: Settings, run_dir: Path, source: DataRef
) -> None:
    runner(settings, run_dir, FixedProvider()).run(source, run_id=RUN_ID, now=NOW)
    approve(run_dir, ("trim_whitespace",), rejected=("drop_exact_duplicates",))

    # A brand new runner, as a separate command would create.
    outcome = runner(settings, run_dir, FixedProvider()).run(
        source, run_id=RUN_ID, now=NOW + timedelta(minutes=2)
    )

    assert outcome.is_complete
    cleaned = outcome.results[-1]
    assert cleaned.payload["rules_applied"] == ["trim_whitespace"]
    # De-duplication was rejected, so the duplicate row is still there.
    assert cleaned.payload["rows_out"] == 40
    assert (settings.layers.clean / "events.parquet").is_file()


def test_approving_everything_cleans_everything(
    settings: Settings, run_dir: Path, source: DataRef
) -> None:
    runner(settings, run_dir, FixedProvider()).run(source, run_id=RUN_ID, now=NOW)
    approve(run_dir, ("trim_whitespace", "drop_exact_duplicates", "normalize_unicode_nfc"))
    outcome = runner(settings, run_dir, FixedProvider()).run(
        source, run_id=RUN_ID, now=NOW + timedelta(minutes=2)
    )
    assert outcome.is_complete
    assert outcome.results[-1].payload["rows_out"] == 39


def test_a_decision_cannot_approve_something_never_proposed(
    settings: Settings, run_dir: Path, source: DataRef
) -> None:
    # Otherwise a rule nobody suggested could be slipped into the run.
    runner(settings, run_dir, FixedProvider()).run(source, run_id=RUN_ID, now=NOW)
    with pytest.raises(GateError, match="khong he de xuat"):
        approve(run_dir, ("cast_numeric_safe",))


# --- resume, the point of criterion S3 ----------------------------------------


def test_a_killed_run_resumes_without_redoing_finished_work(
    settings: Settings, run_dir: Path, source: DataRef
) -> None:
    first = FixedProvider()
    runner(settings, run_dir, first).run(source, run_id=RUN_ID, now=NOW)
    profile_calls_before = first.calls
    approve(run_dir, ("trim_whitespace",))

    # Simulates the process dying and a new one starting on the same run id.
    second = FixedProvider()
    outcome = runner(settings, run_dir, second).run(
        source, run_id=RUN_ID, now=NOW + timedelta(minutes=2)
    )

    assert outcome.is_complete
    assert profile_calls_before > 0
    # A2 already succeeded on the same input, so it is not asked again.
    assert TASK_PROFILE not in {result.task_id for result in outcome.results}


def test_rerunning_a_finished_run_replays_the_decision_instead_of_asking(
    settings: Settings, run_dir: Path, source: DataRef
) -> None:
    # This is what makes a run containing a gate reproducible at all.
    runner(settings, run_dir, FixedProvider()).run(source, run_id=RUN_ID, now=NOW)
    approve(run_dir, ("trim_whitespace",))
    runner(settings, run_dir, FixedProvider()).run(
        source, run_id=RUN_ID, now=NOW + timedelta(minutes=2)
    )

    third = FixedProvider()
    outcome = runner(settings, run_dir, third).run(
        source, run_id=RUN_ID, now=NOW + timedelta(minutes=5)
    )
    assert outcome.is_complete
    assert not outcome.is_paused
    # Nothing was re-run and nothing was re-asked.
    assert outcome.results == ()
    assert third.calls == 0


def test_changed_input_forces_the_work_to_run_again(
    settings: Settings, run_dir: Path, source: DataRef
) -> None:
    runner(settings, run_dir, FixedProvider()).run(source, run_id=RUN_ID, now=NOW)
    approve(run_dir, ("trim_whitespace",))
    runner(settings, run_dir, FixedProvider()).run(
        source, run_id=RUN_ID, now=NOW + timedelta(minutes=2)
    )

    changed = source.model_copy(update={"content_hash": "b" * 64})
    outcome = runner(settings, run_dir, FixedProvider()).run(
        changed, run_id=RUN_ID, now=NOW + timedelta(minutes=5)
    )
    # Resuming onto different data must not reuse the old outputs.
    assert TASK_PROFILE in {result.task_id for result in outcome.results}


# --- the audit trail ----------------------------------------------------------


def test_the_audit_log_records_the_whole_story(
    settings: Settings, run_dir: Path, source: DataRef
) -> None:
    runner(settings, run_dir, FixedProvider()).run(source, run_id=RUN_ID, now=NOW)
    approve(run_dir, ("trim_whitespace",))
    runner(settings, run_dir, FixedProvider()).run(
        source, run_id=RUN_ID, now=NOW + timedelta(minutes=2)
    )

    events = AuditLog(run_dir / AUDIT_FILENAME, RUN_ID).events()
    for required in (
        "RUN_STARTED",
        "PLAN_CREATED",
        "SCOPE_ISSUED",
        "TASK_STARTED",
        "TASK_COMPLETED",
        "VALIDATION_RESULT",
        "HUMAN_GATE",
        "RUN_ENDED",
    ):
        assert required in events, f"thieu event {required}"
    assert events[0] == "RUN_STARTED"
    assert events[-1] == "RUN_ENDED"


def test_no_boundary_violation_is_recorded_on_a_clean_run(
    settings: Settings, run_dir: Path, source: DataRef
) -> None:
    # Criterion S2: a clean run leaves no unresolved violation behind.
    runner(settings, run_dir, FixedProvider()).run(source, run_id=RUN_ID, now=NOW)
    approve(run_dir, ("trim_whitespace",))
    runner(settings, run_dir, FixedProvider()).run(
        source, run_id=RUN_ID, now=NOW + timedelta(minutes=2)
    )
    assert AuditLog(run_dir / AUDIT_FILENAME, RUN_ID).unresolved_violations() == []


SPLIT_PROPOSAL = RuleProposal(
    rules=[
        ProposedRule(rule_id="cast_numeric_safe", columns=("price",), reason="do luong"),
        ProposedRule(
            rule_id="cast_numeric_safe", columns=("yr_renovated",), reason="nam, 0 la chua"
        ),
        ProposedRule(rule_id="trim_whitespace", columns=("city",), reason="khoang trang"),
    ],
    summary="mot rule tach lam hai nhom, mot rule rieng",
)


def test_a_rule_proposed_once_keeps_its_plain_id(
    settings: Settings, run_dir: Path, source: DataRef
) -> None:
    runner(settings, run_dir, FixedProvider()).run(source, run_id=RUN_ID, now=NOW)
    request = GateStore(run_dir).read(GATE_RULES)
    assert "trim_whitespace" in request.option_ids


def ids_for(option_ids: set[str], rule_id: str) -> list[str]:
    """Every option that is that rule, however the gate happened to number it.

    `trim_whitespace` becomes `trim_whitespace#1` the moment a second one is
    proposed. The suffix is a position in a list, not a fact about the rule, so
    a test that names it is testing the numbering.
    """
    return sorted(item for item in option_ids if item.split("#")[0] == rule_id)


def test_a_rule_proposed_twice_becomes_two_options(
    settings: Settings, run_dir: Path, source: DataRef
) -> None:
    # The proposal split them on purpose; the gate has to let them be judged apart.
    runner(settings, run_dir, FixedProvider(SPLIT_PROPOSAL)).run(source, run_id=RUN_ID, now=NOW)
    request = GateStore(run_dir).read(GATE_RULES)

    # Asserted as the property rather than as the exact list: the examination
    # seeds rules of its own - the fixture really does hold duplicate rows and
    # untrimmed text - and a test pinned to the literal set breaks every time
    # the measurements find one more thing worth asking about. The numbering is
    # positional too: a second trim_whitespace turns `trim_whitespace` into
    # `trim_whitespace#1`, which changes no property this test is about.
    proposed = set(request.option_ids)
    assert len(ids_for(proposed, "cast_numeric_safe")) == 2
    assert ids_for(proposed, "trim_whitespace")


def test_approving_one_group_takes_that_group_alone(
    settings: Settings, run_dir: Path, source: DataRef
) -> None:
    runner(settings, run_dir, FixedProvider(SPLIT_PROPOSAL)).run(source, run_id=RUN_ID, now=NOW)
    request = GateStore(run_dir).read(GATE_RULES)
    decision = decide(request, approved=("cast_numeric_safe#2",), now=NOW)
    selected = approved_rules_from(request, decision)
    assert len(selected) == 1
    assert selected[0]["columns"] == ["yr_renovated"]


def test_approving_a_split_group_and_a_plain_rule_together(
    settings: Settings, run_dir: Path, source: DataRef
) -> None:
    runner(settings, run_dir, FixedProvider(SPLIT_PROPOSAL)).run(source, run_id=RUN_ID, now=NOW)
    request = GateStore(run_dir).read(GATE_RULES)
    trimming = ids_for(set(request.option_ids), "trim_whitespace")[0]
    decision = decide(request, approved=("cast_numeric_safe#1", trimming), now=NOW)
    selected = approved_rules_from(request, decision)
    assert [rule["rule_id"] for rule in selected] == ["cast_numeric_safe", "trim_whitespace"]
    assert selected[0]["columns"] == ["price"]
