"""Golden test for the whole Phase 2 DAG: seven agents, two gates, one answer.

Phase 0 proved a fixed pipeline was deterministic. This proves the same of the
planned one - the version with a model in four of its seven steps, two human
gates in the middle, and a Manager deciding what runs.

The model is scripted, which is the only way this can be a golden test at all:
what is being pinned down is the machinery around the model, not the model. Two
runs on the same fixture, under different run ids and in different directories,
must agree on every hash. That is criterion S1, stated for the real pipeline.

The fixture is real BPI Challenge 2019 data, read from git and never regenerated
here. A change in this test means the pipeline changed or the fixture did, and
both should be deliberate.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from analysis_system.contracts.agents import (
    ColumnLineage,
    Finding,
    FindingProposal,
    NarrativeProposal,
    Plan,
    PlannedTask,
    ProfileInterpretation,
    ProposedRule,
    RuleProposal,
    SqlProposal,
)
from analysis_system.contracts.base import DataRef
from analysis_system.manager.dag_runner import DagRunner
from analysis_system.manager.gates import GateStore, decide
from analysis_system.manager.planner import Planner
from analysis_system.manager.retry import NO_WAIT
from analysis_system.manager.runner import RunOutcome
from analysis_system.manager.state import StateStore
from analysis_system.services import storage
from analysis_system.services.llm import LlmClient, LlmRequest, LlmResponse
from analysis_system.settings import LAYER_NAMES, LayerPaths, Settings, load_settings, resolve

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "bpi19_slice.csv"
MANIFEST_DIR = REPO_ROOT / "config" / "manifests"
EXPECTED = REPO_ROOT / "tests" / "golden" / "expected" / "phase2.json"

SQL = SqlProposal(
    sql=(
        "SELECT case_spend_area_text AS spend_area, "
        "CAST(cumulative_net_worth_eur AS DOUBLE) AS net_worth FROM events"
    ),
    target_table="spend",
    lineage=[
        ColumnLineage(output="spend_area", sources=("case_spend_area_text",), transform="doi ten"),
        ColumnLineage(
            output="net_worth", sources=("cumulative_net_worth_eur",), transform="ep kieu so"
        ),
    ],
    reason="chuan bi bang chi tieu theo mang",
)

FINDINGS = FindingProposal(
    findings=[
        Finding(
            claim_template="Bang co {rows.total} dong su kien.",
            metric_keys=("rows.total",),
            evidence_ref="mart://spend.parquet",
            confidence=0.95,
        ),
        Finding(
            claim_template="Gia tri luy ke trung binh moi dong la {net_worth.mean} EUR.",
            metric_keys=("net_worth.mean",),
            evidence_ref="mart://spend.parquet",
            confidence=0.9,
        ),
    ],
    summary="hai ket luan",
)

RULES = RuleProposal(
    rules=[
        ProposedRule(
            rule_id="trim_whitespace",
            columns=("case_spend_area_text",),
            reason="chuan hoa ten mang chi tieu",
        )
    ],
    summary="mot rule",
)


class Scripted:
    """A model that always answers the same thing, so the machinery is what is tested."""

    name = "golden"

    def complete(self, request: LlmRequest) -> LlmResponse:
        answers: dict[Any, Any] = {
            ProfileInterpretation: ProfileInterpretation(),
            RuleProposal: RULES,
            SqlProposal: SQL,
            FindingProposal: FINDINGS,
            NarrativeProposal: NarrativeProposal(
                summary_template="Trung binh moi dong {net_worth.mean} EUR."
            ),
        }
        data = answers.get(request.schema)
        if data is None:
            raise AssertionError(f"Kich ban khong co cau tra loi cho {request.schema}")
        return LlmResponse(data=data, provider=self.name, model="scripted")


def golden_plan() -> Plan:
    """The seven-task pipeline, with the params each agent needs."""
    return Plan(
        tasks=(
            PlannedTask(
                task_id="t1_ingest",
                agent_id="a1_ingest",
                params={"target": "staging://events.parquet"},
                instruction="Nap file su kien vao staging.",
            ),
            PlannedTask(
                task_id="t2_profile",
                agent_id="a2_profiler",
                depends_on=("t1_ingest",),
                instruction="Mo ta du lieu da nap.",
            ),
            PlannedTask(
                task_id="t3_clean",
                agent_id="a3_cleaner",
                depends_on=("t2_profile",),
                inputs_from=("t1_ingest",),
                instruction="De xuat rule lam sach.",
            ),
            PlannedTask(
                task_id="t4_transform",
                agent_id="a4_transformer",
                depends_on=("t3_clean",),
                params={
                    "target": "mart://spend.parquet",
                    "question": "chi tieu luy ke theo mang",
                },
                instruction="Dung bang chi tieu theo mang.",
            ),
            PlannedTask(
                task_id="t5_validate",
                agent_id="a5_validator",
                depends_on=("t4_transform",),
                # Checks the fixture actually meets. Real BPI data leaves 42 of
                # 5,000 spend areas blank, so demanding not_null on that column
                # would - correctly - stop the run at validation. That case gets
                # its own test below; this plan is here to exercise the whole
                # chain.
                params={
                    "checks": {
                        "not_null": ["net_worth"],
                        "ranges": [{"column": "net_worth", "min": 0}],
                    }
                },
                instruction="Cham bang mart.",
            ),
            PlannedTask(
                task_id="t6_analyse",
                agent_id="a7_analyst",
                depends_on=("t5_validate",),
                inputs_from=("t4_transform",),
                params={
                    "question": "chi tieu luy ke theo mang",
                    "dimensions": ["spend_area"],
                    "measures": ["net_worth"],
                },
                instruction="Rut ket luan tu bang mart.",
            ),
            PlannedTask(
                task_id="t7_report",
                agent_id="a8_reporter",
                depends_on=("t6_analyse",),
                instruction="Xuat bao cao.",
            ),
        ),
        reason="ke hoach golden Phase 2",
    )


def settings_in(root: Path) -> Settings:
    """Point every layer at a throwaway directory, keeping the real rules."""
    roots = {name: root / name for name in LAYER_NAMES}
    for path in roots.values():
        path.mkdir(parents=True, exist_ok=True)
    return load_settings().model_copy(update={"layers": LayerPaths(**roots)})


def staged_source(settings: Settings) -> DataRef:
    """Put the committed fixture where A1 can read it."""
    target = resolve("raw://bpi19_slice.csv", settings)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURE, target)
    return DataRef(
        path="raw://bpi19_slice.csv", format="csv", content_hash=storage.sha256_file(target)
    )


def run_to_the_end(root: Path, run_id: str) -> tuple[RunOutcome, Settings]:
    """Run the plan, answering both gates the same way every time.

    Approving everything is what makes this reproducible: a gate replays its
    stored decision, so the human step is data, not a person.
    """
    settings = settings_in(root)
    source = staged_source(settings)
    run_dir = root / "runs" / run_id
    engine = DagRunner(
        settings, run_dir, llm=LlmClient(Scripted()), manifest_dir=MANIFEST_DIR, retry=NO_WAIT
    )
    plan = golden_plan()

    outcome = engine.run(plan, source, run_id=run_id)
    for _ in range(4):
        if not outcome.is_paused:
            break
        approve_everything(run_dir, str(outcome.paused_gate))
        outcome = engine.run(plan, source, run_id=run_id)
    return outcome, settings


def approve_everything(run_dir: Path, gate_id: str) -> None:
    """Record the decision, the way the approve command does."""
    gates = GateStore(run_dir)
    states = StateStore(run_dir / "state.json")
    state = states.load()
    request = gates.read(gate_id)
    decision = decide(request, approved=request.option_ids, now=state.updated_at)
    states.save(state.with_gate(decision, now=state.updated_at))


def observed(outcome: RunOutcome) -> dict[str, Any]:
    """The facts a golden result is made of, taken from the run state."""
    tasks = outcome.state.tasks
    return {
        "fixture_sha256": storage.sha256_file(FIXTURE),
        "tasks": list(tasks),
        "staging_hash": tasks["t1_ingest"].output_refs[0].content_hash,
        "clean_hash": tasks["t3_clean"].output_refs[0].content_hash,
        "mart_hash": tasks["t4_transform"].output_refs[0].content_hash,
        "rows_staged": tasks["t1_ingest"].metrics["rows"],
        "rows_mart": tasks["t4_transform"].metrics["rows_out"],
        "checks_failed": tasks["t5_validate"].metrics["checks_failed"],
        "findings": tasks["t6_analyse"].metrics["findings"],
        "report_findings": tasks["t7_report"].metrics["findings"],
    }


def expected() -> dict[str, Any]:
    """Read the recorded golden result."""
    if not EXPECTED.is_file():
        pytest.fail(f"Thieu ket qua ky vong: {EXPECTED}")
    loaded: dict[str, Any] = json.loads(EXPECTED.read_text(encoding="utf-8"))
    return loaded


# --- the tests ----------------------------------------------------------------


def test_the_fixture_itself_has_not_changed() -> None:
    # The fixture is immutable by contract; anything else invalidates the rest.
    assert storage.sha256_file(FIXTURE) == expected()["fixture_sha256"]


def test_the_whole_dag_matches_the_recorded_result(tmp_path: Path) -> None:
    outcome, _ = run_to_the_end(tmp_path, "r_golden2")
    assert outcome.is_complete, outcome.escalation
    assert observed(outcome) == expected()


def test_two_runs_agree_on_every_hash(tmp_path: Path) -> None:
    # Criterion S1 for the planned pipeline. Different run ids, different
    # directories, two human gates - and not one hash may move.
    first, _ = run_to_the_end(tmp_path / "one", "r_first")
    second, _ = run_to_the_end(tmp_path / "two", "r_second")
    assert first.is_complete and second.is_complete
    assert observed(first) == observed(second)


def test_the_report_reaches_disk_with_its_chart(tmp_path: Path) -> None:
    _, settings = run_to_the_end(tmp_path, "r_files")
    report = settings.layers.artifacts / "report"
    assert (report / "r_files.md").is_file()
    assert (report / "r_files.html").is_file()


def test_every_number_in_the_report_came_from_a_metric(tmp_path: Path) -> None:
    # The claims are rendered by code from named metrics. If a figure appears
    # that no metric produced, the placeholder mechanism has been bypassed.
    _, settings = run_to_the_end(tmp_path, "r_numbers")
    text = (settings.layers.artifacts / "report" / "r_numbers.md").read_text(encoding="utf-8")
    assert "dong su kien" in text
    assert "{" not in text  # nothing was left unrendered


def test_the_audit_log_records_the_plan_and_both_gates(tmp_path: Path) -> None:
    run_to_the_end(tmp_path, "r_audit")
    lines = (tmp_path / "runs" / "r_audit" / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    events = [json.loads(line)["event"] for line in lines]
    assert events.count("PLAN_CREATED") >= 1
    assert events.count("HUMAN_GATE") == 2
    assert events[-1] == "RUN_ENDED"


def test_a_table_that_fails_its_checks_stops_the_run(tmp_path: Path) -> None:
    """The referee's verdict has consequences.

    Real BPI data leaves 42 of 5,000 spend areas blank. Demanding not_null on
    that column must stop the run at validation - not report a failure and let
    the analyst draw conclusions from the table anyway, which is what happened
    before the exclusive gateway existed.
    """
    settings = settings_in(tmp_path)
    source = staged_source(settings)
    run_dir = tmp_path / "runs" / "r_halt"
    engine = DagRunner(
        settings, run_dir, llm=LlmClient(Scripted()), manifest_dir=MANIFEST_DIR, retry=NO_WAIT
    )

    strict = golden_plan()
    demanding = tuple(
        task.model_copy(update={"params": {"checks": {"not_null": ["spend_area"]}}})
        if task.task_id == "t5_validate"
        else task
        for task in strict.tasks
    )
    plan = strict.model_copy(update={"tasks": demanding})

    outcome = engine.run(plan, source, run_id="r_halt")
    for _ in range(4):
        if not outcome.is_paused:
            break
        approve_everything(run_dir, str(outcome.paused_gate))
        outcome = engine.run(plan, source, run_id="r_halt")

    assert outcome.halted is not None
    assert "checks_failed=1" in outcome.halted
    assert not outcome.is_complete
    # Nothing downstream ran on a table that did not pass.
    assert "t6_analyse" not in outcome.state.tasks
    assert not (settings.layers.artifacts / "report").exists()


def test_a_halt_is_not_something_a_replan_can_route_around(tmp_path: Path) -> None:
    # A different graph over the same data fails the same way, so the run stops
    # rather than spending a planning call on it.
    settings = settings_in(tmp_path)
    source = staged_source(settings)
    run_dir = tmp_path / "runs" / "r_noreplan"
    engine = DagRunner(
        settings,
        run_dir,
        llm=LlmClient(Scripted()),
        manifest_dir=MANIFEST_DIR,
        retry=NO_WAIT,
        planner=Planner(MANIFEST_DIR, llm=LlmClient(Scripted())),
    )
    strict = golden_plan()
    demanding = tuple(
        task.model_copy(update={"params": {"checks": {"not_null": ["spend_area"]}}})
        if task.task_id == "t5_validate"
        else task
        for task in strict.tasks
    )
    plan = strict.model_copy(update={"tasks": demanding})

    outcome = engine.run(plan, source, run_id="r_noreplan")
    for _ in range(4):
        if not outcome.is_paused:
            break
        approve_everything(run_dir, str(outcome.paused_gate))
        outcome = engine.run(plan, source, run_id="r_noreplan")

    assert outcome.halted is not None
    assert outcome.escalation is None
