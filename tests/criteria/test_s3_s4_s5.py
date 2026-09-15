"""S3, S4 and S5: resume, traceability, and the ceiling that stops a run."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from analysis_system.contracts.agents import AnalysisResult, FindingProposal, Plan
from analysis_system.contracts.base import DataRef, ScopeToken
from analysis_system.core import storage
from analysis_system.core.budget import (
    AgentCallBudget,
    BudgetConfig,
    BudgetExceeded,
    BudgetTracker,
    JobBudget,
    ModelPrice,
    Pricing,
)
from analysis_system.core.hashing import canonical_hash
from analysis_system.core.scoped_storage import ScopedStorage
from analysis_system.core.settings import Settings, resolve
from analysis_system.manager.gates import GateStore
from analysis_system.manager.runner import RunOutcome
from analysis_system.manager.selection import apply_selection
from analysis_system.services.features import Selection, catalogue_for
from analysis_system.services.llm import LlmResponse
from tests.criteria.harness import (
    FINDINGS,
    MANIFEST_DIR,
    Scripted,
    approve_all,
    plan,
    run_to_completion,
    runner_for,
    settings_in,
    staged_source,
)

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


# --- S3: resume duoc tu buoc loi -------------------------------------------------


def test_s3_a_run_killed_mid_way_carries_on_where_it_stopped(tmp_path: Path) -> None:
    # State is written after every task, so the process dying is not the same
    # as the work being lost.
    settings = settings_in(tmp_path)
    source = staged_source(settings)
    run_dir = tmp_path / "runs" / "r_kill"
    engine = runner_for(settings, run_dir)

    first = engine.run(plan(), source, run_id="r_kill")
    assert first.is_paused
    finished_before = {task_id for task_id, task in first.state.tasks.items() if task.is_done}
    assert finished_before  # something really was completed

    # Nothing is carried in memory: a brand-new Manager picks the run up.
    approve_all(run_dir, str(first.paused_gate))
    resumed = runner_for(settings, run_dir).run(plan(), source, run_id="r_kill")
    for task_id in finished_before:
        assert resumed.state.tasks[task_id].is_done


def test_s3_work_already_done_is_not_done_again(tmp_path: Path) -> None:
    _, _, run_dir = run_to_completion(tmp_path, "r_once")
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    # A2 interprets once. Two attempts would mean the resume re-ran it.
    assert state["tasks"]["t2_profile"]["attempts"] == 1
    assert state["tasks"]["t1_ingest"]["attempts"] == 1


def test_s3_a_decision_already_made_is_replayed_not_asked_again(tmp_path: Path) -> None:
    outcome, settings, run_dir = run_to_completion(tmp_path, "r_replay")
    assert outcome.is_complete
    # Running the finished run again changes nothing and asks nothing.
    again = runner_for(settings, run_dir).run(plan(), staged_source(settings), run_id="r_replay")
    assert again.is_complete
    assert not again.is_paused
    assert again.results == ()  # every task skipped


def test_s3_a_changed_source_makes_the_whole_chain_run_again(tmp_path: Path) -> None:
    # Resuming onto different data would otherwise mix two runs together, so a
    # source whose content moved must invalidate everything downstream of it.
    _, settings, run_dir = run_to_completion(tmp_path, "r_changed")

    raw = resolve("raw://bpi19_slice.csv", settings)
    lines = raw.read_text(encoding="utf-8").splitlines()
    raw.write_text("\n".join(lines[:200]) + "\n", encoding="utf-8")
    changed = DataRef(
        path="raw://bpi19_slice.csv", format="csv", content_hash=storage.sha256_file(raw)
    )

    again = runner_for(settings, run_dir).run(plan(), changed, run_id="r_changed")
    reran = [result.task_id for result in again.results]
    assert "t1_ingest" in reran
    assert "t3_clean" in reran  # and the change carried down the chain


def test_s3_an_intermediate_file_edited_by_hand_is_not_noticed(tmp_path: Path) -> None:
    # Recorded honestly rather than claimed otherwise: should_skip compares the
    # hash written into the state when a task finished, not the hash of what is
    # on disk now. Re-reading every intermediate table on every resume would
    # cost time proportional to the data, to guard against something the system
    # never does to itself. A changed *source* is caught, which is the case that
    # actually arises.
    _, settings, run_dir = run_to_completion(tmp_path, "r_edited")
    staged = resolve("staging://events.parquet", settings)
    storage.write_parquet(storage.read_parquet(staged).head(100), staged)

    again = runner_for(settings, run_dir).run(plan(), staged_source(settings), run_id="r_edited")
    assert again.results == ()  # everything still counted as done


def _plan_with(task_id: str, **params: object) -> Plan:
    """The standard plan with one task's parameters replaced."""
    graph = plan()
    return graph.model_copy(
        update={
            "tasks": tuple(
                task.model_copy(update={"params": {**task.params, **params}})
                if task.task_id == task_id
                else task
                for task in graph.tasks
            )
        }
    )


def _drive(settings: Settings, run_dir: Path, graph: Plan, run_id: str) -> RunOutcome:
    """Run a plan to the end, answering whatever gates come up."""
    source = staged_source(settings)
    outcome = runner_for(settings, run_dir).run(graph, source, run_id=run_id)
    for _ in range(4):
        if not outcome.is_paused:
            break
        approve_all(run_dir, str(outcome.paused_gate))
        outcome = runner_for(settings, run_dir).run(graph, source, run_id=run_id)
    return outcome


def test_s3_a_task_told_to_analyse_something_else_is_run_again(tmp_path: Path) -> None:
    # The bug this exists for: resume compared input hashes and nothing else, so
    # a finished task was skipped no matter how much its instructions changed.
    # Someone narrowing an analysis to different columns got the previous
    # answer back, with no indication that their change had been ignored - the
    # one failure mode worse than an error, because the numbers look fine.
    settings = settings_in(tmp_path)
    run_dir = tmp_path / "runs" / "r_params"

    # Explicitly no breakdown to begin with. Saying nothing would let the
    # analyst work the dimensions out for itself, and what this test is about
    # is changing a choice a person actually made.
    first = _drive(settings, run_dir, _plan_with("t6_analyse", dimensions=[]), "r_params")
    assert not first.is_paused
    before = first.state.tasks["t6_analyse"]

    # Same data, same run: only the question changes - group by spend area.
    second = _drive(
        settings, run_dir, _plan_with("t6_analyse", dimensions=["spend_area"]), "r_params"
    )
    after = second.state.tasks["t6_analyse"]

    assert after.params_hash != before.params_hash
    assert after.attempts > before.attempts, "task duoc bo qua du da doi tham so"


def test_s3_the_new_analysis_reaches_the_report_too(tmp_path: Path) -> None:
    # Re-running the analysis is only half of it. The report reads what the
    # analysis wrote, so if the report were still skipped the artifact a person
    # actually opens would be the one they asked to replace.
    #
    # What is asserted is that the report was rebuilt from the new analysis, not
    # that its bytes differ: whether the wording changes depends on what the
    # model chose to cite, and pinning that here would be testing the model
    # rather than the pipeline. The cascade itself runs through content hashes -
    # the analysis writes different output, so the report's input changes.
    settings = settings_in(tmp_path)
    run_dir = tmp_path / "runs" / "r_cascade"

    first = _drive(settings, run_dir, _plan_with("t6_analyse", dimensions=[]), "r_cascade")
    before = first.state.tasks["t7_report"]

    second = _drive(
        settings, run_dir, _plan_with("t6_analyse", dimensions=["spend_area"]), "r_cascade"
    )
    after = second.state.tasks["t7_report"]

    assert after.input_hashes != before.input_hashes, "bao cao van doc ket qua phan tich cu"
    assert after.attempts > before.attempts, "bao cao khong duoc dung lai"


def test_s3_an_unchanged_plan_run_again_repeats_no_work(tmp_path: Path) -> None:
    # The other direction, and it carries the weight: a fingerprint that never
    # matched would make every resume redo everything. That would look like
    # caution and would quietly cost a person the whole point of resuming.
    settings = settings_in(tmp_path)
    run_dir = tmp_path / "runs" / "r_same"

    first = _drive(settings, run_dir, plan(), "r_same")
    before = {task_id: task.attempts for task_id, task in first.state.tasks.items()}

    second = _drive(settings, run_dir, plan(), "r_same")
    after = {task_id: task.attempts for task_id, task in second.state.tasks.items()}

    assert after == before


def test_s3_changing_what_a_person_chose_reruns_exactly_what_it_should(tmp_path: Path) -> None:
    """The whole point of the feature-selection work, end to end.

    Somebody finishes a run, decides they only care about two columns, says so,
    and resumes. The analysis has to be redone with those columns and the report
    rebuilt from it - and the ingest and cleaning, which the choice says nothing
    about, must not be repeated.

    This passes only because a task's parameters are part of its identity (L40).
    Before that fix the resumed run would have handed back the previous answer to
    the new question without a word, which is exactly the failure this guards.
    """
    settings = settings_in(tmp_path)
    run_dir = tmp_path / "runs" / "r_select"

    # Start from an explicit "no breakdown", so the selection that follows is a
    # real change. A plan that says nothing about dimensions lets the analyst
    # pick them, and it would pick the same column this selection names.
    first = _drive(settings, run_dir, _plan_with("t6_analyse", dimensions=[]), "r_select")
    assert not first.is_paused
    before = first.state.tasks

    frame = storage.read_parquet(resolve("mart://spend.parquet", settings))
    catalogue = catalogue_for(frame, "mart://spend.parquet")
    chosen = Selection.from_params(["column:spend_area"])
    narrowed = apply_selection(plan(), chosen, catalogue, MANIFEST_DIR)

    second = _drive(settings, run_dir, narrowed, "r_select")
    after = second.state.tasks

    # Redone: the analysis was told something different.
    assert after["t6_analyse"].attempts > before["t6_analyse"].attempts
    # Redone: it reads what the analysis wrote, and that changed.
    assert after["t7_report"].input_hashes != before["t7_report"].input_hashes
    # Untouched: the choice says nothing about loading or cleaning the data.
    for task_id in ("t1_ingest", "t3_clean", "t4_transform"):
        assert after[task_id].attempts == before[task_id].attempts


def test_s3_choosing_the_same_thing_again_repeats_no_work(tmp_path: Path) -> None:
    # The other direction. A selection that re-ran everything each time it was
    # confirmed would make the feature worse than not having it.
    settings = settings_in(tmp_path)
    run_dir = tmp_path / "runs" / "r_select_same"

    frame_plan = plan()
    first = _drive(settings, run_dir, frame_plan, "r_select_same")
    frame = storage.read_parquet(resolve("mart://spend.parquet", settings))
    catalogue = catalogue_for(frame, "mart://spend.parquet")
    narrowed = apply_selection(
        frame_plan, Selection.from_params(["column:spend_area"]), catalogue, MANIFEST_DIR
    )

    second = _drive(settings, run_dir, narrowed, "r_select_same")
    third = _drive(settings, run_dir, narrowed, "r_select_same")

    assert {task_id: task.attempts for task_id, task in third.state.tasks.items()} == {
        task_id: task.attempts for task_id, task in second.state.tasks.items()
    }
    assert first is not None


class Speaks:
    """The scripted model, but saying something else about the findings.

    Everything else answers as usual. Only the conclusions change, which is what
    happens when an analysis is given fewer metrics to work from.
    """

    name = "criteria"

    def __init__(self, findings: FindingProposal) -> None:
        self._findings = findings
        self._scripted = Scripted()

    def complete(self, request: object) -> object:
        if getattr(request, "schema", None) is FindingProposal:
            return LlmResponse(
                data=self._findings,
                provider=self.name,
                model="scripted",
                tokens_in=100,
                tokens_out=50,
            )
        return self._scripted.complete(request)  # type: ignore[arg-type]


# --- what running it on a real question found -------------------------------------


def _plan_with_profile_first() -> Plan:
    """The standard plan, with the transformer reading the profile as well.

    A plan a planner really wrote. Given the freedom to say which upstream
    outputs a task reads, it listed the profile alongside the table - reasonable,
    the profile is context - and the transformer read it as Parquet and died.
    """
    graph = plan()
    return graph.model_copy(
        update={
            "tasks": tuple(
                task.model_copy(update={"inputs_from": ("t2_profile", "t3_clean")})
                if task.task_id == "t4_transform"
                else task
                for task in graph.tasks
            )
        }
    )


def test_an_agent_takes_the_input_it_needs_not_the_one_listed_first(tmp_path: Path) -> None:
    # L45. Position was never a way to identify an input: it is an unwritten
    # rule the model writing the plan has no way to know, and breaking it
    # produced an error about Parquet magic bytes, nowhere near the mistake.
    settings = settings_in(tmp_path)
    run_dir = tmp_path / "runs" / "r_order"
    outcome = _drive(settings, run_dir, _plan_with_profile_first(), "r_order")
    assert not outcome.is_paused
    assert outcome.state.tasks["t4_transform"].is_done


def test_a_gate_asks_again_when_the_conclusions_have_changed(tmp_path: Path) -> None:
    """L47 and L48, which arrived together on a real run.

    An approval is about *those* conclusions. When the analysis is redone and
    says something else, nobody has approved the new ones - and the question on
    disk still described the old ones, so a person was shown three conclusions
    to approve while the analysis held two, and approving the third failed the
    report.
    """
    settings = settings_in(tmp_path)
    run_dir = tmp_path / "runs" / "r_stale"

    first = _drive(settings, run_dir, plan(), "r_stale")
    assert not first.is_paused

    # The analysis is asked something different and now says less, exactly as
    # the live model did when its metric set was narrowed.
    fewer = FindingProposal(
        findings=[FINDINGS.findings[0]],
        summary="mot ket luan",
    )
    graph = _plan_with("t6_analyse", dimensions=["spend_area"])
    second = runner_for(settings, run_dir, llm=Speaks(fewer)).run(
        graph, staged_source(settings), run_id="r_stale"
    )

    # It stops to ask again rather than replaying an approval given for
    # conclusions that no longer exist.
    assert second.is_paused
    assert second.paused_gate == "gate_t6_analyse"

    # And the question it asks describes what the task now holds.
    asked = GateStore(run_dir).read("gate_t6_analyse")
    held = second.state.tasks["t6_analyse"].output_refs[0].content_hash
    assert asked.describes(held)
    assert len(asked.options) == 1


def test_the_gate_listing_agrees_with_the_manager_about_what_is_owed(tmp_path: Path) -> None:
    # The run stopped and told the operator to go and look at the gates, and the
    # listing told them there was nothing to look at. The worst possible pair of
    # messages to receive together, so both now ask one function.
    settings = settings_in(tmp_path)
    run_dir = tmp_path / "runs" / "r_listing"

    _drive(settings, run_dir, plan(), "r_listing")
    fewer = FindingProposal(findings=[FINDINGS.findings[0]], summary="mot ket luan")
    outcome = runner_for(settings, run_dir, llm=Speaks(fewer)).run(
        _plan_with("t6_analyse", dimensions=["spend_area"]),
        staged_source(settings),
        run_id="r_listing",
    )

    assert outcome.is_paused
    pending = GateStore(run_dir).pending(outcome.state)
    assert [request.gate_id for request in pending] == [str(outcome.paused_gate)]


def test_an_approval_still_replays_when_nothing_has_changed(tmp_path: Path) -> None:
    # The other direction, and it carries the weight: if an approval stopped
    # applying for no reason, every resume would ask again and the gates would
    # become something people click through.
    settings = settings_in(tmp_path)
    run_dir = tmp_path / "runs" / "r_replay"

    first = _drive(settings, run_dir, plan(), "r_replay")
    assert not first.is_paused

    again = runner_for(settings, run_dir).run(plan(), staged_source(settings), run_id="r_replay")
    assert not again.is_paused
    assert GateStore(run_dir).pending(again.state) == []


# --- S4: moi ket luan truy nguoc duoc ve nguon goc -------------------------------


def analysis_of(settings: Settings, run_id: str, task_id: str = "t6_analyse") -> AnalysisResult:
    # The task id is part of the name now: a plan may hold several analysis
    # tasks, and they all used to write to the one file and overwrite each
    # other in silence.
    path = resolve(f"artifacts://{run_id}_{task_id}_findings.json", settings)
    return AnalysisResult.model_validate_json(storage.read_text(path))


def test_s4_every_conclusion_names_a_source(tmp_path: Path) -> None:
    _, settings, _ = run_to_completion(tmp_path, "r_trace")
    analysis = analysis_of(settings, "r_trace")
    assert analysis.findings
    assert all(finding.evidence_ref for finding in analysis.findings)


def test_s4_the_source_a_conclusion_names_really_exists(tmp_path: Path) -> None:
    outcome, settings, _ = run_to_completion(tmp_path, "r_exists")
    analysis = analysis_of(settings, "r_exists")
    for finding in analysis.findings:
        assert resolve(finding.evidence_ref, settings).is_file()


def test_s4_a_conclusion_records_which_content_not_only_which_path(
    tmp_path: Path,
) -> None:
    # A path can be overwritten by a later run and still pass every check. The
    # hash is what makes a citation survive that.
    _, settings, _ = run_to_completion(tmp_path, "r_hash")
    analysis = analysis_of(settings, "r_hash")
    for finding in analysis.findings:
        table = storage.read_parquet(resolve(finding.evidence_ref, settings))
        assert finding.evidence_hash == canonical_hash(table)


def test_s4_an_overwritten_source_makes_the_citation_detectably_stale(
    tmp_path: Path,
) -> None:
    _, settings, _ = run_to_completion(tmp_path, "r_stale")
    analysis = analysis_of(settings, "r_stale")
    mart = resolve(analysis.findings[0].evidence_ref, settings)
    frame = storage.read_parquet(mart)
    storage.write_parquet(frame.head(10), mart)
    # The path still resolves; the content no longer matches what was cited.
    assert mart.is_file()
    assert analysis.findings[0].evidence_hash != canonical_hash(storage.read_parquet(mart))


def test_s4_every_number_in_a_conclusion_came_from_a_named_metric(
    tmp_path: Path,
) -> None:
    _, settings, _ = run_to_completion(tmp_path, "r_numbers")
    analysis = analysis_of(settings, "r_numbers")
    for finding in analysis.findings:
        assert finding.metrics
        for key in finding.metrics:
            assert key in finding.template


def test_s4_a_citation_outside_the_granted_scope_is_not_usable(tmp_path: Path) -> None:
    settings = settings_in(tmp_path)
    token = ScopeToken(
        run_id="r_cite",
        task_id="t",
        agent_id="a7_analyst",
        allow_read=("mart://**",),
        allow_write=("artifacts://**",),
        issued_at=NOW,
        expires_at=NOW.replace(hour=13),
    )
    files = ScopedStorage(token, settings)
    assert not files.citation_exists("raw://bpi19_slice.csv")


# --- S5: khong vuot ngan sach ----------------------------------------------------


def budget_of(*, max_tokens: int = 1_000_000, max_cost: float = 100.0) -> BudgetTracker:
    config = BudgetConfig(
        per_job=JobBudget(max_tokens=max_tokens, max_cost_usd=max_cost, max_wallclock_min=30),
        per_agent_call=AgentCallBudget(max_tokens=100_000, max_retries=3),
    )
    prices = Pricing(
        last_verified=NOW.date(),
        models={"scripted": ModelPrice(input=1.0, output=1.0)},
    )
    # Started now, not at the fixed NOW these tests use for everything else.
    # The run measures elapsed time against the real clock, so pinning the start
    # to an instant on one particular day made this a test that passed until
    # half past twelve and failed for ever afterwards - which is exactly what it
    # did. The wallclock ceiling itself is tested in tests/unit/test_budget.py,
    # where the clock is supplied rather than read.
    return BudgetTracker(config, prices, started_at=datetime.now(UTC))


def test_s5_a_run_inside_its_ceiling_finishes_and_reports_what_it_used(
    tmp_path: Path,
) -> None:
    budget = budget_of()
    outcome, _, _ = run_to_completion(tmp_path, "r_budget", budget=budget)
    assert outcome.is_complete
    assert budget.tokens_total > 0


def test_s5_a_job_halts_when_it_crosses_its_token_ceiling(tmp_path: Path) -> None:
    # Never continued automatically past a ceiling, and never quietly.
    with pytest.raises(BudgetExceeded, match="tran token"):
        run_to_completion(tmp_path, "r_tokens", budget=budget_of(max_tokens=200))


def test_s5_a_job_halts_when_it_crosses_its_money_ceiling(tmp_path: Path) -> None:
    with pytest.raises(BudgetExceeded, match="tran tien|chi phi"):
        run_to_completion(tmp_path, "r_money", budget=budget_of(max_cost=0.0001))


def test_s5_the_ceiling_stops_the_run_before_it_finishes(tmp_path: Path) -> None:
    # A halt that arrives after the work is done protects nothing.
    budget = budget_of(max_tokens=200)
    with pytest.raises(BudgetExceeded):
        run_to_completion(tmp_path, "r_early", budget=budget)
    assert not (tmp_path / "artifacts" / "report").exists()
