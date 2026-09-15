"""What the system can do, as operations that return data.

Until now the command line *was* the application: it decided what to run and
printed the outcome in the same breath, so the only way to use the system was to
read a terminal. A second front end could not call any of it without also
inheriting a Console.

Everything here returns a value and prints nothing. It raises `ServiceError`
rather than exiting, because deciding what to do about a failure belongs to
whoever asked - a terminal exits, a web request returns a status, and neither
choice should be made down here.

The command line becomes one presenter of this. A web application would be a
second, calling the same methods and rendering the same objects, which is the
point: the logic is not written twice and cannot drift.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar, Literal

import pandas as pd

from analysis_system.agents.a2_profiler import refreshed_profile
from analysis_system.contracts.agents import (
    AnalysisResult,
    ManagerAnswer,
    Plan,
    ProcessMap,
    ProfileReport,
)
from analysis_system.contracts.base import DataFormat, DataRef
from analysis_system.manager.dag_runner import DagRunner
from analysis_system.manager.gates import GateError, GateStore, decide
from analysis_system.manager.planner import (
    PlanError,
    Planner,
    cleaning_plan,
    keeping_rows,
    with_asked,
    with_context,
    with_glossary,
    with_synthesis,
)
from analysis_system.manager.runner import RunOutcome
from analysis_system.manager.selection import affected_tasks, apply_selection
from analysis_system.manager.state import RunState, StateError, StateStore
from analysis_system.services import dataset_removal, retention, storage
from analysis_system.services.bpmn import BpmnError, to_bpmn
from analysis_system.services.budget import (
    BudgetError,
    BudgetExceeded,
    BudgetTracker,
    load_budget,
    load_pricing,
    record,
)
from analysis_system.services.data_scope import parse_recipe, recipe_of, shown_condition
from analysis_system.services.dataset_context import MAX_LENGTH as CONTEXT_LIMIT
from analysis_system.services.dataset_context import read_context, write_context
from analysis_system.services.features import (
    FeatureCatalogue,
    FeatureError,
    Selection,
    catalogue_for,
)
from analysis_system.services.glossary_draft import GlossaryProposal
from analysis_system.services.glossary_draft import as_lines as glossary_lines
from analysis_system.services.glossary_draft import build_request as build_glossary_request
from analysis_system.services.glossary_draft import verified as verified_glossary
from analysis_system.services.glossary_store import (
    GlossaryTooLongError,
    as_text,
    for_prompt,
    read_glossary,
    rows_for,
    without_glossary_lines,
    write_glossary,
)
from analysis_system.services.llm import (
    AllModelsFailedError,
    AnthropicProvider,
    CassetteProvider,
    GeminiProvider,
    HandoffProvider,
    LlmClient,
    LlmError,
    OpenRouterProvider,
)
from analysis_system.services.rule_names import in_plain_words
from analysis_system.services.value_labels import (
    categories_of,
    effective_labels,
    labels_text,
    parse_labels,
    read_labels,
    suggested,
    write_labels,
)
from analysis_system.settings import (
    ConfigError,
    Settings,
    cassette_path,
    load_settings,
    resolve,
    verify_layers,
)
from analysis_system.web.naming import ROUND_MARK

CONFIG_ENV_VAR = "ANALYSIS_SYSTEM_CONFIG"
BUDGET_FILE = "budget.yaml"
PRICING_FILE = "pricing.yaml"
PLAN_FILENAME = "plan.json"
BASE_PLAN_FILENAME = "plan.base.json"
SELECTION_FILENAME = "selection.json"
STATE_FILENAME = "state.json"

# Agents that read what the cleaning stage produced. Used to tell a run that
# stopped after cleaning from one that carried on into analysis.
ANALYSIS_AGENTS = frozenset({"a4_transformer", "a6_process_miner", "a7_analyst", "a8_reporter"})

RunStatus = Literal["completed", "paused", "halted", "failed"]


class ServiceError(RuntimeError):
    """An operation cannot be carried out, with something a person can act on.

    Carries a hint separately from the message because the two are read at
    different moments: the message says what went wrong, the hint says what to
    do next, and a front end may well want to show them differently.
    """

    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


@dataclass(frozen=True)
class TaskReport:
    """How one task ended."""

    task_id: str
    agent_id: str
    status: str
    message: str = ""


@dataclass(frozen=True)
class Declined:
    """Something a skill would not claim, and which skill would not claim it."""

    agent_id: str
    note: str


@dataclass(frozen=True)
class Spend:
    """What a run cost, and anything the ceiling wanted to say about it."""

    tokens: int = 0
    cost_usd: float = 0.0
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class RunReport:
    """What happened in one run.

    `declined` is here rather than buried in the artifacts because a conclusion
    drawn over a gap nobody mentioned is the failure the whole design is
    arranged against - and a front end that cannot see the gaps cannot show them.
    """

    run_id: str
    status: RunStatus
    tasks: tuple[TaskReport, ...] = ()
    pending_gate: str = ""
    escalation: str = ""
    declined: tuple[Declined, ...] = ()
    spend: Spend | None = None
    can_replan: bool = False

    @property
    def is_complete(self) -> bool:
        """True when the run finished with nothing left owing."""
        return self.status == "completed"


@dataclass(frozen=True)
class TableReport:
    """A table, described well enough to decide what to ask of it."""

    uri: str
    rows: int
    columns: tuple[str, ...]


@dataclass(frozen=True)
class CleanReport:
    """The result of turning a file into a table a person can look at."""

    run: RunReport
    table: TableReport | None = None


@dataclass(frozen=True)
class PlannedStep:
    """One step of a plan, as a person reads it."""

    task_id: str
    agent_id: str
    after: tuple[str, ...] = ()
    reads: tuple[str, ...] = ()


@dataclass(frozen=True)
class AskReport:
    """One question asked of a clean table, and how far it got."""

    round_id: str
    question: str
    reason: str
    steps: tuple[PlannedStep, ...]
    run: RunReport
    answer: ManagerAnswer | None = None


@dataclass(frozen=True)
class GateOptionReport:
    """One thing a person may approve."""

    option_id: str
    label: str
    detail: str = ""


@dataclass(frozen=True)
class GateReport:
    """One question still owed an answer."""

    gate_id: str
    task_id: str
    agent_id: str
    title: str
    question: str
    options: tuple[GateOptionReport, ...] = ()
    # What the agent said about the data while producing this question. For the
    # cleaning gate that is the examination: what was looked at, what was
    # counted, and whether anything needs fixing at all. It used to appear once
    # in the run report at the terminal and be gone by the time anybody opened
    # the gate again - which is the moment a person actually needs it.
    examined: tuple[str, ...] = ()


@dataclass(frozen=True)
class FeatureReport:
    """One thing in the data that can be chosen or left out."""

    key: str
    kind: str
    name: str
    role: str
    detail: str
    chosen: bool


@dataclass(frozen=True)
class FeatureListing:
    """Everything choosable in a run's data, and what is currently chosen."""

    source: str
    features: tuple[FeatureReport, ...] = ()
    nothing_chosen: bool = True


@dataclass(frozen=True)
class SelectionReport:
    """What a choice changed, before anything runs."""

    chosen: tuple[str, ...]
    affected: tuple[str, ...]


def drive(
    settings: Settings,
    run_dir: Path,
    plan: Plan,
    ref: DataRef,
    *,
    run_id: str,
    question: str,
    now: datetime,
    budget: BudgetTracker | None,
    llm: LlmClient | None = None,
) -> tuple[RunOutcome | None, BudgetTracker | None, BudgetExceeded | None]:
    """Run one plan and write what it cost. The whole shared middle, in one place.

    Both front ends did these six steps themselves - run directory, budget,
    client, runner, run, ceiling - and differed only in what they did with the
    outcome. Two copies meant every change had to be made twice, and twice it
    was made once: a provider added to one copy left `resume-dag` denying that
    provider existed, and a ledger added to one copy left `resume-dag` spending
    money it never wrote down.

    Returns:
        The outcome, the budget it was spent under, and the ceiling it hit, if
        it hit one. Exactly one of the first and last is set - the caller
        decides whether that is a report or a red line of terminal output.
    """
    spend = budget
    client = llm if llm is not None else build_client(settings, run_dir, spend)
    runner = DagRunner(
        settings,
        run_dir,
        llm=client,
        budget=spend,
        planner=Planner(llm=client) if client is not None else None,
    )
    try:
        outcome = runner.run(plan, ref, run_id=run_id, question=question, now=now)
    except BudgetExceeded as exceeded:
        # Written here too, deliberately. The run that crossed the ceiling is
        # the one somebody will want the ledger for, and it leaves by the
        # exception rather than by the return.
        _keep(run_dir, spend, now)
        return None, spend, exceeded
    _keep(run_dir, spend, now)
    return outcome, spend, None


def _keep(run_dir: Path, spend: BudgetTracker | None, now: datetime) -> None:
    """Ghi so, khi co gi de ghi.

    A free provider is given no tracker at all, so there is nothing counted and
    nothing to write. An empty ledger would say the run was free, which is true
    but indistinguishable from a run whose ledger failed to be written.
    """
    if spend is not None:
        record(run_dir, spend.snapshot(), now=now)


def frame_for(
    settings: Settings, plan: Plan, state: RunState, run_id: str
) -> tuple[pd.DataFrame, str, dict[str, str]]:
    """The table a run is working on, and its event-log roles if it has any.

    One copy, because there were two and a fix landed in the wrong one. The
    command line kept its own walk of the plan and went on refusing after the
    service layer had learned to fall back - and the command line is what a
    person types.

    Raises:
        ServiceError: the run has produced nothing and was given nothing.
    """
    roles: dict[str, str] = {}
    for task in plan.tasks:
        raw = task.params.get("event_log")
        if isinstance(raw, dict):
            roles = {str(key): str(value) for key, value in raw.items() if value}
            break

    for task in reversed(plan.tasks):
        stored = state.task(task.task_id)
        if stored is None:
            continue
        for ref in stored.output_refs:
            if ref.format == "parquet":
                return storage.read_parquet(resolve(ref.path, settings)), ref.path, roles

    # Nothing produced yet, so the table to choose from is the one this run was
    # given. A question pauses at its first gate before writing anything, which
    # made "choose which data to analyse" reachable only by accident: refused on
    # the cleaning run because no task there consumes features, and refused on
    # the question run because it had written no table yet.
    #
    # The source is the clean table the question is being asked about, which is
    # exactly what somebody picking columns has in mind.
    source = state.source
    if source is not None and source.format == "parquet":
        return storage.read_parquet(resolve(source.path, settings)), source.path, roles

    raise ServiceError(
        f"Lan chay {run_id!r} chua tao ra bang nao.",
        "Chay it nhat toi buoc lam sach truoc.",
    )


def build_client(
    settings: Settings,
    run_dir: Path,
    budget: BudgetTracker | None = None,
    *,
    for_planner: bool = False,
) -> LlmClient | None:
    """Build the model client the configuration asks for.

    handoff   - writes the prompt out for a person to run on a subscription
    cassette  - replays a recorded answer, free and repeatable
    gemini    - calls Gemini; the free tier costs nothing but trains on what it
                is sent, so it belongs on the fixture and not on client data
    openrouter- one endpoint reaching many models, so each skill can run on a
                different one. Free models there trade data for the price; the
                paid ones cost about $0.004 a question and do not.
    anthropic - calls the Anthropic API, and is billed for it
    none      - no model at all; agents fall back to code-only behaviour

    Lives here, once, because it used to live here *and* in the CLI. Adding
    OpenRouter to one copy left `asys ask` running on it while `asys resume-dag`
    reported that no such provider existed - the same run, the same config, two
    answers.

    Raises:
        ServiceError: the configuration names a provider that does not exist.
    """
    choice = settings.llm.provider
    if choice == "handoff":
        return LlmClient(HandoffProvider(run_dir / "handoff"), budget=budget)
    if choice == "cassette":
        return LlmClient(CassetteProvider(cassette_path(settings)), budget=budget)
    if choice == "gemini":
        return LlmClient(
            GeminiProvider(settings.llm.gemini_model, thinking=settings.llm.gemini_thinking),
            budget=budget,
        )
    if choice == "openrouter":
        name = settings.llm.openrouter_model
        if for_planner and settings.llm.planner_model:
            name = settings.llm.planner_model
        return LlmClient(OpenRouterProvider(name), budget=budget)
    if choice == "anthropic":
        return LlmClient(AnthropicProvider(settings.llm.active_model), budget=budget)
    if choice == "none":
        return None
    raise ServiceError(
        f"provider khong ho tro: {choice}",
        "Chon mot trong: handoff, cassette, gemini, openrouter, anthropic, none",
    )


@dataclass
class Workspace:
    """Everything the system can do with one configuration.

    Holds no run state of its own: every method reads what it needs from disk,
    so two callers - a terminal and a web request - never disagree about where
    a run got to.
    """

    settings: Settings = field(default_factory=lambda: _settings())
    config_dir: Path = field(default_factory=lambda: _config_dir())

    # --- the two acts -------------------------------------------------------

    def clean(self, source: Path, run_id: str = "") -> CleanReport:
        """Turn a file into a table, and stop there.

        Raises:
            ServiceError: the file is not there, or the raw layer cannot take it.
        """
        if not source.is_file():
            raise ServiceError(f"Khong tim thay file: {source}")

        name = run_id or f"d_{datetime.now(UTC):%Y%m%d_%H%M%S}"
        ref = self._source_ref(source, name)
        plan = cleaning_plan()
        self._write_plan(name, plan)
        run = self._execute(plan, ref, name, "")
        return CleanReport(run=run, table=self.clean_table(name))

    def ask(self, run_id: str, question: str) -> AskReport:
        """Ask one question of a clean table. Ask again as often as you like.

        Raises:
            ServiceError: nothing has been cleaned yet, no model is configured,
                or no plan could be made.
        """
        table = self._clean_ref(run_id)
        if table is None:
            raise ServiceError(
                f"Lan lam viec {run_id!r} chua co du lieu sach.",
                f"Chay truoc: asys clean --input <file> --run-id {run_id}",
            )

        now = datetime.now(UTC)
        budget = self._budget(now)
        # The Manager plans on its own model. Planning is the hardest reasoning
        # in the system and it used to run on whatever was cheap enough for the
        # workers - which is how a two-step plan came back unwired three times.
        llm = self._llm(run_id, budget, for_planner=True)
        if llm is None:
            raise ServiceError(
                "Chua cau hinh model.",
                "Manager can mot model de lap ke hoach tu cau hoi. Xem llm.provider.",
            )

        round_id = self._next_round(run_id)
        try:
            plan = Planner(llm=llm).plan(
                question, table.path, self._planning_profile(run_id, table.path)
            )
            # The Manager answers, always. Whether a question gets an answer is
            # not a planning decision.
            plan = with_synthesis(plan, question, self.config_dir / "manifests")
        except PlanError as error:
            raise ServiceError(f"Khong lap duoc ke hoach: {error}") from error

        # Bang nao se di vao tang thong ke thi phai giu nguyen tung dong.
        # Chi ke hoach biet duoc dieu do - a4 nhin mot minh khong thay bang
        # cua no chay di dau.
        plan = keeping_rows(plan)
        # Chu giai luu rieng. Model chi duoc dua nhung dong cua cot ma cau hoi
        # nhac toi; code doi chieu thi doc ca bang, qua tham so rieng.
        glossary = self.glossary(run_id)
        plan = with_context(plan, for_prompt(self.context(run_id), glossary, question))
        plan = with_glossary(plan, glossary)
        # Buoc phan tich chi nhan loi dan cua Manager, va loi dan co the da doi
        # cot. Cau hoi goc di kem de phan chon cot doc dung cau nguoi dung hoi.
        plan = with_asked(plan, question)
        self._write_plan(round_id, plan)
        run = self._execute(plan, table, round_id, question, budget=budget, llm=llm, now=now)
        run = self._answer_through(round_id, run)
        return AskReport(
            round_id=round_id,
            question=question,
            reason=plan.reason,
            steps=tuple(
                PlannedStep(
                    task_id=task.task_id,
                    agent_id=task.agent_id,
                    after=task.depends_on,
                    reads=task.reads_from,
                )
                for task in plan.tasks
            ),
            run=run,
            answer=self.answer(round_id),
        )

    # Ly do ghi vao chinh quyet dinh, de nhat ky noi ro ai duyet va vi sao.
    AUTO_NOTE: ClassVar[str] = (
        "Tu dong duyet: day la mot cau hoi, khong phai mot bao cao. Manager la "
        "nguoi duyet ket luan cua cac skill; nguoi hoi nhan cau tra loi."
    )

    # Gate lam sach thi KHONG bao gio tu duyet. No dong vao du lieu cua nguoi
    # dung, va viec hoi truoc khi sua la thu duoc yeu cau tu dau.
    NEVER_AUTO: ClassVar[frozenset[str]] = frozenset({"a3_cleaner"})

    def _answer_through(self, run_id: str, run: RunReport, limit: int = 4) -> RunReport:
        """Carry a question past the gates that only ask which parts may be said.

        A person who asks a question wants an answer. Being handed five claims,
        each already carrying its own metric citation, and asked to tick which
        ones may be printed is being asked to do the Manager's job - without
        being told what ticking changes:

            "toi chon duyet 1 va 2 thi co muc dich gi toi khong hieu, ma duyet
             tat ca thi cung khong biet de lam gi"

        A gate nobody understands is not a gate. It is a button to press before
        being allowed to see the answer.

        Only the asking flow. `asys run-dag`, which ends in a written report,
        keeps every gate it has: choosing what a published report says is a real
        editorial decision, and the manifests still declare it.

        Nothing is loosened by this. Every number still has to be a real metric,
        `render_all` still throws out invented ones, and what could not be
        established is still printed. None of that lives in this gate.
        """
        for _ in range(limit):
            if run.status != "paused" or not self._approve_for_the_asker(run_id):
                return run
            run = self.resume(run_id)
        return run

    def _approve_for_the_asker(self, run_id: str) -> bool:
        """Record the automatic decision. True when there was one to record."""
        run_dir = self._run_dir(run_id)
        store = GateStore(run_dir)
        states = StateStore(run_dir / STATE_FILENAME)
        try:
            state = states.load()
            pending = [
                request
                for request in store.pending(state)
                if request.agent_id not in self.NEVER_AUTO
            ]
            if not pending:
                return False
            now = datetime.now(UTC)
            for request in pending:
                state = state.with_gate(
                    decide(
                        request,
                        approved=request.option_ids,
                        note=self.AUTO_NOTE,
                        now=now,
                    ),
                    now=now,
                )
            states.save(state)
        except (GateError, StateError):
            # Khong duyet duoc thi de nguyen cho nguoi that duyet, chu khong
            # lam hong ca lan chay.
            return False
        return True

    # Khong co tin hieu nao lau hon nguong nay thi coi nhu da chet, khong con
    # la "dang chay". Mot lan chay bi giet giua chung de lai phase RUNNING mai
    # mai, va mot cai vong xoay quay hoai la mot loi noi doi.
    STALE_AFTER_MINUTES: ClassVar[int] = 15

    def running(self, run_id: str, now: datetime | None = None) -> bool:
        """True khi lần chạy này thật sự đang chạy dở.

        Không chỉ đọc `phase`: một lần chạy bị ngắt giữa chừng để lại phase
        RUNNING vĩnh viễn. Nên còn phải có tín hiệu gần đây.
        """
        try:
            state = self._state(run_id, quiet=True)
        except (ServiceError, StateError):
            return False
        if state is None or str(state.phase) != "RUNNING":
            return False
        moment = now or datetime.now(UTC)
        idle = float((moment - state.updated_at).total_seconds()) / 60
        return bool(idle < self.STALE_AFTER_MINUTES)

    def context(self, run_id: str) -> str:
        """Bối cảnh người dùng đã ghi cho bộ dữ liệu này."""
        return read_context(self._run_dir(self._dataset_of(run_id)))

    def set_context(self, run_id: str, text: str) -> str:
        """Ghi bối cảnh cho bộ dữ liệu, trả về đúng phần đã lưu.

        Raises:
            ServiceError: dài quá giới hạn. Trước đây phần thừa bị cắt ngầm mà
                trang vẫn báo đã lưu, và nửa sau của một bảng chú giải 96 cột
                mất như thế.
        """
        tidy = "\n".join(" ".join(line.split()) for line in str(text).splitlines() if line.strip())
        if len(tidy) > CONTEXT_LIMIT:
            raise ServiceError(
                f"Bối cảnh dài {len(tidy)} ký tự, tối đa {CONTEXT_LIMIT}.",
                "Chú giải cột nay lưu riêng trong bảng Chú giải cột ở trang dữ liệu "
                "sạch, không cần viết vào ô này.",
            )
        return write_context(self._run_dir(self._dataset_of(run_id)), text)

    def data_scope(self, run_id: str) -> list[dict[str, object]]:
        """Những bước lọc của lượt hỏi: còn bao nhiêu dòng, theo điều kiện nào.

        Đọc từ câu SQL mà bước biến đổi đã lưu cạnh bảng, không từ lời model: đây
        là chỗ người đọc biết chắc mọi con số thuộc tập nào, dù câu chữ nói gì.
        """
        state = self._state(run_id, quiet=True)
        if state is None:
            return []
        found: list[dict[str, object]] = []
        for task in state.tasks.values():
            if task.phase != "OK":
                continue
            for ref in task.output_refs:
                if ref.format != "parquet" or not ref.path.startswith("mart://"):
                    continue
                try:
                    text = storage.read_text(resolve(recipe_of(ref.path), self.settings))
                except (ConfigError, OSError, ValueError, storage.StorageError):
                    continue
                scope = parse_recipe(text)
                if scope is None:
                    continue
                total = scope.total or int(task.metrics.get("rows_in_total", 0)) or None
                found.append(
                    {
                        "rows": scope.rows,
                        "total": total,
                        "condition": shown_condition(scope.condition),
                        "notes": list(scope.notes),
                    }
                )
        return found

    def _glossary_columns(self, dataset: str) -> list[str]:
        table = self._glossary_table_ref(dataset)
        return [] if table is None else [str(name) for name in table.columns]

    def glossary_rows(self, run_id: str) -> list[tuple[str, str]]:
        """Mỗi cột một dòng, theo thứ tự của bảng: nghĩa đã lưu, hoặc rỗng."""
        dataset = self._dataset_of(run_id)
        return rows_for(
            self._glossary_columns(dataset),
            read_glossary(self._run_dir(dataset)),
            self.context(dataset),
        )

    def glossary(self, run_id: str) -> str:
        """Bảng chú giải có hiệu lực, dạng `cột = nghĩa`, cho code đối chiếu."""
        return as_text(self.glossary_rows(run_id))

    def categories(self, run_id: str) -> dict[str, list[str]]:
        """Cột phân loại của bảng và các giá trị của nó, viết đúng như trong khóa chỉ số."""
        table = self._glossary_table_ref(self._dataset_of(run_id))
        return {} if table is None else categories_of(self.table(table.uri))

    def _glossary_table_ref(self, dataset: str) -> TableReport | None:
        return self.clean_table(dataset) or self.staged_table(dataset)

    def value_labels(self, run_id: str) -> dict[str, dict[str, str]]:
        """Nhãn tiếng Việt cho giá trị, theo cột: khai tay thắng, còn lại tự suy."""
        dataset = self._dataset_of(run_id)
        return effective_labels(
            self.categories(dataset),
            read_labels(self._run_dir(dataset)),
            dict(self.glossary_rows(dataset)),
        )

    def glossary_table(self, run_id: str) -> list[dict[str, object]]:
        """Mỗi cột một dòng cho bảng chú giải; cột phân loại có thêm nhãn giá trị.

        Chỉ cột phân loại mang ba khóa `categories`, `values`, `suggested`: một
        ô nhãn giá trị trên một cột số liên tục là ô không ai điền được.
        """
        dataset = self._dataset_of(run_id)
        found = self.categories(dataset)
        saved = read_labels(self._run_dir(dataset))
        table: list[dict[str, object]] = []
        for column, meaning in self.glossary_rows(dataset):
            row: dict[str, object] = {"column": column, "meaning": meaning}
            values = found.get(column)
            if values:
                row["categories"] = values
                row["values"] = labels_text(saved.get(column, {}))
                row["suggested"] = labels_text(suggested(values, meaning))
            table.append(row)
        return table

    def _checked_labels(self, dataset: str, values: dict[str, str]) -> dict[str, dict[str, str]]:
        """Nhãn giá trị người dùng gõ, sau khi đối chiếu với giá trị có thật.

        Raises:
            ServiceError: cột không phải cột phân loại, hoặc giá trị không có.
        """
        found = self.categories(dataset)
        tidy = {" ".join(name.split()): name for name in found}
        labels: dict[str, dict[str, str]] = {}
        for column, text in values.items():
            parsed = parse_labels(text)
            if not parsed:
                continue
            real = tidy.get(" ".join(column.split()))
            if real is None:
                raise ServiceError(
                    f"Cột '{column}' không phải cột phân loại, không đặt nhãn giá trị được."
                )
            strange = [value for value in parsed if value not in found[real]]
            if strange:
                raise ServiceError(
                    f"Cột '{real}' không có giá trị {', '.join(strange)} "
                    f"(chỉ có: {', '.join(found[real])})."
                )
            labels[real] = parsed
        return labels

    def set_glossary(
        self,
        run_id: str,
        rows: list[tuple[str, str]],
        values: dict[str, str] | None = None,
    ) -> tuple[str, int]:
        """THAY cả bảng chú giải, rồi chuyển các dòng chú giải cũ khỏi ô Bối cảnh.

        Chuyển được vì bảng người dùng vừa lưu đã hiện sẵn các dòng cũ đó (xem
        `rows_for`): họ đã thấy, đã giữ hoặc đã sửa chúng.

        Returns:
            (phần đã lưu, số dòng đã chuyển khỏi ô Bối cảnh).

        Raises:
            ServiceError: chưa có bảng, có cột không có thật, hoặc quá dài.
        """
        dataset = self._dataset_of(run_id)
        columns = self._glossary_columns(dataset)
        if not columns:
            raise ServiceError("Chưa có bảng nào để đối chiếu tên cột. Làm sạch dữ liệu trước.")
        real = {" ".join(name.split()) for name in columns}
        unknown = [
            column
            for column, meaning in rows
            if str(meaning).strip() and " ".join(str(column).split()) not in real
        ]
        if unknown:
            raise ServiceError(f"Không có cột: {', '.join(unknown[:5])}.")
        # Doi chieu nhan gia tri TRUOC khi ghi gi: mot nhan sai khong duoc de
        # lai mot bang chu giai luu nua chung.
        labels = None if values is None else self._checked_labels(dataset, values)
        try:
            saved = write_glossary(self._run_dir(dataset), rows)
        except GlossaryTooLongError as error:
            raise ServiceError(str(error)) from error
        if labels is not None:
            write_labels(self._run_dir(dataset), labels)
        prose, moved = without_glossary_lines(self.context(dataset), columns)
        if moved:
            write_context(self._run_dir(dataset), prose)
        return saved, moved

    @staticmethod
    def _dataset_of(run_id: str) -> str:
        """Bộ dữ liệu gốc của một lượt hỏi.

        Bối cảnh thuộc về BỘ DỮ LIỆU, không thuộc về từng lượt hỏi: người dùng
        gõ một lần rồi mọi câu hỏi trên bộ đó đều mang nó theo.
        """
        dataset, _, _ = run_id.partition("__q")
        return dataset

    def why_stopped(self, run_id: str) -> str:
        """Vì sao lần chạy này chưa có kết quả, nói bằng tiếng người.

        Trước đây dashboard chỉ in "Chưa có câu trả lời." cho mọi trường hợp:
        đang chạy, chạm trần ngân sách, một skill hỏng. Chủ hệ thống hỏi cùng
        một câu hai lần, một lần được trả lời một lần không, và không dòng nào
        nói vì sao - nên nó trông như hệ thống lặp lại câu hỏi.

        Returns:
            Một câu cho người đọc, hoặc chuỗi rỗng khi không có gì bất thường
            để nói (lần chạy còn đang chạy dở, hoặc đọc không được trạng thái).
        """
        try:
            state = self._state(run_id, quiet=True)
        except (ServiceError, StateError):
            return ""
        if state is None:
            return ""

        failed = [
            (task_id, task)
            for task_id, task in state.tasks.items()
            if task.phase in {"FAILED", "HALTED_BUDGET", "BOUNDARY_VIOLATION"}
        ]
        if failed:
            task_id, task = failed[0]
            detail = _message_of(task.error)
            where = f"Bước {task_id} ({task.agent_id}) không chạy được."
            return f"{where} {in_plain_words(_first_sentence(detail))}".strip()
        if str(state.phase) == "HALTED":
            return "Lần chạy đã dừng giữa chừng."
        if str(state.phase) == "RUNNING":
            if self.running(run_id):
                return "Đang chạy, chưa xong."
            return "Lần chạy dừng giữa chừng và không có tín hiệu nào nữa. Hãy hỏi lại câu này."
        return ""

    def resume(self, run_id: str) -> RunReport:
        """Carry on a run that stopped, without redoing what is done.

        Raises:
            ServiceError: there is no such run, or its state cannot be read.
        """
        try:
            stored = self._state(run_id)
            plan = Plan.model_validate_json(self._plan_path(run_id).read_text(encoding="utf-8"))
        except (StateError, OSError, ValueError) as error:
            raise ServiceError(
                f"Chua co ke hoach hoac state cho {run_id!r}.",
                "Lan dau phai dung: asys clean --input <file>",
            ) from error
        if stored.source is None:
            raise ServiceError("State khong ghi nguon du lieu.", "Hay bat dau lai.")
        return self._execute(plan, stored.source, run_id, "")

    # --- gates ---------------------------------------------------------------

    def gates(self, run_id: str) -> list[GateReport]:
        """Every question still owed an answer.

        Not merely the undecided ones: a decision made about an earlier result
        does not answer the question a re-run is now asking.
        """
        state = self._state(run_id)
        return [
            GateReport(
                gate_id=request.gate_id,
                task_id=request.task_id,
                agent_id=request.agent_id,
                title=request.title,
                question=request.question,
                options=tuple(
                    GateOptionReport(
                        option_id=option.option_id, label=option.label, detail=option.detail
                    )
                    for option in request.options
                ),
                examined=tuple(
                    in_plain_words(str(line)) for line in (request.payload.get("da_xem") or [])
                ),
            )
            for request in GateStore(self._run_dir(run_id)).pending(state)
        ]

    def examination(self, run_id: str) -> tuple[str, ...]:
        """What the cleaning stage found when it looked at the data.

        Read from every gate written for the run, not only the pending ones:
        the verdict is just as worth showing after it has been approved - that
        is the moment somebody asks what was actually done to their data.
        Deduplicated in the order first written, because a re-run repeats an
        unchanged verdict word for word and reading it twice tells nobody
        anything.
        """
        seen: list[str] = []
        for request in GateStore(self._run_dir(run_id)).all_gates():
            for line in request.payload.get("da_xem") or []:
                text = str(line)
                if text not in seen:
                    seen.append(text)
        # "Can sua: cast_numeric_safe tren ..." - chu he thong doc dung dong do
        # va hoi he thong dang sua cai gi. Doi ma luat sang ten tieng Viet, giu
        # ma trong ngoac vuong cho nguoi van hanh doi chieu voi nhat ky. Lam O
        # DAY thi ca trang Python lan ban Next cung duoc.
        return tuple(in_plain_words(text) for text in seen)

    def approve(
        self,
        run_id: str,
        gate_id: str,
        approved: tuple[str, ...],
        rejected: tuple[str, ...] = (),
        note: str = "",
        added: tuple[dict[str, Any], ...] = (),
    ) -> None:
        """Record one decision, as data that replays on the next run.

        Raises:
            ServiceError: the gate does not exist, or something was approved
                that it never offered.
        """
        run_dir = self._run_dir(run_id)
        states = StateStore(run_dir / STATE_FILENAME)
        try:
            state = states.load()
            request = GateStore(run_dir).read(gate_id)
            decision = decide(
                request,
                approved=approved,
                rejected=rejected,
                added=added,
                note=note,
                now=datetime.now(UTC),
            )
        except (GateError, StateError) as error:
            raise ServiceError(str(error)) from error
        states.save(state.with_gate(decision, now=datetime.now(UTC)))

    # --- what can be chosen --------------------------------------------------

    def features(self, run_id: str, kind: str = "") -> FeatureListing:
        """Everything in this run's data that can be chosen or left out.

        Raises:
            ServiceError: the run has produced no table to choose from.
        """
        frame, source, roles = self._frame_for(run_id)
        catalogue = catalogue_for(
            frame, source, activity=roles.get("activity", ""), resource=roles.get("resource", "")
        )
        if kind:
            catalogue = FeatureCatalogue(source=catalogue.source, features=catalogue.of_kind(kind))
        chosen = self.selection(run_id)
        return FeatureListing(
            source=catalogue.source,
            nothing_chosen=chosen.is_empty,
            features=tuple(
                FeatureReport(
                    key=feature.key,
                    kind=feature.kind,
                    name=feature.name,
                    role=feature.role,
                    detail=feature.detail,
                    chosen=chosen.is_empty or feature.key in set(chosen.keys),
                )
                for feature in catalogue.features
            ),
        )

    def choose(self, run_id: str, keys: tuple[str, ...]) -> SelectionReport:
        """Narrow the analysis to certain features, and say what that changes.

        Nothing runs. The plan is rewritten and the tasks that will have to be
        redone are named, so a person can see the consequence before accepting it.

        Raises:
            ServiceError: a key names something the data does not have, or the
                choice would change nothing.
        """
        plan = self._base_plan(run_id)
        frame, source, roles = self._frame_for(run_id)
        catalogue = catalogue_for(
            frame, source, activity=roles.get("activity", ""), resource=roles.get("resource", "")
        )
        try:
            selection = Selection.from_params(list(keys))
            changed = apply_selection(plan, selection, catalogue, self.config_dir / "manifests")
            touched = affected_tasks(plan, selection, catalogue, self.config_dir / "manifests")
        except FeatureError as error:
            raise ServiceError(str(error)) from error

        base = self._run_dir(run_id) / BASE_PLAN_FILENAME
        if not base.is_file():
            base.parent.mkdir(parents=True, exist_ok=True)
            base.write_text(self._plan_path(run_id).read_text(encoding="utf-8"), encoding="utf-8")
        self._write_plan(run_id, changed)
        self._write_selection(run_id, selection)
        return SelectionReport(chosen=selection.keys, affected=touched)

    def clear_choice(self, run_id: str) -> None:
        """Go back to analysing everything, plan included."""
        base = self._run_dir(run_id) / BASE_PLAN_FILENAME
        if base.is_file():
            self._plan_path(run_id).write_text(base.read_text(encoding="utf-8"), encoding="utf-8")
        self._write_selection(run_id, Selection())

    def selection(self, run_id: str) -> Selection:
        """What was chosen last time, or nothing when nobody has chosen."""
        path = self._run_dir(run_id) / SELECTION_FILENAME
        if not path.is_file():
            return Selection()
        try:
            return Selection.from_params(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, FeatureError):
            return Selection()

    # --- what a run produced --------------------------------------------------

    def staged_table(self, run_id: str) -> TableReport | None:
        """Bảng vừa đọc từ tệp gốc, mô tả lại - trước khi làm sạch bất cứ gì."""
        try:
            state = self._state(run_id, quiet=True)
        except (ServiceError, StateError):
            return None
        if state is None:
            return None
        task = state.tasks.get("t1_ingest")
        if task is None or not task.output_refs:
            return None
        try:
            frame = storage.read_parquet(resolve(task.output_refs[0].path, self.settings))
        except (OSError, ValueError):
            return None
        return TableReport(
            uri=task.output_refs[0].path,
            rows=len(frame.index),
            columns=tuple(str(column) for column in frame.columns),
        )

    def clean_table(self, run_id: str) -> TableReport | None:
        """The clean table a run produced, described, or None."""
        ref = self._clean_ref(run_id)
        if ref is None or self._analysed(run_id):
            return None
        frame = storage.read_parquet(resolve(ref.path, self.settings))
        return TableReport(
            uri=ref.path,
            rows=len(frame.index),
            columns=tuple(str(column) for column in frame.columns),
        )

    def answer(self, run_id: str) -> ManagerAnswer | None:
        """The Manager's answer for this round, if it got that far."""
        found = self._artifact(run_id, "_answer.json", ManagerAnswer)
        return found if isinstance(found, ManagerAnswer) else None

    def forget_rounds(self, dataset: str, round_ids: Sequence[str]) -> int:
        """Xoá hẳn các lượt hỏi này, và mọi tệp mang tên chúng.

        Args:
            dataset: bộ dữ liệu đang mở.
            round_ids: các lượt hỏi cần xoá.

        Returns:
            Số lượt thật sự đã xoá.

        Raises:
            ServiceError: một mã không thuộc bộ dữ liệu này, hoặc xoá không được.

        Lớp chặn "phải thuộc bộ đang mở" nằm ở đây chứ không phải ở route: một
        mã đến từ trình duyệt không được phép xoá thứ của bộ khác chỉ vì nó
        đoán đúng cái tên. Và **chỉ xoá lượt hỏi** — mã của chính bộ dữ liệu bị
        từ chối, vì `belongings` khớp theo tiền tố nên xoá bộ sẽ cuốn theo mọi
        lượt hỏi của nó, và đó là một việc khác hẳn với việc người dùng đang làm.
        """
        wanted = [str(item) for item in round_ids if str(item).strip()]
        if not wanted:
            return 0
        mark = f"{dataset}{ROUND_MARK}"
        for round_id in wanted:
            if not round_id.startswith(mark):
                raise ServiceError(f"{round_id!r} khong thuoc bo du lieu {dataset!r}.")
        try:
            retention.forget(self.settings, wanted)
        except OSError as error:
            raise ServiceError(f"Khong xoa duoc: {error}") from error
        return len(wanted)

    def dataset_busy(self, dataset: str) -> list[str]:
        """Những lần chạy của bộ này (chính nó hay lượt hỏi) đang chạy dở."""
        try:
            owned = dataset_removal.runs_of(self.settings, dataset)
        except ValueError:
            return []
        return [run_id for run_id in owned if self.running(run_id)]

    def forget_dataset(self, dataset: str) -> int:
        """Xoá hẳn một bộ dữ liệu: tệp gốc, bảng sạch, mọi lượt hỏi và tệp mang tên nó.

        Returns:
            Số tệp và thư mục đã xoá.

        Raises:
            ServiceError: mã là một lượt hỏi chứ không phải một bộ, hoặc xoá không được.
        """
        if not dataset.strip() or ROUND_MARK in dataset:
            raise ServiceError(f"{dataset!r} khong phai ma cua mot bo du lieu.")
        try:
            removed, _freed = dataset_removal.forget(self.settings, dataset)
        except (OSError, ValueError) as error:
            raise ServiceError(f"Khong xoa duoc: {error}") from error
        return removed

    def draft_glossary(self, run_id: str) -> tuple[str, list[str]]:
        """Soạn bản nháp bảng chú giải cho bộ dữ liệu này.

        Model đề xuất nghĩa tiếng Việt của từng tên cột; code đối chiếu mọi
        khoá với cột có thật; người dùng đọc và sửa trước khi lưu.

        Returns:
            (các dòng chú giải, những gì bị bỏ kèm lý do).

        Raises:
            ServiceError: chưa có bảng sạch, chưa có model, hoặc model hỏng.
        """
        table = self.clean_table(run_id) or self.staged_table(run_id)
        if table is None:
            raise ServiceError("Chua co bang nao de doc ten cot. Lam sach du lieu truoc.")
        columns = [str(name) for name in self.table(table.uri, limit=1).columns]

        client = build_client(self.settings, self._run_dir(run_id))
        if client is None:
            raise ServiceError("Chua cau hinh model nao, nen khong soan nhap duoc.")
        try:
            # Loi goi le, khong co vong thu lai: model mac dinh bi gioi han luot
            # goi (HTTP 429) tung la het cach (bo MBB, 2026-09-15).
            answer = client.complete_with_fallback(
                build_glossary_request(columns), self.settings.llm.openrouter_fallback
            )
        except AllModelsFailedError as error:
            raise ServiceError(f"Không soạn được bản nháp chú giải. {error}") from error
        except LlmError as error:
            raise ServiceError(f"Model khong soan duoc: {_first_sentence(str(error))}") from error
        if not isinstance(answer.data, GlossaryProposal):
            raise ServiceError("Model tra ve sai dinh dang.")

        found, dropped = verified_glossary(answer.data, columns)
        if not found:
            raise ServiceError("Khong dong nao dung duoc - moi dong deu tro toi cot khong co that.")
        return glossary_lines(found), dropped

    def measured(self, run_id: str) -> dict[str, float]:
        """Cac con so A7 do duoc trong luot nay, theo metric key.

        De ve bieu do ngay tren trang. Gia tri den tu chinh artifact da do,
        khong di qua tay model - nen bieu do khong phai them mot cho nua de mot
        con so sai lot qua.
        """
        found = self._artifact(run_id, "_findings.json", AnalysisResult)
        if not isinstance(found, AnalysisResult):
            return {}
        return {metric.key: float(metric.value) for metric in found.metrics}

    def process_map(self, run_id: str) -> ProcessMap | None:
        """The process map a run produced, if it produced one."""
        found = self._artifact(run_id, "_process_map.json", ProcessMap)
        return found if isinstance(found, ProcessMap) else None

    def profile(self, run_id: str) -> ProfileReport | None:
        """What A2 found, so a plan is not made blind."""
        state = self._state(run_id, quiet=True)
        if state is None:
            return None
        for task in state.tasks.values():
            if task.agent_id != "a2_profiler" or not task.is_done:
                continue
            for ref in task.output_refs:
                try:
                    return ProfileReport.model_validate_json(
                        resolve(ref.path, self.settings).read_text(encoding="utf-8")
                    )
                except (OSError, ValueError):
                    return None
        return None

    def _planning_profile(self, run_id: str, uri: str) -> ProfileReport | None:
        """Mô tả của đúng bảng mà kế hoạch được lập trên đó: bảng sạch, không phải tệp gốc.

        Bảng sạch đổi hình (xoay bảng) thì profile của A2 mô tả những cột không
        còn nữa, và kế hoạch ra lệnh trên chúng (bộ MBB, 2026-09-15).
        """
        stored = self.profile(run_id)
        if stored is None:
            # Khong co gi de lech: planner van duoc bao "chua co mo ta" nhu truoc.
            return None
        try:
            frame = self.table(uri)
        except ServiceError:
            return stored
        return refreshed_profile(stored, frame)

    def bpmn(self, run_id: str) -> str:
        """The measured process as BPMN 2.0, ready to import.

        Raises:
            ServiceError: this run mined no process, or there was none to draw.
        """
        found = self.process_map(run_id)
        if found is None:
            raise ServiceError(
                f"Lan chay {run_id!r} chua co ban do quy trinh.",
                "Can mot lan chay co agent khai thac quy trinh (a6_process_miner).",
            )
        try:
            return to_bpmn(found)
        except BpmnError as error:
            raise ServiceError(str(error)) from error

    def table(self, uri: str, limit: int = 0, offset: int = 0) -> pd.DataFrame:
        """One stored table, for looking at or exporting.

        Args:
            uri: the stored table.
            limit: how many rows at most; 0 means all of them.
            offset: rows to skip first, so a browser can page through a table
                it could never hold at once.

        Raises:
            ServiceError: the reference cannot be read.
        """
        try:
            path = resolve(uri, self.settings)
            frame = storage.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)
        except (ConfigError, OSError, ValueError, storage.StorageError) as error:
            raise ServiceError(f"Khong doc duoc {uri}: {error}") from error
        if offset:
            frame = frame.iloc[offset:]
        return frame.head(limit) if limit else frame

    # --- the parts nobody outside needs to know about ---------------------------

    def _run_dir(self, run_id: str) -> Path:
        return self.settings.layers.runs / run_id

    def _plan_path(self, run_id: str) -> Path:
        return self._run_dir(run_id) / PLAN_FILENAME

    def _write_plan(self, run_id: str, plan: Plan) -> None:
        path = self._plan_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")

    def _base_plan(self, run_id: str) -> Plan:
        """The plan as it was before anybody narrowed it.

        A later choice replaces an earlier one rather than adding to it, so it is
        always applied to the untouched plan.
        """
        base = self._run_dir(run_id) / BASE_PLAN_FILENAME
        path = base if base.is_file() else self._plan_path(run_id)
        try:
            return Plan.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ServiceError(
                f"Chua co ke hoach cho {run_id!r}.", "Chay clean hoac run-dag truoc."
            ) from error

    def _write_selection(self, run_id: str, selection: Selection) -> None:
        path = self._run_dir(run_id) / SELECTION_FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(list(selection.keys), indent=2), encoding="utf-8")

    def _state(self, run_id: str, *, quiet: bool = False) -> Any:
        try:
            return StateStore(self._run_dir(run_id) / STATE_FILENAME).load()
        except StateError as error:
            if quiet:
                return None
            raise ServiceError(str(error)) from error

    def _artifact(self, run_id: str, suffix: str, model: Any) -> Any:
        state = self._state(run_id, quiet=True)
        if state is None:
            return None
        for task in state.tasks.values():
            for ref in task.output_refs:
                if ref.format != "json" or not ref.path.endswith(suffix):
                    continue
                try:
                    return model.model_validate_json(
                        resolve(ref.path, self.settings).read_text(encoding="utf-8")
                    )
                except (OSError, ValueError):
                    return None
        return None

    def _clean_ref(self, run_id: str) -> DataRef | None:
        state = self._state(run_id, quiet=True)
        if state is None:
            return None
        for task in state.tasks.values():
            if task.agent_id == "a3_cleaner" and task.is_done and task.output_refs:
                found = task.output_refs[0]
                return found if isinstance(found, DataRef) else None
        return None

    def _analysed(self, run_id: str) -> bool:
        """True when this run went past cleaning into analysis."""
        state = self._state(run_id, quiet=True)
        if state is None:
            return False
        return any(task.agent_id in ANALYSIS_AGENTS for task in state.tasks.values())

    def _next_round(self, run_id: str) -> str:
        """A fresh id for this question.

        Each question is its own run. Two questions about one table are two
        pieces of work, and sharing state would mean the second quietly
        inheriting the first's decisions.
        """
        runs = self.settings.layers.runs
        used = {path.name for path in runs.glob(f"{run_id}__q*")} if runs.is_dir() else set()
        index = 1
        while f"{run_id}__q{index}" in used:
            index += 1
        return f"{run_id}__q{index}"

    def _frame_for(self, run_id: str) -> tuple[pd.DataFrame, str, dict[str, str]]:
        """The table a run is working on, and its event-log roles if it has any."""
        return frame_for(self.settings, self._base_plan(run_id), self._state(run_id), run_id)

    def _source_ref(self, source: Path, run_id: str) -> DataRef:
        """Point a run at its input, copying it in only when it is not already there.

        The raw layer holds the one thing that cannot be regenerated, so nothing
        writes to it if it can avoid doing so - and under Docker it cannot.
        """
        raw_root = self.settings.layers.raw.resolve()
        resolved = source.resolve()
        if raw_root == resolved.parent or raw_root in resolved.parents:
            relative = resolved.relative_to(raw_root).as_posix()
            return DataRef(
                path=f"raw://{relative}",
                format=_format_of(source),
                content_hash=storage.sha256_file(resolved),
            )

        target_uri = f"raw://{run_id}_{source.name}"
        target = resolve(target_uri, self.settings)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        except OSError as error:
            raise ServiceError(
                f"Khong chep duoc file nguon vao tang raw: {error}",
                f"Tang raw ({raw_root}) chi doc. Hay dat file vao do truoc.",
            ) from error
        return DataRef(
            path=target_uri,
            format=_format_of(source),
            content_hash=storage.sha256_file(target),
        )

    def _budget(self, now: datetime) -> BudgetTracker | None:
        """The ceiling this run must not cross, for providers that reach an endpoint."""
        if self.settings.llm.provider in ("none", "cassette", "handoff"):
            return None
        try:
            config = load_budget(self.config_dir / BUDGET_FILE)
            prices = load_pricing(self.config_dir / PRICING_FILE)
        except BudgetError as error:
            raise ServiceError(f"Khong doc duoc ngan sach: {error}") from error
        return BudgetTracker(config, prices, started_at=now)

    def _llm(
        self, run_id: str, budget: BudgetTracker | None, *, for_planner: bool = False
    ) -> LlmClient | None:
        """The model client for this run, or None when the run uses no model."""
        return build_client(self.settings, self._run_dir(run_id), budget, for_planner=for_planner)

    def _execute(
        self,
        plan: Plan,
        ref: DataRef,
        run_id: str,
        question: str,
        *,
        budget: BudgetTracker | None = None,
        llm: LlmClient | None = None,
        now: datetime | None = None,
    ) -> RunReport:
        """Run a plan and describe what happened, without deciding what to do about it."""
        moment = now or datetime.now(UTC)
        outcome, spend, exceeded = drive(
            self.settings,
            self._run_dir(run_id),
            plan,
            ref,
            run_id=run_id,
            question=question,
            now=moment,
            budget=budget if budget is not None else self._budget(moment),
            llm=llm,
        )
        if exceeded is not None or outcome is None:
            return RunReport(
                run_id=run_id,
                status="halted",
                escalation=str(exceeded or "khong ro ly do"),
                spend=_spend_of(spend),
            )
        return _report(outcome, run_id, _spend_of(spend))


def _message_of(error: object) -> str:
    """Câu người đọc cần, lấy ra khỏi `ErrorDetail`.

    Trước đây chỉ đọc được khi lỗi là `dict`; khi nó là chính đối tượng
    `ErrorDetail` thì `str()` cho ra bản in máy — `code='RULE_REJECTED'
    message="..."` — và cả cụm đó đi thẳng lên màn hình người dùng.
    """
    if error is None:
        return ""
    if isinstance(error, dict):
        return str(error.get("message") or "")
    found = getattr(error, "message", None)
    return str(found) if found else str(error)


def _first_sentence(detail: str, limit: int = 160) -> str:
    """Câu đầu của một lỗi, đủ để biết chuyện gì, không kèm cả phản hồi thô.

    Một lỗi từ model mang theo nguyên văn phản hồi của nó - hàng nghìn ký tự
    JSON và dòng suy nghĩ - và khi in thẳng ra dashboard thì nó chiếm trọn màn
    hình, đẩy mọi thứ khác xuống dưới. Bản đầy đủ vẫn nằm trong `state.json`,
    nơi người đi tìm lỗi cần nó.
    """
    text = " ".join(str(detail).split())
    for mark in (". ", ".\n", "Phan hoi day du", "Phản hồi đầy đủ"):
        head, sep, _ = text.partition(mark)
        if sep:
            text = head + ("." if mark.startswith(".") else "")
            break
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _report(outcome: RunOutcome, run_id: str, spend: Spend | None) -> RunReport:
    """One run outcome, in the shape any front end can render."""
    status: RunStatus = "completed"
    if outcome.is_paused:
        status = "paused"
    elif outcome.halted or outcome.escalation:
        status = "halted"
    return RunReport(
        run_id=run_id,
        status=status,
        tasks=tuple(
            TaskReport(
                task_id=result.task_id,
                agent_id=result.agent_id,
                status=result.status,
                message=result.error.message if result.error else "",
            )
            for result in outcome.results
        ),
        pending_gate=str(outcome.paused_gate or ""),
        escalation=outcome.escalation or outcome.halted or "",
        declined=tuple(
            Declined(agent_id=result.agent_id, note=note)
            for result in outcome.results
            for note in result.declined
        ),
        spend=spend,
        can_replan=outcome.can_replan,
    )


def _spend_of(budget: BudgetTracker | None) -> Spend | None:
    """What a run cost, when anything was counted."""
    if budget is None:
        return None
    return Spend(
        tokens=budget.tokens_total,
        cost_usd=budget.cost_usd,
        warnings=tuple(budget.warnings),
    )


def _format_of(path: Path) -> DataFormat:
    """The stored format of a source file, from its extension."""
    suffix = path.suffix.lower()
    if suffix in {".parquet", ".pq"}:
        return "parquet"
    if suffix in {".json", ".jsonl", ".ndjson"}:
        return "json"
    return "csv"


def _settings() -> Settings:
    """The configuration in use.

    Raises:
        ServiceError: it cannot be read, or a layer is missing.
    """
    override = os.environ.get(CONFIG_ENV_VAR)
    try:
        settings = load_settings(Path(override) if override else None)
        verify_layers(settings)
    except ConfigError as error:
        raise ServiceError(f"Loi cau hinh:\n{error}") from error
    return settings


def _config_dir() -> Path:
    """Where budget.yaml and pricing.yaml live, beside the settings file in use."""
    from analysis_system.settings import DEFAULT_CONFIG_PATH

    override = os.environ.get(CONFIG_ENV_VAR)
    beside = Path(override).parent if override else DEFAULT_CONFIG_PATH.parent
    return beside if (beside / BUDGET_FILE).is_file() else DEFAULT_CONFIG_PATH.parent
