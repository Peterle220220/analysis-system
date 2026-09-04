"""A whole run, driven end to end, for the tests that prove the six criteria.

Each criterion in Section 1 of the spec is a claim about the system as a whole,
not about a function. Proving one needs a real run: real agents, the real
Manager, real files on disk. What is faked is only the model, because a live one
would make the same test give different answers on different days - and a
criterion that holds only sometimes is not a criterion.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

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
from analysis_system.manager.retry import NO_WAIT
from analysis_system.manager.runner import RunOutcome
from analysis_system.manager.state import StateStore
from analysis_system.services import storage
from analysis_system.services.budget import BudgetTracker
from analysis_system.services.llm import LlmClient, LlmRequest, LlmResponse
from analysis_system.settings import LAYER_NAMES, LayerPaths, Settings, load_settings, resolve

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "bpi19_slice.csv"
MANIFEST_DIR = REPO_ROOT / "config" / "manifests"

SQL = SqlProposal(
    sql=(
        "SELECT case_spend_area_text AS spend_area, "
        "CAST(cumulative_net_worth_eur AS DOUBLE) AS net_worth FROM events"
    ),
    target_table="spend",
    lineage=[
        ColumnLineage(output="spend_area", sources=("case_spend_area_text",), transform="doi ten"),
        ColumnLineage(
            output="net_worth", sources=("cumulative_net_worth_eur",), transform="ep kieu"
        ),
    ],
    reason="bang chi tieu theo mang",
)

FINDINGS = FindingProposal(
    findings=[
        Finding(
            # No "dong" after the placeholder: rows.total already carries that
            # unit and code appends it, so writing it too rendered "2 dong dong".
            claim_template="Bang co {rows.total}.",
            metric_keys=("rows.total",),
            evidence_ref="mart://spend.parquet",
            confidence=0.95,
        ),
        Finding(
            claim_template="Gia tri luy ke trung binh la {net_worth.mean}.",
            metric_keys=("net_worth.mean",),
            evidence_ref="mart://spend.parquet",
            confidence=0.9,
        ),
    ],
    summary="hai ket luan",
)

RULES = RuleProposal(
    rules=[ProposedRule(rule_id="trim_whitespace", columns=("case_spend_area_text",), reason="x")],
    summary="mot rule",
)


class Scripted:
    """One prepared answer per schema, so a run is repeatable."""

    name = "criteria"

    def complete(self, request: LlmRequest) -> LlmResponse:
        answers: dict[Any, Any] = {
            ProfileInterpretation: ProfileInterpretation(),
            RuleProposal: RULES,
            SqlProposal: SQL,
            FindingProposal: FINDINGS,
            NarrativeProposal: NarrativeProposal(summary_template="Trung binh {net_worth.mean}."),
        }
        data = answers.get(request.schema)
        if data is None:
            raise AssertionError(f"kich ban thieu cau tra loi cho {request.schema}")
        return LlmResponse(
            data=data, provider=self.name, model="scripted", tokens_in=100, tokens_out=50
        )


def plan() -> Plan:
    """The seven-task pipeline the criteria are proved against."""
    return Plan(
        tasks=(
            PlannedTask(
                task_id="t1_ingest",
                agent_id="a1_ingest",
                params={"target": "staging://events.parquet"},
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
                params={"target": "mart://spend.parquet"},
            ),
            PlannedTask(
                task_id="t5_validate",
                agent_id="a5_validator",
                depends_on=("t4_transform",),
                params={"checks": {"not_null": ["net_worth"]}},
            ),
            PlannedTask(
                task_id="t6_analyse",
                agent_id="a7_analyst",
                depends_on=("t5_validate",),
                inputs_from=("t4_transform",),
                params={"question": "chi tieu ra sao", "measures": ["net_worth"]},
            ),
            PlannedTask(task_id="t7_report", agent_id="a8_reporter", depends_on=("t6_analyse",)),
        ),
        reason="ke hoach kiem chung tieu chi",
    )


def settings_in(root: Path) -> Settings:
    """Every layer under a throwaway directory, with the real rules."""
    roots = {name: root / name for name in LAYER_NAMES}
    for path in roots.values():
        path.mkdir(parents=True, exist_ok=True)
    return load_settings().model_copy(update={"layers": LayerPaths(**roots)})


def staged_source(settings: Settings) -> DataRef:
    """Put the committed fixture where A1 can read it."""
    target = resolve("raw://bpi19_slice.csv", settings)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(FIXTURE.read_bytes())
    return DataRef(
        path="raw://bpi19_slice.csv", format="csv", content_hash=storage.sha256_file(target)
    )


def runner_for(
    settings: Settings,
    run_dir: Path,
    *,
    budget: BudgetTracker | None = None,
    llm: Any = None,
) -> DagRunner:
    """A Manager wired the way a real run wires one, minus the live model.

     takes a different scripted model, for the cases where what matters is
    the answer *changing* between runs.
    """
    return DagRunner(
        settings,
        run_dir,
        llm=LlmClient(llm or Scripted(), budget=budget),
        manifest_dir=MANIFEST_DIR,
        retry=NO_WAIT,
        budget=budget,
    )


def approve_all(run_dir: Path, gate_id: str) -> None:
    """Answer one gate the way the approve command does."""
    gates = GateStore(run_dir)
    states = StateStore(run_dir / "state.json")
    state = states.load()
    request = gates.read(gate_id)
    decision = decide(request, approved=request.option_ids, now=state.updated_at)
    states.save(state.with_gate(decision, now=state.updated_at))


def run_to_completion(
    root: Path, run_id: str, *, budget: BudgetTracker | None = None
) -> tuple[RunOutcome, Settings, Path]:
    """Drive a whole run, answering every gate, and hand back what it produced."""
    settings = settings_in(root)
    source = staged_source(settings)
    run_dir = root / "runs" / run_id
    engine = runner_for(settings, run_dir, budget=budget)
    graph = plan()

    outcome = engine.run(graph, source, run_id=run_id)
    for _ in range(4):
        if not outcome.is_paused:
            break
        approve_all(run_dir, str(outcome.paused_gate))
        outcome = engine.run(graph, source, run_id=run_id)
    return outcome, settings, run_dir
