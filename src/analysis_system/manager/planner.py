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
from collections.abc import Collection, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, Final

from analysis_system.contracts.agents import Plan, PlannedTask, ProfileReport
from analysis_system.services.asked_columns import ASKED_PARAM
from analysis_system.services.boundary import (
    DEFAULT_MANIFEST_DIR as BOUNDARY_MANIFEST_DIR,
)
from analysis_system.services.boundary import Manifest, load_manifest
from analysis_system.services.glossary_store import GLOSSARY_PARAM
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


# The agent that builds a table, and the ones that exist to read one.
TRANSFORM_AGENT: Final[str] = "a4_transformer"
ANALYSIS_AGENTS: Final[frozenset[str]] = frozenset(
    {"a5_validator", "a6_process_miner", "a7_analyst", "a10_text_miner"}
)


# Tham so noi voi a4 rang bang no dung se di vao tang thong ke, nen phai giu
# nguyen tung dong.
ROW_LEVEL_PARAM: Final[str] = "giu_tung_dong"


def keeping_rows(plan: Plan) -> Plan:
    """Đánh dấu các bước dựng bảng mà tầng thống kê sẽ đọc.

    Đo trên lượt chạy thật: a4 viết `GROUP BY poutcome, y`, 41.176 dòng thành
    6, rồi 6 dòng đó đi vào tầng thống kê và mọi phép kiểm chết vì *"dưới 5
    quan sát"*. Câu SQL không sai; nó sai ở chỗ **đứng trước** tầng thống kê.

    Chỉ kế hoạch biết được điều đó — a4 nhìn một mình thì không thấy bảng của
    nó chảy đi đâu. Nên chỗ đánh dấu là ở đây, còn chỗ tuân theo là ở a4.
    """
    readers = {
        source
        for task in plan.tasks
        if task.agent_id in ANALYSIS_AGENTS
        for source in (task.inputs_from or task.depends_on)
    }
    if not readers:
        return plan
    tasks = tuple(
        task.model_copy(update={"params": {**task.params, ROW_LEVEL_PARAM: True}})
        if task.agent_id == TRANSFORM_AGENT and task.task_id in readers
        else task
        for task in plan.tasks
    )
    return plan.model_copy(update={"tasks": tasks})


def _unread_transforms(plan: Plan) -> list[str]:
    """Transform tasks whose table no analysis task ever reads.

    Measured on emotions.txt. The question needed average sentence length, a
    measure that was not a column. The Manager did the hard half right - it
    planned a4_transformer, and a4 built exactly the right table, 16,000 rows
    with a word count - and then pointed a7_analyst at the *source* instead of
    at that table. So a7 saw two text columns again, refused for want of a
    numeric one, and the whole transform was wasted.

    Nothing caught it: every task existed, every dependency resolved, no cycle.
    The plan was well formed and pointless. This is the check that says so,
    and it is a plan-level fault, so it comes back as a replan rather than as
    an answer built on the wrong table.
    """
    built = {task.task_id for task in plan.tasks if task.agent_id == TRANSFORM_AGENT}
    if not built:
        return []
    read: set[str] = set()
    for task in plan.tasks:
        if task.agent_id in ANALYSIS_AGENTS:
            read.update(task.inputs_from)
    return [
        f"task {task_id!r} ({TRANSFORM_AGENT}) tao ra mot bang ma khong agent phan tich nao "
        f"doc: hay dat inputs_from={[task_id]} cho task phan tich, neu khong buoc bien doi nay "
        "khong co tac dung gi"
        for task_id in sorted(built - read)
    ]


def wire_transforms(plan: Plan) -> Plan:
    """Point analysis tasks at the table a transform built, when that is unambiguous.

    Three models, from 12B to 120B, produced the same plan: a4 builds the
    table, a7 reads the *source*, and a9 gets `inputs_from` for both - they all
    read the Manager as the place where results are gathered. Explaining
    `inputs_from` in the prompt changed nothing, which by now is the expected
    outcome of arguing with a habit.

    So code does it. This is not guessing: with exactly one transform in the
    plan and an analysis task that reads nothing, there is precisely one table
    it could mean. Two transforms and it *would* be guessing, so it stops and
    lets `validate_plan` refuse.
    """
    built = [task.task_id for task in plan.tasks if task.agent_id == TRANSFORM_AGENT]
    if len(built) != 1:
        return plan
    source = built[0]
    if any(source in task.inputs_from for task in plan.tasks if task.agent_id in ANALYSIS_AGENTS):
        return plan

    rewired = [
        task.model_copy(
            update={
                "inputs_from": (source,),
                "depends_on": task.depends_on
                if source in task.depends_on
                else (*task.depends_on, source),
            }
        )
        if task.agent_id in ANALYSIS_AGENTS and not task.inputs_from
        else task
        for task in plan.tasks
    ]
    return plan.model_copy(update={"tasks": rewired})


# Tham so ma thieu no thi agent chet ngay, khong phai chay do roi bao. Bat o
# day - truoc khi bat cu buoc nao chay - thi khong ton mot dong nao va khong ai
# phai doi. Cung mot hinh nhu RULE_PARAMS cua rulebook va GATE_PARAM cua
# dag_runner: mot bang nho, doc duoc, nam canh cho no duoc dung.
REQUIRED_PARAMS: Final[Mapping[str, frozenset[str]]] = {
    # Cham du lieu theo tieu chi nao thi phai co ai do noi ra. Doan ho la tu
    # dinh nghia the nao la "dat", va do la mot nhan dinh chu khong phai mot
    # phep do.
    "a5_validator": frozenset({"checks"}),
}


def validate_plan(plan: Plan, manifests: dict[str, Manifest]) -> list[str]:
    """Everything that would stop this plan from running.

    Returns:
        A list of problems, not just the first one, so a replan sees the whole
        picture at once. Empty means the plan may be executed.
    """
    problems: list[str] = []
    if not plan.tasks:
        return ["ke hoach rong - khong co task nao"]

    for task in plan.tasks:
        for name in sorted(REQUIRED_PARAMS.get(task.agent_id, frozenset())):
            if name not in task.params:
                problems.append(
                    f"task {task.task_id!r} ({task.agent_id}) thieu tham so bat buoc "
                    f"{name!r} - buoc nay se chet ngay khi chay, hay khai no hoac bo "
                    "buoc nay khoi ke hoach"
                )

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

    problems.extend(_unread_transforms(plan))

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


def waves(plan: Plan) -> list[list[PlannedTask]]:
    """The same order, grouped by what may run at the same time.

    A wave is every task whose dependencies are already met, so nothing inside
    one wave depends on anything else inside it. Asked which words characterise
    `sadness` and which characterise `fear`, the Manager plans two tasks that
    share nothing at all - and they ran one after the other because the runner
    only knew how to walk a list.

    Flattening this gives back exactly `ordered_tasks`, and each wave is sorted
    by id, so the sequence tasks are *considered* in does not change. That is
    what criterion S1 asks for, and running them at the same time does not
    disturb it: a wave holds no task that could read another's output.

    Raises:
        PlanError: the graph has a cycle, so no order exists.
    """
    by_id = {task.task_id: task for task in plan.tasks}
    pending = {task.task_id: set(task.depends_on) for task in plan.tasks}
    grouped: list[list[PlannedTask]] = []

    while pending:
        ready = sorted(task_id for task_id, waiting in pending.items() if not waiting)
        if not ready:
            stuck = ", ".join(sorted(pending))
            raise PlanError(f"Ke hoach co chu trinh, khong bao gio chay xong: {stuck}")
        grouped.append([by_id[task_id] for task_id in ready])
        for task_id in ready:
            del pending[task_id]
        for waiting in pending.values():
            waiting.difference_update(ready)
    return grouped


def describe_data(profile: ProfileReport | None) -> dict[str, Any]:
    """What the planner is told about the data it is planning against.

    Structure and shape, never values. Which columns exist, what each looks
    like, whether the rows are events with a case and a timestamp, and what A2
    noticed about quality. That is enough to decide what is worth asking and not
    enough to quote a figure from - the same line every other prompt draws.

    An absent profile is described as absent rather than omitted. A planner that
    cannot tell "no time column" from "nobody looked" will plan as though it
    knows something it does not.
    """
    if profile is None:
        return {
            "profiled": False,
            "note": "chua lap ho so - ke hoach dang duoc lap khi CHUA nhin thay du lieu",
        }
    roles = profile.eventlog_candidates
    return {
        "profiled": True,
        "rows": profile.row_count,
        "columns": [
            {
                "name": column.name,
                "dtype": column.dtype,
                "distinct": column.distinct,
                "null_pct": column.null_pct,
                # What separates a measure from a category code. A column staged
                # as text can still hold numbers, and the dtype alone does not
                # say - so a planner told to find numeric columns needs this.
                "numeric_share": column.numeric_share,
            }
            for column in profile.columns
        ],
        # The single most consequential fact about a table: are its rows events?
        # If they are, questions about order and waiting become answerable, and
        # if they are not, planning process mining is planning to fail.
        "is_event_log": roles.is_complete,
        "event_log_roles": roles.model_dump(mode="json"),
        "pii_columns": list(profile.pii_flags),
        "quality_notes": list(profile.observations),
    }


def build_plan_request(
    question: str,
    manifests: dict[str, Manifest],
    source: str,
    profile: ProfileReport | None = None,
) -> LlmRequest:
    """Build the one question the planner asks."""
    return _request(
        {
            "question": question,
            "source": source,
            # Where in the pipeline this plan starts. A plan for already-clean
            # data that begins by loading and cleaning it again would redo work
            # a person has already approved.
            "stage": "clean" if source.startswith("clean://") else "raw",
            "data": describe_data(profile),
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
    # Measured on emotions.txt: two text columns, and the question asked about
    # average sentence length in words. The plan was a7_analyst alone, which
    # refused - "bang khong co du cot so". The measure the question needed did
    # not exist yet, and nothing in the plan was going to create it. The
    # Manager was never told it could.
    "Neu cau hoi noi ve mot DAI LUONG chua ton tai thanh cot trong 'data' - do dai "
    "cau, so tu, so ky tu, ty le giua hai cot, thoi gian giua hai moc - thi phai co "
    "mot task a4_transformer TRUOC de tinh ra cot do, roi agent phan tich moi doc "
    "duoc. a7_analyst chi doc cot da co san; no khong tu tao cot moi.",
    "Cot chua van ban tu do khong phai la cot so. Muon dem tu, dem ky tu hay do do "
    "dai thi phai tinh ra cot so o buoc a4_transformer truoc.",
)


def _with_corrections(request: LlmRequest, problems: list[str]) -> LlmRequest:
    """The same question again, with what was wrong with the last answer.

    Asking the identical question and hoping for a different plan is not a
    strategy - the same rule A7 follows on a retry.
    """
    payload = json.loads(request.prompt)
    payload["ke_hoach_truoc_bi_tu_choi"] = problems
    payload["sua_lai"] = (
        "Ke hoach ban vua dua ra khong chay duoc, vi nhung ly do tren. "
        "Sua dung nhung cho do roi dua lai ca ke hoach."
    )
    return replace(
        request, prompt=json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    )


def _request(payload: dict[str, Any]) -> LlmRequest:
    """Wrap a payload as the planner request. One prompt serves both cases."""
    return LlmRequest(
        purpose="manager_plan",
        system=load_prompt("manager_plan"),
        prompt=json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        schema=Plan,
    )


SYNTHESIS_AGENT: Final[str] = "a9_manager"
SYNTHESIS_TASK: Final[str] = "t_answer"


def _readable_by(reader: Manifest, writer: Manifest) -> bool:
    """True when everything the writer produces is inside what the reader may read."""
    return bool(writer.allow.write) and all(
        any(_covers(allowed, target) for allowed in reader.allow.read)
        for target in writer.allow.write
    )


def _covers(pattern: str, target: str) -> bool:
    """Whether one layer pattern includes another.

    Both are of the form `layer://**`, so the comparison is on the layer alone.
    Anything more elaborate belongs in the boundary module, which already does it
    properly at run time; this only has to decide what to hand over.
    """
    return pattern.split("://", 1)[0] == target.split("://", 1)[0]


CONTEXT_PARAM: Final[str] = "boi_canh"


def with_context(plan: Plan, context: str) -> Plan:
    """Bối cảnh của bộ dữ liệu, gắn vào mọi bước — không chỉ bước cuối.

    Bước phân tích cần nó y như bước tổng hợp: một con số chỉ có nghĩa khi biết
    nó đo cái gì, và người biết điều đó là người tải tệp lên.

    Để trống thì kế hoạch không đổi một chữ - không có bối cảnh không phải là
    một loại bối cảnh.
    """
    if not context.strip():
        return plan
    return plan.model_copy(
        update={
            "tasks": tuple(
                task.model_copy(update={"params": {**task.params, CONTEXT_PARAM: context}})
                for task in plan.tasks
            )
        }
    )


def with_glossary(plan: Plan, glossary: str) -> Plan:
    """Bảng chú giải, gắn vào mọi bước cho code đối chiếu đọc.

    Tách khỏi `boi_canh`: bối cảnh đi thẳng vào prompt, còn cả bảng chú giải thì
    không. Để trống thì kế hoạch không đổi một chữ.
    """
    if not glossary.strip():
        return plan
    return plan.model_copy(
        update={
            "tasks": tuple(
                task.model_copy(update={"params": {**task.params, GLOSSARY_PARAM: glossary}})
                for task in plan.tasks
            )
        }
    )


def with_asked(plan: Plan, question: str) -> Plan:
    """Câu hỏi GỐC của người dùng, gắn vào mọi bước để chọn cột.

    Tham số riêng, không thay lời dặn: một bước biến đổi vẫn làm đúng việc của
    nó, chỉ phần chọn cột ưu tiên mới đọc câu hỏi gốc.
    """
    if not question.strip():
        return plan
    return plan.model_copy(
        update={
            "tasks": tuple(
                task.model_copy(update={"params": {**task.params, ASKED_PARAM: question}})
                for task in plan.tasks
            )
        }
    )


def with_synthesis(plan: Plan, question: str, manifest_dir: Path | None = None) -> Plan:
    """The same plan, ending with the Manager answering the question.

    Appended rather than planned. Whether a question gets an answer is not a
    judgement call - it is what asking one means - and leaving it to the model
    would make some questions come back answered and others as a pile of
    findings, with no way to know which in advance.

    Args:
        plan: what the planner produced.
        question: what to answer.
        manifest_dir: where the manifests live.

    Returns:
        The plan with a synthesis task, or unchanged when there is nothing for
        the Manager to read or it is already there.
    """
    # The model sometimes plans the synthesis step itself, and when it does it
    # writes its own instruction - a restatement of the question rather than the
    # question. The Manager checks its answer against what it was asked, so a
    # restatement means checking against the plan instead of against the person,
    # and the paraphrase drops exactly the specifics that make a question
    # answerable. The task stays as planned; the question is put back into it.
    if any(task.agent_id == SYNTHESIS_AGENT for task in plan.tasks):
        return plan.model_copy(
            update={
                "tasks": tuple(
                    task.model_copy(update={"params": {**task.params, "question": question}})
                    if task.agent_id == SYNTHESIS_AGENT
                    else task
                    for task in plan.tasks
                )
            }
        )
    manifests = available_agents(manifest_dir)
    manager = manifests.get(SYNTHESIS_AGENT)
    if manager is None or not plan.tasks:
        return plan

    # Handed only what it is allowed to read. Worked out from the manifests, so
    # a skill added later qualifies on the strength of its own boundary rather
    # than by being named here.
    readable = tuple(
        task.task_id
        for task in plan.tasks
        if task.agent_id in manifests and _readable_by(manager, manifests[task.agent_id])
    )
    if not readable:
        return plan

    return plan.model_copy(
        update={
            "tasks": (
                *plan.tasks,
                PlannedTask(
                    task_id=SYNTHESIS_TASK,
                    agent_id=SYNTHESIS_AGENT,
                    depends_on=tuple(task.task_id for task in plan.tasks),
                    inputs_from=readable,
                    params={"question": question},
                    instruction="Tong hop bao cao cua cac agent thanh cau tra loi co bang chung.",
                ),
            )
        }
    )


def cleaning_plan() -> Plan:
    """Turn a file into a table a person can look at, and stop there.

    Takes no source: which file this runs on is supplied when the run
    starts, not baked into the plan, so the same three steps serve any input.

    Fixed rather than planned, and that is the point: loading, describing and
    cleaning are the same three steps whatever the question turns out to be, and
    at this stage there is no question yet. Asking a model to plan them would be
    asking it to reason about something with one right answer.
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
                instruction="Mo ta du lieu da nap: cot nao, kieu gi, chat luong ra sao.",
            ),
            PlannedTask(
                task_id="t3_clean",
                agent_id="a3_cleaner",
                depends_on=("t2_profile",),
                inputs_from=("t1_ingest",),
                instruction="De xuat rule lam sach, cho nguoi duyet.",
            ),
        ),
        reason="Lam sach du lieu de nguoi dung xem truoc khi dat cau hoi.",
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
                # Khai RONG, khong phai bo trong. Duong chay mac dinh khong biet
                # tieu chi nao dang de cham - no chay khi khong co model va
                # khong ai noi ra dieu do - nhung A5 co san duong xu ly cho
                # truong hop nay: no chay, khong kiem gi, va noi thang "du lieu
                # CHUA DUOC KIEM, khong phai da kiem va dat".
                #
                # Cung mot phan biet a3_cleaner da dat: vang mat la bo sot, co
                # ma rong la mot cau tra loi. Bo trong thi A5 chet han va ca
                # duong chay mac dinh chet theo.
                params={"checks": {}},
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

    def plan(self, question: str, source: str, profile: ProfileReport | None = None) -> Plan:
        """Produce a plan and check it before returning.

        Args:
            question: what the person wants to know.
            source: where the data is.
            profile: what A2 found in it. Absent means the plan is being made
                without having looked, which is worth knowing and is said out
                loud in the prompt rather than passed over in silence.

        Raises:
            PlanError: the model produced a plan that cannot be executed.
        """
        if self._llm is None:
            return default_plan(source)
        return self._checked(build_plan_request(question, self._manifests, source, profile))

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
        """Ask the model, and refuse anything that would not run.

        One correction is offered before refusing. The problems are written to
        be acted on - they name the task and the field to change - and without
        a second ask the only reader of that advice is a person looking at a
        stack trace. Asking twice and giving up keeps it a correction rather
        than a loop.
        """
        problems: list[str] = []
        for attempt in range(2):
            asked = request if attempt == 0 else _with_corrections(request, problems)
            answer = self._llm.complete(asked) if self._llm else None
            if answer is None or not isinstance(answer.data, Plan):
                raise PlanError("Model khong tra ve dung Plan.")
            proposed = wire_transforms(answer.data)
            problems = validate_plan(proposed, self._manifests)
            if not problems:
                return proposed
        raise PlanError("Ke hoach khong chay duoc: " + "; ".join(problems))
