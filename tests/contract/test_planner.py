"""Planner tests: a plan is a proposal, and nothing runs until code agrees."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from analysis_system.contracts.agents import Plan, PlannedTask
from analysis_system.manager.planner import (
    PlanError,
    Planner,
    available_agents,
    build_plan_request,
    build_replan_request,
    default_plan,
    describe_agents,
    frozen_conflicts,
    ordered_tasks,
    topological_order,
    transitive_dependencies,
    validate_plan,
    wire_transforms,
    with_synthesis,
)
from analysis_system.services.boundary import Manifest
from analysis_system.services.llm import LlmClient, LlmRequest, LlmResponse

MANIFEST_DIR = Path(__file__).resolve().parents[2] / "config" / "manifests"


class FixedPlan:
    """Answers with one prepared plan."""

    name = "test"

    def __init__(self, plan: Plan) -> None:
        self._plan = plan
        self.calls = 0

    def complete(self, _request: LlmRequest) -> LlmResponse:
        self.calls += 1
        return LlmResponse(data=self._plan, provider=self.name, model="test")


def plan_of(*tasks: PlannedTask) -> Plan:
    return Plan(tasks=tasks, reason="thu")


# --- the agent registry -------------------------------------------------------


def test_every_agent_with_a_manifest_is_offered() -> None:
    found = available_agents(MANIFEST_DIR)
    assert {"a1_ingest", "a2_profiler", "a3_cleaner", "a4_transformer", "a5_validator"} <= set(
        found
    )


def test_an_agent_without_a_manifest_cannot_be_planned(tmp_path: Path) -> None:
    # A manifest is what makes an agent real: no manifest, no boundary.
    assert available_agents(tmp_path) == {}


def test_the_registry_shown_to_the_planner_carries_the_data_flow() -> None:
    described = describe_agents(available_agents(MANIFEST_DIR))
    ingest = next(entry for entry in described if entry["agent_id"] == "a1_ingest")
    assert ingest["reads"] == ["raw://**", "extracted://**"]
    assert ingest["writes"] == ["staging://**"]
    assert ingest["uses_llm"] is False


# --- ordering -----------------------------------------------------------------


def test_tasks_run_after_what_they_depend_on() -> None:
    plan = plan_of(
        PlannedTask(task_id="b", agent_id="a2_profiler", depends_on=("a",)),
        PlannedTask(task_id="a", agent_id="a1_ingest"),
    )
    assert topological_order(plan) == ["a", "b"]


def test_independent_tasks_are_ordered_by_id_so_two_runs_agree() -> None:
    # Without the tie-break the order would follow dictionary iteration.
    plan = plan_of(
        PlannedTask(task_id="z", agent_id="a1_ingest"),
        PlannedTask(task_id="a", agent_id="a1_ingest"),
        PlannedTask(task_id="m", agent_id="a1_ingest"),
    )
    assert topological_order(plan) == ["a", "m", "z"]
    assert topological_order(plan) == topological_order(plan)


def test_a_cycle_is_refused_rather_than_run_forever() -> None:
    plan = plan_of(
        PlannedTask(task_id="a", agent_id="a1_ingest", depends_on=("b",)),
        PlannedTask(task_id="b", agent_id="a2_profiler", depends_on=("a",)),
    )
    with pytest.raises(PlanError, match="chu trinh"):
        topological_order(plan)


def test_ordered_tasks_returns_the_tasks_themselves() -> None:
    plan = plan_of(
        PlannedTask(task_id="b", agent_id="a2_profiler", depends_on=("a",)),
        PlannedTask(task_id="a", agent_id="a1_ingest"),
    )
    assert [task.task_id for task in ordered_tasks(plan)] == ["a", "b"]


# --- validation ---------------------------------------------------------------


def test_a_sound_plan_passes() -> None:
    assert validate_plan(default_plan("raw://x.csv"), available_agents(MANIFEST_DIR)) == []


def test_an_empty_plan_is_refused() -> None:
    assert validate_plan(Plan(), available_agents(MANIFEST_DIR)) == [
        "ke hoach rong - khong co task nao"
    ]


def test_calling_an_agent_that_does_not_exist_is_refused() -> None:
    plan = plan_of(PlannedTask(task_id="a", agent_id="a9_khong_co"))
    problems = validate_plan(plan, available_agents(MANIFEST_DIR))
    assert any("khong ton tai" in problem for problem in problems)


def test_depending_on_a_task_outside_the_plan_is_refused() -> None:
    plan = plan_of(PlannedTask(task_id="a", agent_id="a1_ingest", depends_on=("khong_co",)))
    problems = validate_plan(plan, available_agents(MANIFEST_DIR))
    assert any("khong co trong ke hoach" in problem for problem in problems)


def test_a_task_depending_on_itself_is_refused() -> None:
    plan = plan_of(PlannedTask(task_id="a", agent_id="a1_ingest", depends_on=("a",)))
    problems = validate_plan(plan, available_agents(MANIFEST_DIR))
    assert any("phu thuoc chinh no" in problem for problem in problems)


def test_a_duplicate_task_id_is_refused() -> None:
    # Otherwise the second one would overwrite the first in the state.
    plan = plan_of(
        PlannedTask(task_id="a", agent_id="a1_ingest"),
        PlannedTask(task_id="a", agent_id="a2_profiler"),
    )
    problems = validate_plan(plan, available_agents(MANIFEST_DIR))
    assert any("xuat hien nhieu lan" in problem for problem in problems)


# --- the default plan ---------------------------------------------------------


def test_the_default_plan_runs_the_whole_pipeline() -> None:
    order = topological_order(default_plan("raw://x.csv"))
    assert order == [
        "t1_ingest",
        "t2_profile",
        "t3_clean",
        "t4_transform",
        "t5_validate",
        "t6_analyse",
        "t7_report",
    ]


def test_the_default_plan_says_it_used_no_model() -> None:
    # A plan nobody reasoned about must not look like one that was.
    assert "khong dung model" in default_plan("raw://x.csv").reason


# --- the planner --------------------------------------------------------------


def test_without_a_model_the_declared_plan_is_used() -> None:
    planner = Planner(MANIFEST_DIR)
    assert planner.plan("cau hoi", "raw://x.csv").task_ids[0] == "t1_ingest"


def test_a_model_plan_that_checks_out_is_accepted() -> None:
    proposed = plan_of(
        PlannedTask(task_id="t1", agent_id="a1_ingest", instruction="nap"),
        PlannedTask(task_id="t2", agent_id="a2_profiler", depends_on=("t1",), instruction="mo ta"),
    )
    planner = Planner(MANIFEST_DIR, llm=LlmClient(FixedPlan(proposed)))
    result = planner.plan("mo ta du lieu", "raw://x.csv")
    assert result.task_ids == ("t1", "t2")


def test_a_model_plan_with_a_cycle_is_rejected_whole() -> None:
    # Not repaired: repairing would mean choosing an order nobody chose.
    broken = plan_of(
        PlannedTask(task_id="t1", agent_id="a1_ingest", depends_on=("t2",)),
        PlannedTask(task_id="t2", agent_id="a2_profiler", depends_on=("t1",)),
    )
    planner = Planner(MANIFEST_DIR, llm=LlmClient(FixedPlan(broken)))
    with pytest.raises(PlanError, match="chu trinh"):
        planner.plan("cau hoi", "raw://x.csv")


def test_a_model_plan_naming_an_unknown_agent_is_rejected() -> None:
    invented = plan_of(PlannedTask(task_id="t1", agent_id="a99_tu_che"))
    planner = Planner(MANIFEST_DIR, llm=LlmClient(FixedPlan(invented)))
    with pytest.raises(PlanError, match="khong ton tai"):
        planner.plan("cau hoi", "raw://x.csv")


def test_the_prompt_shows_the_planner_what_each_agent_reads_and_writes() -> None:
    request = build_plan_request("cau hoi", available_agents(MANIFEST_DIR), "raw://x.csv")
    assert "staging://**" in request.prompt
    assert "a5_validator" in request.prompt
    assert request.purpose == "manager_plan"


# --- what a task reads, as opposed to what it waits for -----------------------


def test_a_task_reads_its_dependencies_unless_told_otherwise() -> None:
    task = PlannedTask(task_id="b", agent_id="a2_profiler", depends_on=("a",))
    assert task.reads_from == ("a",)


def test_inputs_from_wins_when_order_and_data_flow_differ() -> None:
    task = PlannedTask(task_id="c", agent_id="a7_analyst", depends_on=("b",), inputs_from=("a",))
    assert task.reads_from == ("a",)


def test_reading_from_a_task_that_might_not_have_run_is_refused() -> None:
    # Nothing orders these two, so at the moment b runs, a may not have.
    plan = plan_of(
        PlannedTask(task_id="a", agent_id="a1_ingest"),
        PlannedTask(task_id="b", agent_id="a2_profiler", inputs_from=("a",)),
    )
    problems = validate_plan(plan, available_agents(MANIFEST_DIR))
    assert any("khong doi task do chay xong" in problem for problem in problems)


def test_reading_from_further_up_the_chain_is_allowed() -> None:
    # a runs before b runs before c, so c may read what a wrote.
    plan = plan_of(
        PlannedTask(task_id="a", agent_id="a1_ingest"),
        PlannedTask(task_id="b", agent_id="a2_profiler", depends_on=("a",)),
        PlannedTask(task_id="c", agent_id="a3_cleaner", depends_on=("b",), inputs_from=("a",)),
    )
    assert validate_plan(plan, available_agents(MANIFEST_DIR)) == []


def test_reading_from_a_task_outside_the_plan_is_refused() -> None:
    plan = plan_of(PlannedTask(task_id="a", agent_id="a1_ingest", inputs_from=("ma",)))
    problems = validate_plan(plan, available_agents(MANIFEST_DIR))
    assert any("khong co trong ke hoach" in problem for problem in problems)


def test_transitive_dependencies_reach_all_the_way_back() -> None:
    plan = plan_of(
        PlannedTask(task_id="a", agent_id="a1_ingest"),
        PlannedTask(task_id="b", agent_id="a2_profiler", depends_on=("a",)),
        PlannedTask(task_id="c", agent_id="a3_cleaner", depends_on=("b",)),
    )
    assert transitive_dependencies(plan)["c"] == {"a", "b"}


def test_the_default_plan_analyses_the_mart_not_the_validation_report() -> None:
    # A7 waits for validation but reads the table A4 built. Getting this wrong
    # would hand the analyst a JSON report and call it a data table.
    analyse = next(
        task for task in default_plan("raw://x.csv").tasks if task.task_id == "t6_analyse"
    )
    assert analyse.depends_on == ("t5_validate",)
    assert analyse.reads_from == ("t4_transform",)


# --- replanning ----------------------------------------------------------------


def test_a_replan_may_be_accepted_when_it_differs() -> None:
    rescue = plan_of(PlannedTask(task_id="t9", agent_id="a1_ingest"))
    planner = Planner(MANIFEST_DIR, llm=LlmClient(FixedPlan(rescue)))
    failed = plan_of(PlannedTask(task_id="t1", agent_id="a1_ingest"))
    assert planner.replan("cau hoi", "raw://x.csv", failed, "t1 hong").task_ids == ("t9",)


def test_a_replan_that_repeats_the_failed_plan_is_refused() -> None:
    # Running the same graph after the same failure is a loop, not a recovery.
    failed = plan_of(PlannedTask(task_id="t1", agent_id="a1_ingest"))
    planner = Planner(MANIFEST_DIR, llm=LlmClient(FixedPlan(failed)))
    with pytest.raises(PlanError, match="trung y het"):
        planner.replan("cau hoi", "raw://x.csv", failed, "t1 hong")


def test_replanning_without_a_model_is_refused() -> None:
    failed = plan_of(PlannedTask(task_id="t1", agent_id="a1_ingest"))
    with pytest.raises(PlanError, match="Khong co model"):
        Planner(MANIFEST_DIR).replan("cau hoi", "raw://x.csv", failed, "t1 hong")


def test_the_replan_prompt_shows_what_went_wrong() -> None:
    failed = plan_of(PlannedTask(task_id="t1", agent_id="a1_ingest"))
    request = build_replan_request(
        "cau hoi", available_agents(MANIFEST_DIR), "raw://x.csv", failed, "t1: het lan thu"
    )
    assert "het lan thu" in request.prompt
    assert "t1" in request.prompt


def test_a_planner_without_a_model_says_so() -> None:
    assert not Planner(MANIFEST_DIR).has_model
    assert Planner(MANIFEST_DIR, llm=LlmClient(FixedPlan(Plan()))).has_model


# --- a plan that already ran is partly a fact ----------------------------------


def settled_plan() -> Plan:
    return plan_of(
        PlannedTask(task_id="a", agent_id="a1_ingest", params={"target": "staging://x.parquet"}),
        PlannedTask(task_id="b", agent_id="a2_profiler", depends_on=("a",)),
        PlannedTask(task_id="c", agent_id="a3_cleaner", depends_on=("b",), inputs_from=("a",)),
    )


def test_leaving_settled_work_alone_is_no_conflict() -> None:
    plan = settled_plan()
    assert frozen_conflicts(plan, plan, {"a", "b"}) == []


def test_changing_what_a_finished_task_reads_is_refused() -> None:
    # This is the actual bug: a replan gave a finished task different inputs,
    # its input hashes changed, and an approved cleaning step ran five times.
    before = settled_plan()
    after = plan_of(
        before.tasks[0],
        before.tasks[1],
        before.tasks[2].model_copy(update={"inputs_from": ("a", "b")}),
    )
    problems = frozen_conflicts(before, after, {"c"})
    assert any("doi inputs_from" in problem for problem in problems)


def test_changing_which_agent_ran_is_refused() -> None:
    before = settled_plan()
    after = plan_of(
        before.tasks[0].model_copy(update={"agent_id": "a2_profiler"}), *before.tasks[1:]
    )
    assert any("doi agent_id" in problem for problem in frozen_conflicts(before, after, {"a"}))


def test_changing_the_params_a_person_approved_is_refused() -> None:
    before = settled_plan()
    after = plan_of(
        before.tasks[0].model_copy(update={"params": {"target": "staging://khac.parquet"}}),
        *before.tasks[1:],
    )
    assert any("doi params" in problem for problem in frozen_conflicts(before, after, {"a"}))


def test_dropping_a_finished_task_orphans_its_output() -> None:
    before = settled_plan()
    after = plan_of(before.tasks[1], before.tasks[2])
    assert any("mo coi" in problem for problem in frozen_conflicts(before, after, {"a"}))


def test_a_task_that_has_not_run_may_still_be_rewritten() -> None:
    # The whole point of replanning. Only settled work is off limits.
    before = settled_plan()
    after = plan_of(
        before.tasks[0],
        before.tasks[1],
        before.tasks[2].model_copy(update={"agent_id": "a4_transformer"}),
    )
    assert frozen_conflicts(before, after, {"a", "b"}) == []


def test_wording_may_change_because_a_finished_task_will_not_run_again() -> None:
    before = settled_plan()
    after = plan_of(
        before.tasks[0].model_copy(update={"instruction": "dien dat khac"}), *before.tasks[1:]
    )
    assert frozen_conflicts(before, after, {"a"}) == []


def test_a_replan_that_rewrites_settled_work_is_refused() -> None:
    before = settled_plan()
    rewritten = plan_of(
        before.tasks[0].model_copy(update={"params": {"target": "staging://khac.parquet"}}),
        *before.tasks[1:],
    )
    planner = Planner(MANIFEST_DIR, llm=LlmClient(FixedPlan(rewritten)))
    with pytest.raises(PlanError, match="viet de len viec da xong"):
        planner.replan("cau hoi", "raw://x.csv", before, "b hong", ("a",))


def test_the_replan_prompt_names_what_may_not_change() -> None:
    # Told plainly, the model spends its one attempt on the part that can move.
    request = build_replan_request(
        "cau hoi",
        available_agents(MANIFEST_DIR),
        "raw://x.csv",
        settled_plan(),
        "c hong",
        ("a", "b"),
    )
    assert '"frozen"' in request.prompt
    assert "DA CHAY XONG hoac DA DUOC NGUOI DUYET" in request.prompt


# --- the question reaches the one who has to answer it --------------------------


def test_a_plan_without_the_manager_gets_one_carrying_the_question() -> None:
    plan = plan_of(PlannedTask(task_id="t1", agent_id="a7_analyst"))
    ended = with_synthesis(plan, "diem thi phu thuoc vao gi", MANIFEST_DIR)
    manager = [task for task in ended.tasks if task.agent_id == "a9_manager"]
    assert len(manager) == 1
    assert manager[0].params["question"] == "diem thi phu thuoc vao gi"


def test_a_manager_the_model_planned_itself_is_given_the_real_question() -> None:
    """What the person asked, not the plan's restatement of it.

    The planner sometimes writes the synthesis step on its own, and when it does
    it writes its own instruction - "summarise the reports into an answer with
    evidence". The Manager checks its answer against what it was asked, so
    without this the check runs against the plan rather than against the person,
    and a paraphrase drops exactly the specifics that make a question answerable.

    Seen in a real run: asked which factor most affects the final exam score, the
    Manager was handed "produce a report answering the business question based on
    the analyses available" and scored its claims against that.
    """
    planned = plan_of(
        PlannedTask(task_id="t1", agent_id="a7_analyst"),
        PlannedTask(
            task_id="bao_cao",
            agent_id="a9_manager",
            depends_on=("t1",),
            params={"format": "markdown"},
            instruction="Tong hop cac phan tich thanh bao cao.",
        ),
    )
    ended = with_synthesis(planned, "yeu to nao anh huong den diem thi", MANIFEST_DIR)

    manager = [task for task in ended.tasks if task.agent_id == "a9_manager"]
    assert len(manager) == 1, "khong duoc them mot task tong hop thu hai"
    assert manager[0].params["question"] == "yeu to nao anh huong den diem thi"
    # The task itself is the model's, and stays that way.
    assert manager[0].task_id == "bao_cao"
    assert manager[0].params["format"] == "markdown", "khong duoc xoa param khac"
    assert manager[0].instruction == "Tong hop cac phan tich thanh bao cao."


# --- L90: ke hoach dung khuon nhung vo nghia ----------------------------------


def _plan(tasks: list[dict[str, object]]) -> Plan:
    return Plan.model_validate({"tasks": tasks})


def _manifests() -> dict[str, Manifest]:
    # The real manifests, so the check is exercised against the agents that
    # actually exist rather than a set invented for the test.
    return available_agents(MANIFEST_DIR)


def test_a_transform_nobody_reads_is_refused() -> None:
    # Measured on emotions.txt: a4 built exactly the right table - 16,000 rows
    # with a word count - and a7 was pointed at the source instead, so it saw
    # two text columns again and refused. Every task existed, every dependency
    # resolved, no cycle: the plan was well formed and pointless.
    plan = _plan(
        [
            {"task_id": "1", "agent_id": "a4_transformer", "instruction": "them cot so_tu"},
            {"task_id": "2", "agent_id": "a7_analyst", "instruction": "so sanh"},
            {
                "task_id": "t_answer",
                "agent_id": "a9_manager",
                "instruction": "tong hop",
                "depends_on": ["1", "2"],
                "inputs_from": ["1", "2"],
            },
        ]
    )
    problems = validate_plan(plan, _manifests())
    assert any("khong co tac dung gi" in problem for problem in problems)
    assert any("inputs_from" in problem for problem in problems)


def test_the_same_plan_wired_up_is_accepted() -> None:
    # One field different: the analysis task reads the table that was built.
    plan = _plan(
        [
            {"task_id": "1", "agent_id": "a4_transformer", "instruction": "them cot so_tu"},
            {
                "task_id": "2",
                "agent_id": "a7_analyst",
                "instruction": "so sanh",
                "depends_on": ["1"],
                "inputs_from": ["1"],
            },
            {
                "task_id": "t_answer",
                "agent_id": "a9_manager",
                "instruction": "tong hop",
                "depends_on": ["2"],
                "inputs_from": ["2"],
            },
        ]
    )
    assert validate_plan(plan, _manifests()) == []


def test_the_manager_reading_it_is_not_enough() -> None:
    # a9 summarises what the analysts found; it is not an analyst. A table only
    # it reads has still not been analysed by anything.
    plan = _plan(
        [
            {"task_id": "1", "agent_id": "a4_transformer", "instruction": "them cot"},
            {
                "task_id": "t_answer",
                "agent_id": "a9_manager",
                "instruction": "tong hop",
                "depends_on": ["1"],
                "inputs_from": ["1"],
            },
        ]
    )
    assert validate_plan(plan, _manifests()) != []


def test_a_plan_with_no_transform_is_left_alone() -> None:
    # Most plans have no transform at all. The check must be silent on them.
    plan = _plan([{"task_id": "1", "agent_id": "a7_analyst", "instruction": "mo ta"}])
    assert validate_plan(plan, _manifests()) == []


# --- mot lan sua, roi thoi -----------------------------------------------------


class TwoPlans:
    """Answers with a bad plan first, then a good one."""

    name = "test"

    def __init__(self, first: dict[str, Any], second: dict[str, Any]) -> None:
        self._answers = [Plan.model_validate(first), Plan.model_validate(second)]
        self.prompts: list[str] = []

    def complete(self, request: LlmRequest) -> LlmResponse:
        self.prompts.append(request.prompt)
        return LlmResponse(
            data=self._answers[min(len(self.prompts) - 1, len(self._answers) - 1)],
            provider=self.name,
            model="test",
        )


BROKEN = {
    "tasks": [
        {"task_id": "1", "agent_id": "a4_transformer", "instruction": "them cot so_tu"},
        {"task_id": "2", "agent_id": "a7_analyst", "instruction": "so sanh"},
    ]
}
WIRED = {
    "tasks": [
        {"task_id": "1", "agent_id": "a4_transformer", "instruction": "them cot so_tu"},
        {
            "task_id": "2",
            "agent_id": "a7_analyst",
            "instruction": "so sanh",
            "depends_on": ["1"],
            "inputs_from": ["1"],
        },
    ]
}


def test_a_transform_nobody_reads_is_wired_up_rather_than_refused() -> None:
    # The repair is unambiguous: one transform, one analysis task reading
    # nothing. Refusing here would mean refusing every plan these models
    # produce, since all three of them wire it the same wrong way.
    model = TwoPlans(BROKEN, BROKEN)
    planner = Planner(MANIFEST_DIR, llm=LlmClient(model))
    plan = planner.plan("do dai cau theo nhan", "clean://emotions.parquet", profile=None)
    assert [task.inputs_from for task in plan.tasks] == [(), ("1",)]
    assert plan.tasks[1].depends_on == ("1",)
    # One ask: the plan was fixed, not sent back.
    assert len(model.prompts) == 1


def test_two_transforms_are_not_wired_because_the_choice_is_real() -> None:
    # Which of the two tables did the analyst mean? Nothing here knows, and
    # picking one would be the guess this module exists to avoid.
    ambiguous = {
        "tasks": [
            {"task_id": "1", "agent_id": "a4_transformer", "instruction": "bang A"},
            {"task_id": "2", "agent_id": "a4_transformer", "instruction": "bang B"},
            {"task_id": "3", "agent_id": "a7_analyst", "instruction": "so sanh"},
        ]
    }
    assert wire_transforms(Plan.model_validate(ambiguous)) == Plan.model_validate(ambiguous)
    assert validate_plan(Plan.model_validate(ambiguous), _manifests()) != []


def test_a_rejected_plan_is_sent_back_with_the_reason() -> None:
    # A fault no repair can settle - the agent does not exist. The problems are
    # written to be acted on, so they go back to the model rather than only to
    # a person reading a stack trace.
    unknown = {"tasks": [{"task_id": "1", "agent_id": "a99_khong_co", "instruction": "x"}]}
    good = {"tasks": [{"task_id": "1", "agent_id": "a7_analyst", "instruction": "mo ta"}]}
    model = TwoPlans(unknown, good)
    planner = Planner(MANIFEST_DIR, llm=LlmClient(model))
    plan = planner.plan("cau hoi", "clean://x.parquet", profile=None)
    assert plan.tasks[0].agent_id == "a7_analyst"
    assert len(model.prompts) == 2
    assert "ke_hoach_truoc_bi_tu_choi" in model.prompts[1]
    assert "a99_khong_co" in model.prompts[1]


def test_a_plan_still_broken_after_the_correction_is_refused() -> None:
    # Two asks and stop. More would be a loop, not a correction.
    unknown = {"tasks": [{"task_id": "1", "agent_id": "a99_khong_co", "instruction": "x"}]}
    model = TwoPlans(unknown, unknown)
    planner = Planner(MANIFEST_DIR, llm=LlmClient(model))
    with pytest.raises(PlanError) as refused:
        planner.plan("cau hoi", "clean://x.parquet", profile=None)
    assert "khong chay duoc" in str(refused.value)
    assert len(model.prompts) == 2
