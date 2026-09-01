"""The planner: turn a question into a DAG of agent calls.

Phase 1 declared its DAG because it had two agents and there was nothing to
reason about. With eight there is: which agents are needed at all, in what
order, and what each one should be told to do. That is the first thing in this
system genuinely worth asking a model.

What the model produces is a plan, not an action. Every plan is checked before
anything runs:

* every agent named must exist, with a manifest;
* every dependency must name a task in the same plan;
* the graph must be acyclic, or the run would never finish;
* task ids must be unique, or state would overwrite itself;
* a task may only read from a task guaranteed to have run before it.

A plan that fails any of these is rejected whole. Repairing it would mean
guessing an order nobody chose.

Ordering is deterministic: among tasks whose dependencies are all met, the one
with the smallest id goes first. Two runs of the same plan therefore execute in
the same sequence, which criterion S1 needs.
"""

from __future__ import annotations

import json
from collections.abc import Collection
from pathlib import Path
from typing import Any, Final

from analysis_system.contracts.agents import Plan, PlannedTask
from analysis_system.services.boundary import (
    DEFAULT_MANIFEST_DIR as BOUNDARY_MANIFEST_DIR,
)
from analysis_system.services.boundary import Manifest, load_manifest
from analysis_system.services.llm import LlmClient, LlmRequest
from analysis_system.services.prompts import load_prompt

# The same directory the boundary layer reads, so a manifest cannot be
# visible to one and invisible to the other.
DEFAULT_MANIFEST_DIR: Final[Path] = BOUNDARY_MANIFEST_DIR


class PlanError(RuntimeError):
    """The plan cannot be executed as written."""


def available_agents(manifest_dir: Path | None = None) -> dict[str, Manifest]:
    """Every agent that has a manifest, keyed by id.

    A manifest is what makes an agent real: without one there is no boundary to
    enforce, so an agent that has none cannot be planned in.
    """
    root = manifest_dir or DEFAULT_MANIFEST_DIR
    if not root.is_dir():
        return {}
    found: dict[str, Manifest] = {}
    for path in sorted(root.glob("*.yaml")):
        try:
            manifest = load_manifest(path.stem, root)
        except Exception:  # noqa: BLE001 - a broken manifest is simply not offered
            continue
        found[manifest.agent_id] = manifest
    return found


def describe_agents(manifests: dict[str, Manifest]) -> list[dict[str, Any]]:
    """The agent registry as the planner is shown it."""
    return [
        {
            "agent_id": manifest.agent_id,
            "description": manifest.description,
            "reads": list(manifest.allow.read),
            "writes": list(manifest.allow.write),
            "uses_llm": manifest.allow.llm.enabled,
            "human_gate": manifest.human_gate.required,
        }
        for manifest in sorted(manifests.values(), key=lambda item: item.agent_id)
    ]


def validate_plan(plan: Plan, manifests: dict[str, Manifest]) -> list[str]:
    """Everything that would stop this plan from running.

    Returns:
        A list of problems, not just the first one, so a replan sees the whole
        picture at once. Empty means the plan may be executed.
    """
    problems: list[str] = []
    if not plan.tasks:
        return ["ke hoach rong - khong co task nao"]

    seen: set[str] = set()
    for task in plan.tasks:
        if task.task_id in seen:
            problems.append(f"task_id {task.task_id!r} xuat hien nhieu lan")
        seen.add(task.task_id)
        if task.agent_id not in manifests:
            known = ", ".join(sorted(manifests))
            problems.append(
                f"task {task.task_id!r} goi agent {task.agent_id!r} khong ton tai. Co: {known}"
            )

    for task in plan.tasks:
        for dependency in (*task.depends_on, *task.inputs_from):
            if dependency not in seen:
                problems.append(
                    f"task {task.task_id!r} phu thuoc {dependency!r} khong co trong ke hoach"
                )
            if dependency == task.task_id:
                problems.append(f"task {task.task_id!r} phu thuoc chinh no")

    if problems:
        return problems

    try:
        topological_order(plan)
    except PlanError as error:
        return [str(error)]

    # Reading from a task that is not guaranteed to have run first would mean
    # reading a file that does not exist yet.
    reachable = transitive_dependencies(plan)
    for task in plan.tasks:
        for upstream in task.inputs_from:
            if upstream not in reachable[task.task_id]:
                problems.append(
                    f"task {task.task_id!r} doc ket qua cua {upstream!r} "
                    "nhung khong doi task do chay xong"
                )
    return problems


def topological_order(plan: Plan) -> list[str]:
    """Task ids in the order they may run.

    Among tasks whose dependencies are all satisfied, the smallest id goes
    first. Without that tie-break the order would depend on dictionary
    iteration and two identical runs could execute differently.

    Raises:
        PlanError: the graph has a cycle, so no order exists.
    """
    pending = {task.task_id: set(task.depends_on) for task in plan.tasks}
    ordered: list[str] = []

    while pending:
        ready = sorted(task_id for task_id, waiting in pending.items() if not waiting)
        if not ready:
            stuck = ", ".join(sorted(pending))
            raise PlanError(f"Ke hoach co chu trinh, khong bao gio chay xong: {stuck}")
        for task_id in ready:
            ordered.append(task_id)
            del pending[task_id]
        for waiting in pending.values():
            waiting.difference_update(ready)
    return ordered


def transitive_dependencies(plan: Plan) -> dict[str, set[str]]:
    """For each task, every task guaranteed to have finished before it.

    Only meaningful on an acyclic plan, so callers check the graph first.
    """
    direct = {task.task_id: set(task.depends_on) for task in plan.tasks}
    resolved: dict[str, set[str]] = {}
    for task_id in topological_order(plan):
        reachable: set[str] = set()
        for parent in direct[task_id]:
            reachable.add(parent)
            reachable |= resolved.get(parent, set())
        resolved[task_id] = reachable
    return resolved


def ordered_tasks(plan: Plan) -> list[PlannedTask]:
    """The plan tasks, in execution order."""
    by_id = {task.task_id: task for task in plan.tasks}
    return [by_id[task_id] for task_id in topological_order(plan)]


def build_plan_request(question: str, manifests: dict[str, Manifest], source: str) -> LlmRequest:
    """Build the one question the planner asks."""
    return _request(
        {
            "question": question,
            "source": source,
            "agents": describe_agents(manifests),
            "rules": _RULES,
        }
    )


def build_replan_request(
    question: str,
    manifests: dict[str, Manifest],
    source: str,
    failed: Plan,
    failure: str,
    frozen: tuple[str, ...] = (),
) -> LlmRequest:
    """Build the question asked after a plan has already failed once.

    The failed plan and the reason go in whole. A replan that cannot see what
    went wrong would simply propose the same thing again.

    Which tasks are frozen goes in too. The model could not know that a person
    already approved a step; told plainly, it spends its one attempt on the part
    that can still change.
    """
    rules = [
        *_RULES,
        "Ke hoach truoc da that bai vi ly do ghi o truong failure.",
        "Ke hoach moi PHAI khac ke hoach cu. Lap lai y nguyen se that bai y nguyen.",
    ]
    if frozen:
        rules += [
            "Cac task trong 'frozen' DA CHAY XONG hoac DA DUOC NGUOI DUYET.",
            "Giu chung y nguyen: dung task_id, agent_id, depends_on, inputs_from, params.",
            "Chi duoc sua hoac them cac task CHUA chay.",
        ]
    return _request(
        {
            "question": question,
            "source": source,
            "agents": describe_agents(manifests),
            "failed_plan": failed.model_dump(mode="json"),
            "failure": failure,
            "frozen": list(frozen),
            "rules": rules,
        }
    )


# Fields that decide what a task actually does. A frozen task may not differ on
# any of them; its instruction text may, because a task that will not run again
# is not affected by how it was once phrased.
EXECUTION_FIELDS: Final[tuple[str, ...]] = ("agent_id", "depends_on", "inputs_from", "params")


def frozen_conflicts(previous: Plan, proposed: Plan, frozen: Collection[str]) -> list[str]:
    """Every way a proposal would rewrite work that already happened.

    Returns:
        A list of problems. Empty means the proposal leaves settled work alone.
    """
    was = {task.task_id: task for task in previous.tasks}
    now = {task.task_id: task for task in proposed.tasks}
    problems: list[str] = []

    for task_id in sorted(frozen):
        before = was.get(task_id)
        if before is None:
            continue
        after = now.get(task_id)
        if after is None:
            problems.append(
                f"task {task_id!r} da chay xong nhung ke hoach moi bo han - "
                "ket qua cua no se thanh mo coi"
            )
            continue
        for field in EXECUTION_FIELDS:
            if getattr(before, field) != getattr(after, field):
                problems.append(
                    f"task {task_id!r} da chay xong nhung ke hoach moi doi {field}: "
                    f"{getattr(before, field)!r} -> {getattr(after, field)!r}"
                )
    return problems


_RULES: Final[tuple[str, ...]] = (
    "Chi duoc goi agent co trong danh sach.",
    "Moi depends_on phai tro toi task_id khac trong cung ke hoach.",
    "Khong duoc tao chu trinh.",
    "Agent doc tang nao thi phai co task truoc do ghi vao tang do.",
    "inputs_from chi duoc tro toi task chac chan da chay xong truoc do.",
    "Chi dua vao ke hoach nhung agent that su can cho cau hoi nay.",
)


def _request(payload: dict[str, Any]) -> LlmRequest:
    """Wrap a payload as the planner request. One prompt serves both cases."""
    return LlmRequest(
        purpose="manager_plan",
        system=load_prompt("manager_plan"),
        prompt=json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        schema=Plan,
    )


def default_plan(source: str) -> Plan:
    """The standard pipeline, for when no model is available.

    Not a fallback the planner reaches for silently: the caller asks for it
    explicitly. A plan nobody chose should never be mistaken for one a model
    reasoned about.
    """
    return Plan(
        tasks=(
            PlannedTask(
                task_id="t1_ingest",
                agent_id="a1_ingest",
                instruction="Nap du lieu nguon vao staging, khong sua gi.",
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
                # Runs after the profile, but reads the staged table.
                inputs_from=("t1_ingest",),
                instruction="De xuat rule lam sach, cho nguoi duyet.",
            ),
            PlannedTask(
                task_id="t4_transform",
                agent_id="a4_transformer",
                depends_on=("t3_clean",),
                instruction="Dung bang mart tra loi cau hoi.",
            ),
            PlannedTask(
                task_id="t5_validate",
                agent_id="a5_validator",
                depends_on=("t4_transform",),
                instruction="Cham bang mart theo tieu chi da khai bao.",
            ),
            PlannedTask(
                task_id="t6_analyse",
                agent_id="a7_analyst",
                depends_on=("t5_validate",),
                # Runs only if validation passed, but reads the mart itself.
                inputs_from=("t4_transform",),
                instruction="Rut ket luan co bang chung tu bang mart.",
            ),
            PlannedTask(
                task_id="t7_report",
                agent_id="a8_reporter",
                depends_on=("t6_analyse",),
                instruction="Xuat bao cao tu cac ket luan da duyet.",
            ),
        ),
        reason=f"Ke hoach mac dinh cho nguon {source}, khong dung model.",
    )


class Planner:
    """Produces a checked plan, from a model or from the declared default."""

    def __init__(self, manifest_dir: Path | None = None, *, llm: LlmClient | None = None) -> None:
        """Bind the planner to a manifest directory and an optional model."""
        self._manifests = available_agents(manifest_dir)
        self._llm = llm

    @property
    def agents(self) -> dict[str, Manifest]:
        """Every agent this planner may use."""
        return self._manifests

    @property
    def has_model(self) -> bool:
        """True when this planner can actually reason about a plan."""
        return self._llm is not None

    def plan(self, question: str, source: str) -> Plan:
        """Produce a plan and check it before returning.

        Raises:
            PlanError: the model produced a plan that cannot be executed.
        """
        if self._llm is None:
            return default_plan(source)
        return self._checked(build_plan_request(question, self._manifests, source))

    def replan(
        self,
        question: str,
        source: str,
        failed: Plan,
        failure: str,
        frozen: tuple[str, ...] = (),
    ) -> Plan:
        """Propose a different plan after one has failed.

        Raises:
            PlanError: there is no model, the new plan does not check out, it is
                the plan that just failed, or it rewrites work already done.
                Running the same graph after the same failure is a loop; running
                a graph that contradicts what a person approved is worse.
        """
        if self._llm is None:
            raise PlanError("Khong co model, khong the lap lai ke hoach.")
        proposed = self._checked(
            build_replan_request(question, self._manifests, source, failed, failure, frozen)
        )
        if proposed.tasks == failed.tasks:
            raise PlanError("Ke hoach moi trung y het ke hoach vua that bai.")

        conflicts = frozen_conflicts(failed, proposed, frozen)
        if conflicts:
            raise PlanError("Ke hoach moi viet de len viec da xong: " + "; ".join(conflicts))
        return proposed

    def _checked(self, request: LlmRequest) -> Plan:
        """Ask the model, and refuse anything that would not run."""
        answer = self._llm.complete(request) if self._llm else None
        if answer is None or not isinstance(answer.data, Plan):
            raise PlanError("Model khong tra ve dung Plan.")
        problems = validate_plan(answer.data, self._manifests)
        if problems:
            raise PlanError("Ke hoach khong chay duoc: " + "; ".join(problems))
        return answer.data
