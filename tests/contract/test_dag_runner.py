"""End-to-end Phase 2: a whole plan, two human gates, retries, and a replan.

This is where the Phase 2 definition of done is proved. A run walks a planned
DAG from a raw file to a report, stops twice for a person, survives being
killed, and resumes without redoing what already succeeded.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

import pandas as pd
import pytest

from analysis_system.agents.base import BaseAgent
from analysis_system.core import storage
from analysis_system.core.audit import AUDIT_FILENAME
from analysis_system.core.boundary import LlmPolicy, load_manifest
from analysis_system.core.budget import load_pricing
from analysis_system.core.scoped_storage import ScopedStorage
from analysis_system.core.settings import LAYER_NAMES, LayerPaths, Settings, load_settings, resolve
from analysis_system.manager import dag_runner
from analysis_system.manager.dag_runner import (
    DagError,
    DagRunner,
    choose_model,
    gate_id_for,
)
from analysis_system.manager.gates import GateStore, decide
from analysis_system.manager.planner import Planner
from analysis_system.manager.retry import NO_WAIT, RetryPolicy
from analysis_system.manager.state import StateStore
from analysis_system.models.agents import (
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
from analysis_system.models.base import DataRef, ErrorDetail, TaskRequest, TaskResult
from analysis_system.services.llm import (
    LlmClient,
    LlmRequest,
    LlmResponse,
    TransientLlmError,
)

NOW = datetime(2026, 8, 31, 21, 0, tzinfo=UTC)
MANIFEST_DIR = Path(__file__).resolve().parents[2] / "config" / "manifests"
REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_ID = "r_dag"

SQL = SqlProposal(
    # The cleaned table takes its name from the staged one, so a statement
    # written against it stays valid from one run to the next.
    sql="SELECT city, CAST(price AS DOUBLE) AS price FROM houses",
    target_table="houses",
    lineage=[
        ColumnLineage(output="city", sources=("city",), transform="giu nguyen"),
        ColumnLineage(output="price", sources=("price",), transform="ep kieu so"),
    ],
    reason="chuan bi bang gia theo thanh pho",
)

FINDINGS = FindingProposal(
    findings=[
        Finding(
            claim_template="Gia trung binh la {price.mean}.",
            metric_keys=("price.mean",),
            evidence_ref="mart://houses.parquet",
            confidence=0.9,
        ),
        Finding(
            claim_template="Seattle chiem {city.Seattle.share_pct} phan tram so dong.",
            metric_keys=("city.Seattle.share_pct",),
            evidence_ref="mart://houses.parquet",
            confidence=0.8,
        ),
    ],
    summary="hai ket luan",
)

RULES = RuleProposal(
    rules=[ProposedRule(rule_id="trim_whitespace", columns=("city",), reason="co khoang trang")],
    summary="mot rule",
)


class Scripted:
    """Answers every agent, each according to the schema it asked for."""

    name = "test"

    def __init__(self, *, findings: FindingProposal = FINDINGS, plan: Plan | None = None) -> None:
        self._findings = findings
        self._plan = plan
        self.purposes: list[str] = []

    def complete(self, request: LlmRequest) -> LlmResponse:
        self.purposes.append(request.purpose)
        answers: dict[Any, Any] = {
            ProfileInterpretation: ProfileInterpretation(),
            RuleProposal: RULES,
            SqlProposal: SQL,
            FindingProposal: self._findings,
            NarrativeProposal: NarrativeProposal(summary_template="Trung binh {price.mean}."),
            Plan: self._plan,
        }
        data = answers.get(request.schema)
        if data is None:
            raise AssertionError(f"Khong co cau tra loi cho {request.schema}")
        return LlmResponse(data=data, provider=self.name, model="test")


class Unreachable:
    """A model that cannot be reached at all."""

    name = "unreachable"

    def complete(self, _request: LlmRequest) -> LlmResponse:
        raise TransientLlmError("khong goi duoc model")


# --- stub agents, for the parts of the loop that need a failure ---------------


class StubValidator(BaseAgent):
    """Stands in for A5 so a test can choose what the Manager has to react to."""

    agent_id: ClassVar[str] = "a5_validator"
    # task_id -> what each successive call returns; "*" covers every task, and
    # the last entry repeats for as long as the Manager keeps asking.
    script: ClassVar[dict[str, list[str]]] = {}
    calls: ClassVar[list[str]] = []
    # The params each call was given, so a test can prove the Manager handed the
    # rejection back rather than asking the identical question again.
    seen: ClassVar[list[dict[str, Any]]] = []

    def execute(self, request: TaskRequest, _files: ScopedStorage) -> TaskResult:
        task_id = request.scope.task_id
        self.calls.append(task_id)
        self.seen.append(dict(request.scope.params))
        steps = self.script.get(task_id) or self.script.get("*") or ["ok"]
        outcome = steps[min(self.calls.count(task_id) - 1, len(steps) - 1)]
        if outcome == "ok":
            return TaskResult(
                task_id=request.scope.task_id,
                agent_id=self.agent_id,
                status="OK",
                payload={"target": "mart://x.parquet", "passed": 1, "failed": 0, "failures": []},
            )
        if outcome == "ratelimited":
            return TaskResult(
                task_id=request.scope.task_id,
                agent_id=self.agent_id,
                status="FAILED",
                error=ErrorDetail(
                    code="LLM_RATE_LIMITED",
                    message="het luot",
                    retryable=True,
                    retry_after_s=45.0,
                ),
            )
        if outcome == "boundary":
            return TaskResult(
                task_id=request.scope.task_id,
                agent_id=self.agent_id,
                status="BOUNDARY_VIOLATION",
                error=ErrorDetail(code="X", message="ra ngoai pham vi", retryable=False),
            )
        return TaskResult(
            task_id=request.scope.task_id,
            agent_id=self.agent_id,
            status="FAILED",
            error=ErrorDetail(
                code="FLAKY" if outcome == "flaky" else "NO_INPUT",
                message="hong tam thoi",
                retryable=outcome == "flaky",
                # "hard" stands for a task handed the wrong thing to work on -
                # the one failure a different plan could actually fix.
                replannable=outcome == "hard",
            ),
        )


@pytest.fixture(autouse=True)
def _reset_stub() -> None:
    StubValidator.script = {}
    StubValidator.calls = []
    StubValidator.seen = []


# --- the world the run happens in ---------------------------------------------


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
    frame = pd.DataFrame(
        {
            "city": [" Seattle ", "Seattle", "Renton", "Renton"],
            "price": ["100", "200", "300", "400"],
        }
    )
    path = resolve("raw://houses.csv", settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return DataRef(
        path="raw://houses.csv",
        format="csv",
        content_hash=storage.sha256_file(path),
    )


def full_plan() -> Plan:
    """The seven-task pipeline, with the params each agent needs."""
    return Plan(
        tasks=(
            PlannedTask(
                task_id="t1_ingest",
                agent_id="a1_ingest",
                params={"target": "staging://houses.parquet"},
                instruction="nap file",
            ),
            PlannedTask(task_id="t2_profile", agent_id="a2_profiler", depends_on=("t1_ingest",)),
            PlannedTask(
                task_id="t3_clean",
                agent_id="a3_cleaner",
                depends_on=("t2_profile",),
                inputs_from=("t1_ingest",),
            ),
            PlannedTask(
                task_id="t4_transform",
                agent_id="a4_transformer",
                depends_on=("t3_clean",),
                params={"target": "mart://houses.parquet", "question": "gia theo thanh pho"},
            ),
            PlannedTask(
                task_id="t5_validate",
                agent_id="a5_validator",
                depends_on=("t4_transform",),
                params={
                    "checks": {
                        "not_null": ["city", "price"],
                        "ranges": [{"column": "price", "min": 1}],
                    }
                },
            ),
            PlannedTask(
                task_id="t6_analyse",
                agent_id="a7_analyst",
                depends_on=("t5_validate",),
                inputs_from=("t4_transform",),
                params={
                    "question": "gia theo thanh pho",
                    "dimensions": ["city"],
                    "measures": ["price"],
                },
            ),
            PlannedTask(task_id="t7_report", agent_id="a8_reporter", depends_on=("t6_analyse",)),
        ),
        reason="ke hoach thu",
    )


def runner(settings: Settings, run_dir: Path, provider: Scripted, **kwargs: Any) -> DagRunner:
    return DagRunner(
        settings,
        run_dir,
        llm=LlmClient(provider),
        manifest_dir=MANIFEST_DIR,
        retry=kwargs.pop("retry", NO_WAIT),
        **kwargs,
    )


def approve(run_dir: Path, gate_id: str, options: tuple[str, ...]) -> None:
    """Record a human decision, the way the approve command does."""
    gates = GateStore(run_dir)
    states = StateStore(run_dir / "state.json")
    state = states.load()
    decision = decide(gates.read(gate_id), approved=options, now=NOW)
    states.save(state.with_gate(decision, now=NOW))


# --- the whole pipeline --------------------------------------------------------


def test_the_run_stops_at_the_first_gate_before_cleaning_anything(
    settings: Settings, run_dir: Path, source: DataRef
) -> None:
    outcome = runner(settings, run_dir, Scripted()).run(full_plan(), source, run_id=RUN_ID, now=NOW)
    assert outcome.paused_gate == gate_id_for("t3_clean")
    assert outcome.state.phase == "PAUSED_AWAITING_APPROVAL"
    # A3 proposed; it did not clean.
    assert not (settings.layers.clean / "events.parquet").exists()


def test_the_run_stops_again_at_gate_two_before_writing_a_report(
    settings: Settings, run_dir: Path, source: DataRef
) -> None:
    engine = runner(settings, run_dir, Scripted())
    engine.run(full_plan(), source, run_id=RUN_ID, now=NOW)
    approve(run_dir, gate_id_for("t3_clean"), ("trim_whitespace",))

    outcome = engine.run(full_plan(), source, run_id=RUN_ID, now=NOW)
    assert outcome.paused_gate == gate_id_for("t6_analyse")
    assert not (settings.layers.artifacts / "report").exists()


def test_a_plan_runs_from_a_raw_file_to_a_finished_report(
    settings: Settings, run_dir: Path, source: DataRef
) -> None:
    engine = runner(settings, run_dir, Scripted())
    engine.run(full_plan(), source, run_id=RUN_ID, now=NOW)
    approve(run_dir, gate_id_for("t3_clean"), ("trim_whitespace",))
    engine.run(full_plan(), source, run_id=RUN_ID, now=NOW)
    approve(run_dir, gate_id_for("t6_analyse"), ("f1", "f2"))

    outcome = engine.run(full_plan(), source, run_id=RUN_ID, now=NOW)
    assert outcome.is_complete, outcome.escalation
    assert (settings.layers.artifacts / "report" / f"{RUN_ID}.md").is_file()
    assert (settings.layers.mart / "houses.parquet").is_file()


def test_gate_two_offers_one_option_per_finding(
    settings: Settings, run_dir: Path, source: DataRef
) -> None:
    engine = runner(settings, run_dir, Scripted())
    engine.run(full_plan(), source, run_id=RUN_ID, now=NOW)
    approve(run_dir, gate_id_for("t3_clean"), ("trim_whitespace",))
    engine.run(full_plan(), source, run_id=RUN_ID, now=NOW)

    request = GateStore(run_dir).read(gate_id_for("t6_analyse"))
    assert request.option_ids == ("f1", "f2")
    assert "Gia trung binh" in request.options[0].label


def test_only_the_findings_a_person_approved_reach_the_report(
    settings: Settings, run_dir: Path, source: DataRef
) -> None:
    engine = runner(settings, run_dir, Scripted())
    engine.run(full_plan(), source, run_id=RUN_ID, now=NOW)
    approve(run_dir, gate_id_for("t3_clean"), ("trim_whitespace",))
    engine.run(full_plan(), source, run_id=RUN_ID, now=NOW)
    approve(run_dir, gate_id_for("t6_analyse"), ("f1",))
    engine.run(full_plan(), source, run_id=RUN_ID, now=NOW)

    report = (settings.layers.artifacts / "report" / f"{RUN_ID}.md").read_text(encoding="utf-8")
    assert "Gia trung binh" in report
    assert "Seattle chiem" not in report


def test_a_task_reads_what_inputs_from_names_not_what_it_waits_for(
    settings: Settings, run_dir: Path, source: DataRef
) -> None:
    # A7 depends on validation but reads the mart. Reading the validation report
    # instead would fail, silently or otherwise.
    engine = runner(settings, run_dir, Scripted())
    engine.run(full_plan(), source, run_id=RUN_ID, now=NOW)
    approve(run_dir, gate_id_for("t3_clean"), ("trim_whitespace",))
    outcome = engine.run(full_plan(), source, run_id=RUN_ID, now=NOW)

    analysis = next(r for r in outcome.results if r.agent_id == "a7_analyst")
    assert analysis.payload["source"] == "mart://houses.parquet"


def test_resuming_does_not_redo_what_already_succeeded(
    settings: Settings, run_dir: Path, source: DataRef
) -> None:
    provider = Scripted()
    engine = runner(settings, run_dir, provider)
    engine.run(full_plan(), source, run_id=RUN_ID, now=NOW)
    after_first = list(provider.purposes)
    approve(run_dir, gate_id_for("t3_clean"), ("trim_whitespace",))
    engine.run(full_plan(), source, run_id=RUN_ID, now=NOW)

    # A2 interpreted the profile once, on the first pass, and was not asked again.
    assert after_first.count("a2_profiler_interpret") == 1
    assert provider.purposes.count("a2_profiler_interpret") == 1


# --- retry, escalation and replan ---------------------------------------------


def one_task_plan(task_id: str = "t_check") -> Plan:
    return Plan(
        tasks=(
            PlannedTask(
                task_id=task_id,
                agent_id="a5_validator",
                params={"checks": {"not_null": ["city"]}},
            ),
        )
    )


def stub_runner(settings: Settings, run_dir: Path, slept: list[float], **kwargs: Any) -> DagRunner:
    return DagRunner(
        settings,
        run_dir,
        manifest_dir=MANIFEST_DIR,
        retry=RetryPolicy(base_delay_s=1.0, factor=2.0),
        sleep=slept.append,
        **kwargs,
    )


@pytest.fixture
def stubbed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Swap A5 for a stub, so a test can choose what the Manager must react to."""
    monkeypatch.setattr(
        dag_runner, "AGENT_TYPES", {**dag_runner.AGENT_TYPES, "a5_validator": StubValidator}
    )


@pytest.mark.usefixtures("stubbed")
def test_a_transient_failure_is_retried_with_growing_waits(
    settings: Settings, run_dir: Path, source: DataRef
) -> None:
    StubValidator.script = {"*": ["flaky", "flaky", "ok"]}
    slept: list[float] = []
    outcome = stub_runner(settings, run_dir, slept).run(
        one_task_plan(), source, run_id=RUN_ID, now=NOW
    )
    assert outcome.is_complete, outcome.escalation
    assert len(StubValidator.calls) == 3
    assert slept == [1.0, 2.0]


def audit_times(run_dir: Path, event: str) -> list[datetime]:
    lines = (run_dir / AUDIT_FILENAME).read_text(encoding="utf-8").splitlines()
    return [
        datetime.fromisoformat(record["ts"])
        for record in map(json.loads, lines)
        if record["event"] == event
    ]


@pytest.mark.usefixtures("stubbed")
def test_each_attempt_is_stamped_with_the_time_it_really_started(
    settings: Settings, run_dir: Path, source: DataRef
) -> None:
    # Real run (__q2, 2026-09-15): every TASK_STARTED carried the run's start
    # time, so a 13-minute attempt was invisible in the log and the job's
    # wall-clock ceiling never saw the clock move.
    StubValidator.script = {"*": ["flaky", "ok"]}
    stub_runner(settings, run_dir, []).run(one_task_plan(), source, run_id=RUN_ID)
    (run_started,) = audit_times(run_dir, "RUN_STARTED")
    started = audit_times(run_dir, "TASK_STARTED")
    assert len(started) == 2
    assert run_started < started[0] < started[1]


@pytest.mark.usefixtures("stubbed")
def test_a_run_given_a_time_keeps_it_for_every_attempt(
    settings: Settings, run_dir: Path, source: DataRef
) -> None:
    StubValidator.script = {"*": ["flaky", "ok"]}
    stub_runner(settings, run_dir, []).run(one_task_plan(), source, run_id=RUN_ID, now=NOW)
    assert set(audit_times(run_dir, "TASK_STARTED")) == {NOW}


@pytest.mark.usefixtures("stubbed")
def test_retries_stop_at_the_ceiling_and_escalate(
    settings: Settings, run_dir: Path, source: DataRef
) -> None:
    StubValidator.script = {"*": ["flaky"]}
    slept: list[float] = []
    outcome = stub_runner(settings, run_dir, slept).run(
        one_task_plan(), source, run_id=RUN_ID, now=NOW
    )
    assert outcome.escalation is not None
    assert len(StubValidator.calls) == 3  # max_retries in the manifest
    assert outcome.state.phase == "HALTED"


@pytest.mark.usefixtures("stubbed")
def test_a_boundary_violation_is_never_retried(
    settings: Settings, run_dir: Path, source: DataRef
) -> None:
    # Asking an agent that just stepped outside its scope to try again is
    # exactly the wrong response.
    StubValidator.script = {"*": ["boundary"]}
    slept: list[float] = []
    outcome = stub_runner(settings, run_dir, slept).run(
        one_task_plan(), source, run_id=RUN_ID, now=NOW
    )
    assert outcome.escalation is not None
    assert len(StubValidator.calls) == 1
    assert slept == []


@pytest.mark.usefixtures("stubbed")
def test_a_failure_that_survives_the_retries_is_replanned_around(
    settings: Settings, run_dir: Path, source: DataRef
) -> None:
    StubValidator.script = {"t_broken": ["hard"], "t_rescue": ["ok"]}
    rescue = one_task_plan("t_rescue")
    engine = stub_runner(
        settings,
        run_dir,
        [],
        planner=Planner(MANIFEST_DIR, llm=LlmClient(Scripted(plan=rescue))),
    )
    outcome = engine.run(one_task_plan("t_broken"), source, run_id=RUN_ID, now=NOW)

    assert outcome.is_complete, outcome.escalation
    assert StubValidator.calls[-1] == "t_rescue"
    assert outcome.plan is not None
    assert outcome.plan.task_ids == ("t_rescue",)


@pytest.mark.usefixtures("stubbed")
def test_without_a_model_there_is_no_replan(
    settings: Settings, run_dir: Path, source: DataRef
) -> None:
    StubValidator.script = {"*": ["hard"]}
    engine = stub_runner(settings, run_dir, [], planner=Planner(MANIFEST_DIR))
    outcome = engine.run(one_task_plan(), source, run_id=RUN_ID, now=NOW)
    assert outcome.escalation is not None


@pytest.mark.usefixtures("stubbed")
def test_the_run_gives_up_after_the_replan_budget(
    settings: Settings, run_dir: Path, source: DataRef
) -> None:
    StubValidator.script = {"*": ["hard"]}
    engine = stub_runner(
        settings,
        run_dir,
        [],
        planner=Planner(MANIFEST_DIR, llm=LlmClient(Scripted(plan=one_task_plan("t_rescue")))),
    )
    outcome = engine.run(one_task_plan("t_broken"), source, run_id=RUN_ID, now=NOW)
    assert outcome.escalation is not None
    assert {"t_broken", "t_rescue"} <= set(outcome.state.tasks)


# --- what the Manager refuses to guess ----------------------------------------


def test_a_task_reading_from_something_that_produced_nothing_is_refused(
    settings: Settings, run_dir: Path, source: DataRef
) -> None:
    # The planner would never pass this. The runner does not assume it did.
    plan = Plan(tasks=(PlannedTask(task_id="t2", agent_id="a2_profiler", inputs_from=("ma",)),))
    outcome = runner(settings, run_dir, Scripted()).run(plan, source, run_id=RUN_ID, now=NOW)
    assert outcome.escalation is not None
    assert "chua ghi ra gi" in outcome.escalation


@pytest.mark.usefixtures("stubbed")
def test_a_gate_the_manager_cannot_act_on_is_refused_loudly(
    settings: Settings, run_dir: Path, source: DataRef, tmp_path: Path
) -> None:
    # A gate nobody can carry out would pause the run forever, so it is an
    # error at the moment it is met, not a silent skip.
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    for path in MANIFEST_DIR.glob("*.yaml"):
        text = path.read_text(encoding="utf-8")
        if path.stem == "a5_validator":
            text = text.replace(
                "human_gate:\n  required: false",
                "human_gate:\n  required: true\n  at: after_execution\n  approve: dieu_gi_do",
            )
        (manifests / path.name).write_text(text, encoding="utf-8")

    engine = DagRunner(settings, run_dir, manifest_dir=manifests, retry=NO_WAIT)
    with pytest.raises(DagError, match="chua duoc ho tro"):
        engine.run(one_task_plan(), source, run_id=RUN_ID, now=NOW)


def test_approving_no_rule_at_all_still_finishes_the_run(
    settings: Settings, run_dir: Path, source: DataRef
) -> None:
    # A person who approves nothing has answered. Proposing again would ask the
    # same question forever, and the run would never end.
    engine = runner(settings, run_dir, Scripted())
    engine.run(full_plan(), source, run_id=RUN_ID, now=NOW)
    approve(run_dir, gate_id_for("t3_clean"), ())
    outcome = engine.run(full_plan(), source, run_id=RUN_ID, now=NOW)

    assert outcome.paused_gate == gate_id_for("t6_analyse")
    cleaned = next(r for r in outcome.results if r.agent_id == "a3_cleaner")
    assert cleaned.payload["rules_applied"] == []


@pytest.mark.usefixtures("stubbed")
def test_the_manager_waits_as_long_as_the_service_asked(
    settings: Settings, run_dir: Path, source: DataRef
) -> None:
    # Backing off for one second against a limit that named forty-five would
    # spend every remaining retry inside the same refusal window.
    StubValidator.script = {"*": ["ratelimited", "ok"]}
    slept: list[float] = []
    outcome = stub_runner(settings, run_dir, slept).run(
        one_task_plan(), source, run_id=RUN_ID, now=NOW
    )
    assert outcome.is_complete, outcome.escalation
    assert slept == [45.0]  # not the policy's 1.0


@pytest.mark.usefixtures("stubbed")
def test_a_model_the_replan_cannot_reach_does_not_crash_the_run(
    settings: Settings, run_dir: Path, source: DataRef
) -> None:
    # The run already had a failure to report. Losing that report to a traceback
    # from the replan attempt would be the worse outcome.
    StubValidator.script = {"*": ["hard"]}
    engine = stub_runner(
        settings, run_dir, [], planner=Planner(MANIFEST_DIR, llm=LlmClient(Unreachable()))
    )
    outcome = engine.run(one_task_plan(), source, run_id=RUN_ID, now=NOW)
    assert outcome.escalation is not None
    assert "hong tam thoi" in outcome.escalation or "FLAKY" in str(outcome.results)


@pytest.mark.usefixtures("stubbed")
def test_a_bad_answer_is_not_replanned_around(
    settings: Settings, run_dir: Path, source: DataRef
) -> None:
    # A different graph cannot make a model write a better sentence. Asking for
    # one spends a planning call to arrive back where we started.
    StubValidator.script = {"*": ["flaky"]}
    engine = stub_runner(
        settings,
        run_dir,
        [],
        planner=Planner(MANIFEST_DIR, llm=LlmClient(Scripted(plan=one_task_plan("t_rescue")))),
    )
    outcome = engine.run(one_task_plan("t_broken"), source, run_id=RUN_ID, now=NOW)

    assert outcome.escalation is not None
    assert not outcome.can_replan
    assert set(outcome.state.tasks) == {"t_broken"}  # no rescue plan was tried


@pytest.mark.usefixtures("stubbed")
def test_a_retry_is_told_why_the_last_attempt_was_rejected(
    settings: Settings, run_dir: Path, source: DataRef
) -> None:
    # Retrying an identical question and hoping for a different answer is not a
    # strategy. The reasons already exist; they used to be thrown away.
    StubValidator.script = {"*": ["flaky", "ok"]}
    stub_runner(settings, run_dir, []).run(one_task_plan(), source, run_id=RUN_ID, now=NOW)

    second = StubValidator.seen[1]
    assert "retry_feedback" in second
    assert second["retry_feedback"]["attempt"] == 1
    assert second["retry_feedback"]["rejected_because"]


@pytest.mark.usefixtures("stubbed")
def test_resuming_gives_a_task_its_retries_back(
    settings: Settings, run_dir: Path, source: DataRef
) -> None:
    # Counting attempts across invocations meant a task that had already failed
    # escalated immediately on resume - no retry at all, in exactly the case a
    # person resumes about.
    StubValidator.script = {"*": ["flaky"]}
    engine = stub_runner(settings, run_dir, [])
    first = engine.run(one_task_plan(), source, run_id=RUN_ID, now=NOW)
    assert first.escalation is not None
    assert len(StubValidator.calls) == 3

    # A fresh budget, not a continuation of the exhausted one.
    StubValidator.calls = []
    StubValidator.script = {"*": ["flaky", "flaky", "ok"]}
    second = engine.run(one_task_plan(), source, run_id=RUN_ID, now=NOW)
    assert second.is_complete, second.escalation
    assert len(StubValidator.calls) == 3  # it retried twice, rather than giving up at once

    # The record still shows every attempt ever made.
    assert second.state.tasks["t_check"].attempts == 6


# --- doi model khi mot con khong lam duoc ------------------------------------------


def test_the_first_two_attempts_keep_the_manifest_model() -> None:
    """Feedback earns its chance before anyone is replaced.

    The second attempt is not a repeat: it carries what was wrong with the
    first, and being told repairs a great many answers. Switching immediately
    would throw that away and pay a second model to learn the same lesson from
    scratch.
    """
    policy = LlmPolicy(enabled=True, model="chinh", fallback=("du_phong",))
    assert choose_model(policy, 1) == "chinh"
    assert choose_model(policy, 2) == "chinh"


def test_the_third_attempt_moves_on() -> None:
    """A third identical failure says nothing the second did not.

    Measured: two of the last fourteen real runs died with a model returning
    something that was not JSON, three attempts running. The retry worked
    exactly as designed and asked the same model the same question three times.
    """
    policy = LlmPolicy(enabled=True, model="chinh", fallback=("du_phong",))
    assert choose_model(policy, 3) == "du_phong"


def test_the_fallbacks_are_used_in_the_order_they_are_written() -> None:
    policy = LlmPolicy(enabled=True, model="chinh", fallback=("mot", "hai"))
    assert choose_model(policy, 3) == "mot"
    assert choose_model(policy, 4) == "hai"


def test_the_fallbacks_cycle_rather_than_stopping_at_the_last() -> None:
    """A generous retry ceiling should keep alternating, not hammer one name."""
    policy = LlmPolicy(enabled=True, model="chinh", fallback=("mot", "hai"))
    assert choose_model(policy, 5) == "mot"
    assert choose_model(policy, 6) == "hai"


def test_a_manifest_with_no_fallback_behaves_exactly_as_before() -> None:
    """Nothing changes for an agent that named nothing to fall back to."""
    policy = LlmPolicy(enabled=True, model="chinh")
    assert [choose_model(policy, n) for n in (1, 2, 3, 9)] == ["chinh"] * 4


def test_naming_no_model_at_all_still_means_the_run_default() -> None:
    policy = LlmPolicy(enabled=True)
    assert choose_model(policy, 1) == ""
    assert choose_model(policy, 5) == ""


def test_every_shipped_fallback_has_a_declared_price() -> None:
    """A fallback nobody priced is a fallback that halts the run on the budget.

    The ceiling refuses a model it cannot cost, which is the right behaviour
    and a poor surprise to meet on the third attempt of a real question.
    """
    prices = load_pricing(REPO_ROOT / "config" / "pricing.yaml")
    for path in sorted(MANIFEST_DIR.glob("*.yaml")):
        policy = load_manifest(path.stem, MANIFEST_DIR).allow.llm
        for name in policy.fallback:
            assert name in prices.models, f"{path.stem}: chua khai gia cho {name}"


def test_no_agent_falls_back_to_a_model_that_failed_that_job() -> None:
    """The measurements decide the list, not convenience.

    gemma scored 0/4 on lineage once the worked example stopped leaking the
    answer, so it must never be what A4 falls back to. qwen writes Vietnamese
    without diacritics, which switches the relevance check off entirely (L65),
    so it must never be asked to write a claim.
    """
    a4 = load_manifest("a4_transformer", MANIFEST_DIR).allow.llm
    assert "google/gemma-3-12b-it" not in (a4.model, *a4.fallback)

    for writer in ("a7_analyst", "a8_reporter", "a9_manager"):
        policy = load_manifest(writer, MANIFEST_DIR).allow.llm
        assert not any("qwen" in name for name in (policy.model, *policy.fallback)), writer
