"""The Phase 2 loop: execute a whole plan, not a hard-coded pair of agents.

Phase 1 ran A2 and A3 in an order written into the code. This runs whatever the
planner produced, which means three things had to become general rather than
special cases:

**Gates come from manifests.** No agent id appears in a conditional here. A task
stops for a person because its manifest says `human_gate.required`, and *when*
it stops because the manifest says `before_execution` or `after_execution`. A
gate before execution runs the agent in proposal mode, writes what it proposed,
and stops; a gate after execution lets the agent finish, then stops before
anything downstream may use the result.

**Inputs come from the plan, not from the order.** A task reads what
`inputs_from` names, falling back to its dependencies. The two are usually the
same and sometimes not: A7 must run after validation, but what it reads is the
mart table A4 built.

**A failure is answered in proportion.** A transient failure is retried with
backoff. A failure that survives the retries escalates - and if a planner with a
model is available, the run gets one chance to be re-planned around the failure
before giving up. A boundary violation and a budget halt are never retried at
all; that judgement lives in the verifier and is not repeated here.

Everything else is inherited from Phase 1 and unchanged: state is written after
every task so a kill can be resumed, a gate writes a file and exits rather than
blocking, and the Manager never opens a data file - it moves DataRef values
around and reads metrics.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from analysis_system.agents.a1_ingest import IngestAgent
from analysis_system.agents.a2_profiler import ProfilerAgent
from analysis_system.agents.a3_cleaner import CleanerAgent
from analysis_system.agents.a4_transformer import TransformerAgent
from analysis_system.agents.a5_validator import ValidatorAgent
from analysis_system.agents.a6_process_miner import ProcessMinerAgent
from analysis_system.agents.a7_analyst import AnalystAgent
from analysis_system.agents.a8_reporter import ReporterAgent
from analysis_system.agents.a9_manager import ManagerAgent
from analysis_system.agents.a10_text_miner import TextMinerAgent
from analysis_system.agents.base import EMPTY_ANSWER_CODE, BaseAgent, ManifestDir
from analysis_system.agents.extractors import (
    AudioExtractor,
    DocumentExtractor,
    ImageExtractor,
    PdfExtractor,
)
from analysis_system.contracts.agents import Plan, PlannedTask
from analysis_system.contracts.base import DataRef, RetryFeedback, TaskResult
from analysis_system.core import storage
from analysis_system.core.audit import AUDIT_FILENAME, AuditEvent, AuditLog
from analysis_system.core.boundary import LlmPolicy, Manifest, load_manifest
from analysis_system.core.budget import BudgetTracker
from analysis_system.core.settings import Settings
from analysis_system.manager.dispatcher import Dispatcher
from analysis_system.manager.gates import (
    GateError,
    GateRequest,
    GateStore,
    answered,
    approved_rules_from,
    claim_options,
    finding_options,
    gate_payload,
    rule_options,
    span_options,
)
from analysis_system.manager.planner import (
    PlanError,
    Planner,
    transitive_dependencies,
    waves,
)
from analysis_system.manager.retry import RetryPolicy, Sleep, wait
from analysis_system.manager.runner import RunOutcome
from analysis_system.manager.state import (
    GateDecision,
    RunState,
    StateStore,
    TaskPhase,
    TaskState,
    frozen_tasks,
    params_fingerprint,
    should_skip,
)
from analysis_system.manager.verifier import Verdict, retry_ceiling, verify
from analysis_system.services.llm import HandoffPendingError, LlmClient, LlmError

PLAN_FILENAME: Final[str] = "plan.json"
RETRY_FEEDBACK_PARAM: Final[str] = "retry_feedback"

BEFORE: Final[str] = "before_execution"
AFTER: Final[str] = "after_execution"

# What a manifest asks to have approved, and the scope param that carries the
# answer. A gate whose `approve` is not in here is refused loudly: a gate the
# Manager cannot act on would pause a run forever.
GATE_PARAM: Final[Mapping[str, str]] = {
    "proposed_rules": "approved_rules",
    "findings": "approved_findings",
    "claims": "approved_claims",
    "spans": "approved_spans",
}

AGENT_TYPES: Final[Mapping[str, type[BaseAgent]]] = {
    "a1_ingest": IngestAgent,
    "a2_profiler": ProfilerAgent,
    "a3_cleaner": CleanerAgent,
    "a4_transformer": TransformerAgent,
    "a5_validator": ValidatorAgent,
    "a6_process_miner": ProcessMinerAgent,
    "a7_analyst": AnalystAgent,
    "a8_reporter": ReporterAgent,
    "a9_manager": ManagerAgent,
    "a10_text_miner": TextMinerAgent,
    "e1_pdf": PdfExtractor,
    "e2_image": ImageExtractor,
    "e3_audio": AudioExtractor,
    "e4_document": DocumentExtractor,
}


# Attempts the manifest's own model keeps before the work moves on. Two: one
# clean, and one carrying the feedback about what was wrong with the first,
# because being told repairs a great many answers. A third identical failure
# says nothing the second did not.
ATTEMPTS_BEFORE_FALLBACK: Final[int] = 2


def choose_model(policy: LlmPolicy, attempt: int) -> str:
    """Which model this attempt should use.

    Empty means whatever the run was started with - the behaviour of a manifest
    naming nothing, unchanged.
    """
    if attempt <= ATTEMPTS_BEFORE_FALLBACK or not policy.fallback:
        return policy.model
    # Cycles rather than stopping at the last name: a run with a generous retry
    # ceiling should keep alternating instead of hammering one model.
    return policy.fallback[(attempt - ATTEMPTS_BEFORE_FALLBACK - 1) % len(policy.fallback)]


def after_empty_answer(attempt: int, offset: int, result: TaskResult) -> int:
    """How many primary-model turns to skip after this attempt.

    The primary keeps two turns because the second carries feedback. An empty
    answer leaves nothing to give feedback on: gpt-oss-20b returned
    `content: null` twice in a row, and the one attempt left went to the
    fallback (bao_cao_tai_chinh_mb_cua_4_quy_gan_nhat__q1, 2026-09-15). After an
    empty answer the next attempt goes to the fallback at once.
    """
    if result.error is None or result.error.code != EMPTY_ANSWER_CODE:
        return offset
    return max(offset, ATTEMPTS_BEFORE_FALLBACK - attempt)


class DagError(RuntimeError):
    """The plan cannot be carried out, for a reason no retry would change."""


def _output_hash(refs: tuple[DataRef, ...]) -> str:
    """The hash of what a task produced, or empty when it produced nothing."""
    return refs[0].content_hash if refs else ""


def gate_id_for(task_id: str) -> str:
    """The gate belonging to one task."""
    return f"gate_{task_id}"


def _phase_for(verdict: Verdict, result: TaskResult) -> TaskPhase:
    """How a task's outcome is written down.

    A verdict is about what happens next; a phase is about what happened. The
    two only differ where a task succeeded but still owes a person an answer.
    """
    if verdict.decision == "GATE":
        return "AWAITING_APPROVAL"
    if verdict.decision == "PASS":
        return "OK"
    if result.status == "BOUNDARY_VIOLATION":
        return "BOUNDARY_VIOLATION"
    if result.status == "HALTED_BUDGET":
        return "HALTED_BUDGET"
    return "FAILED"


@dataclass(frozen=True)
class Attempted:
    """What running one task produced, before anything was written down.

    Everything in here is the task's own: no state, no gate decision, no audit
    written yet. That is what lets a whole wave of tasks be run at the same time
    and still have the run make its decisions one at a time, in task order.

    The audit entries are carried rather than written because two threads
    appending to one log put their lines in whatever order they finished in,
    and two runs of the same plan are supposed to produce the same trail.
    """

    task_id: str
    result: TaskResult
    verdict: Verdict
    attempts_total: int
    audit_entries: tuple[tuple[AuditEvent, dict[str, Any]], ...] = ()


class DagRunner:
    """Executes a checked plan, pausing at gates and retrying what deserves it."""

    def __init__(
        self,
        settings: Settings,
        run_dir: Path,
        *,
        llm: LlmClient | None = None,
        manifest_dir: ManifestDir = None,
        budget: BudgetTracker | None = None,
        retry: RetryPolicy | None = None,
        sleep: Sleep = time.sleep,
        planner: Planner | None = None,
        max_replans: int = 1,
        max_parallel: int | None = None,
    ) -> None:
        """Bind the loop to one run directory.

        `max_parallel` caps how many tasks of one wave run at the same time.
        One turns it off entirely, which is what every test that counts calls
        or watches for an exact order should use.
        """
        self._max_parallel = max_parallel if max_parallel is not None else settings.llm.max_parallel
        self._settings = settings
        self._run_dir = run_dir
        self._llm = llm
        self._manifest_dir = manifest_dir
        self._budget = budget
        self._retry = retry or RetryPolicy()
        self._sleep = sleep
        self._planner = planner
        self._max_replans = max_replans
        # Gio co dinh chi khi nguoi goi truyen `now` (test). Xem `_attempt`.
        self._pinned = False

    def run(
        self,
        plan: Plan,
        source: DataRef,
        *,
        run_id: str,
        question: str = "",
        now: datetime | None = None,
    ) -> RunOutcome:
        """Run the plan as far as it can, stopping at the first thing a person owes it.

        Three things can stop it short: an undecided gate, a prompt waiting to be
        relayed by hand, and an escalation. The first two are pauses; only the
        third is a failure, and even then a planner with a model gets one chance
        to route around it.
        """
        moment = now or datetime.now(UTC)
        self._pinned = now is not None
        self._run_dir.mkdir(parents=True, exist_ok=True)

        audit = AuditLog(self._run_dir / AUDIT_FILENAME, run_id)
        states = StateStore(self._run_dir / "state.json")
        gates = GateStore(self._run_dir)

        current = plan
        self._save_plan(current)
        outcome = RunOutcome(states.load_or_create(run_id, now=moment), plan=current)

        for round_number in range(self._max_replans + 1):
            if round_number == 0:
                audit.record("RUN_STARTED", now=moment, detail={"source": source.path})
            audit.record(
                "PLAN_CREATED",
                now=moment,
                detail={
                    "tasks": [task.task_id for task in current.tasks],
                    "reason": current.reason,
                    "replan_round": round_number,
                },
            )
            try:
                outcome = self._execute(
                    current,
                    source,
                    run_id=run_id,
                    moment=moment,
                    audit=audit,
                    states=states,
                    gates=gates,
                )
            except HandoffPendingError as pending:
                return self._pause_for_handoff(states, audit, run_id, moment, str(pending), current)

            if outcome.halted is not None or outcome.escalation is None:
                return outcome
            if not outcome.can_replan:
                # The plan is not what failed. Asking for another one would
                # spend a call to arrive back where we started.
                return outcome
            replanned = self._replan(
                current, source, question, outcome.escalation, round_number, outcome.state
            )
            if replanned is None:
                return outcome
            current = replanned
            # The plan on disk must be the plan being executed. Leaving the
            # original there is how state and plan drifted apart, and resume
            # then reloads a plan the state no longer matches.
            self._save_plan(current)

        return outcome

    # --- the loop over one plan -----------------------------------------------

    def _run_wave(
        self,
        wave: list[tuple[PlannedTask, Manifest, tuple[DataRef, ...], dict[str, Any]]],
        *,
        state: RunState,
        dispatcher: Dispatcher,
        moment: datetime,
    ) -> dict[str, Attempted]:
        """Run every task in one wave, at the same time when there is more than one.

        Threads rather than processes: the slow part is waiting on a model, and
        an agent that computes releases the interpreter while pandas works.

        A failure inside a thread is carried back rather than raised here, so
        the caller still processes the wave in task order and still reports what
        the other tasks did. `BudgetExceeded` is the exception: it means the job
        has run out of money, and continuing would spend more of it.
        """
        if len(wave) == 1 or self._max_parallel <= 1:
            return {
                task.task_id: self._work(
                    task,
                    manifest,
                    inputs,
                    params,
                    state=state,
                    dispatcher=dispatcher,
                    moment=moment,
                )
                for task, manifest, inputs, params in wave
            }

        done: dict[str, Attempted] = {}
        workers = min(self._max_parallel, len(wave))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            running = {
                pool.submit(
                    self._work,
                    task,
                    manifest,
                    inputs,
                    params,
                    state=state,
                    dispatcher=dispatcher,
                    moment=moment,
                ): task.task_id
                for task, manifest, inputs, params in wave
            }
            for future in as_completed(running):
                done[running[future]] = future.result()
        return done

    def _execute(
        self,
        plan: Plan,
        source: DataRef,
        *,
        run_id: str,
        moment: datetime,
        audit: AuditLog,
        states: StateStore,
        gates: GateStore,
    ) -> RunOutcome:
        """Walk the plan a wave at a time, running each wave's tasks together.

        A wave is the set of tasks whose dependencies are already met, so no
        task in one can read another's output. That is what makes running them
        at the same time safe, and it is also why nothing about the *decisions*
        changes: preparation reads state sequentially, the slow part overlaps,
        and every outcome is then processed in task order exactly as before.
        """
        state = states.load_or_create(run_id, now=moment)
        if state.source is None:
            state = state.with_source(source)
            states.save(state)

        dispatcher = Dispatcher(run_id, audit, budget=self._budget)
        reachable = transitive_dependencies(plan)
        results: list[TaskResult] = []

        for group in waves(plan):
            ready: list[tuple[PlannedTask, Manifest, tuple[DataRef, ...], dict[str, Any]]] = []
            settled: dict[str, tuple[str, str, bool, tuple[str, ...]]] = {}

            for task in group:
                manifest = load_manifest(task.agent_id, self._manifest_dir)
                gate = manifest.human_gate
                gate_id = gate_id_for(task.task_id)
                decision = state.gates.get(gate_id)
                waits_after = gate.required and gate.at == AFTER

                try:
                    inputs = self._inputs_for(task, state, source)
                except DagError as error:
                    return RunOutcome(
                        state, results=tuple(results), escalation=str(error), plan=plan
                    )

                hashes = tuple(sorted(ref.content_hash for ref in inputs))
                # Built before the skip check rather than after it: what a task
                # was told to do is half of whether its stored result still
                # answers the question being asked now.
                params = self._params_for(task, plan, state, reachable)
                # An approval is carried forward only while it still answers the
                # question this gate is asking. A task that proposed again may be
                # proposing something else, and applying an old approval to a new
                # proposal runs rules nobody chose.
                if (
                    gate.required
                    and gate.at == BEFORE
                    and decision is not None
                    and self._gate_settled(gates, gate_id, decision, state)
                ):
                    params[self._param_for(manifest)] = approved_rules_from(
                        gates.read(gate_id), decision
                    )
                fingerprint = params_fingerprint(params)

                if should_skip(state, task.task_id, hashes, fingerprint):
                    # Done already - but a gate it never answered still blocks
                    # everything downstream, even across a restart. So does one
                    # answered about a result this task has since replaced: the
                    # question on disk is the one this task last asked, and an
                    # approval that does not match it approves something else.
                    if waits_after and not self._gate_current(gates, gate_id, state, task.task_id):
                        # The question on disk is about a result this task has
                        # since replaced, and nothing would refresh it while the
                        # task is skipped. Run it again so the person is asked
                        # about what is actually there.
                        pass
                    elif waits_after and not self._gate_settled(gates, gate_id, decision, state):
                        return self._paused(
                            state, states, audit, task, gate_id, results, plan, moment
                        )
                    else:
                        continue

                ready.append((task, manifest, inputs, params))
                settled[task.task_id] = (gate_id, fingerprint, waits_after, hashes)

            if not ready:
                continue

            done = self._run_wave(ready, state=state, dispatcher=dispatcher, moment=moment)

            # Processed in task order, never in the order they happened to
            # finish. Two runs of the same plan must reach the same decisions in
            # the same sequence, which is what criterion S1 asks for.
            for task, manifest, _inputs, _params in ready:
                gate_id, fingerprint, waits_after, hashes = settled[task.task_id]
                decision = state.gates.get(gate_id)
                attempted = done[task.task_id]
                result, verdict = attempted.result, attempted.verdict

                for event, fields in attempted.audit_entries:
                    audit.record(event, now=moment, **fields)
                state = self._record(
                    state,
                    states,
                    task,
                    result,
                    hashes,
                    fingerprint,
                    attempted.attempts_total,
                    _phase_for(verdict, result),
                    moment,
                )
                results.append(result)

                # The question a person is shown always describes this task's
                # current result. Written here rather than only when the run
                # pauses: a gated task can produce a new result without pausing,
                # and after that the file on disk described a result that no
                # longer existed.
                if waits_after and result.is_ok:
                    self._write_gate(gates, run_id, task, manifest, result, moment)

                if verdict.decision == "GATE":
                    self._write_gate(gates, run_id, task, manifest, result, moment)
                    return self._paused(state, states, audit, task, gate_id, results, plan, moment)

                if verdict.decision != "PASS":
                    reason = f"{task.task_id}: {'; '.join(verdict.reasons) or verdict.decision}"
                    state = state.with_phase("HALTED", now=moment)
                    states.save(state)
                    audit.record(
                        "RUN_ENDED", now=moment, status="HALTED", detail={"reason": reason}
                    )
                    return RunOutcome(
                        state,
                        results=tuple(results),
                        escalation=reason,
                        plan=plan,
                        can_replan=result.error is not None and result.error.replannable,
                    )

                blocked = self._halt_reason(manifest, result)
                if blocked is not None:
                    # An exclusive gateway: nothing downstream may consume a
                    # result that failed its declared checks. Not an escalation -
                    # a replan over the same data would fail the same way.
                    state = state.with_phase("HALTED", now=moment)
                    states.save(state)
                    audit.record(
                        "VALIDATION_RESULT",
                        now=moment,
                        task_id=task.task_id,
                        agent_id=task.agent_id,
                        status="HALT",
                        detail={"reason": blocked},
                    )
                    audit.record(
                        "RUN_ENDED", now=moment, status="HALTED", detail={"reason": blocked}
                    )
                    return RunOutcome(
                        state,
                        results=tuple(results),
                        halted=f"{task.task_id}: {blocked}",
                        plan=plan,
                    )

                if waits_after and not self._gate_settled(gates, gate_id, decision, state):
                    return self._paused(state, states, audit, task, gate_id, results, plan, moment)

        state = state.with_phase("COMPLETED", now=moment)
        states.save(state)
        audit.record("RUN_ENDED", now=moment, status="COMPLETED")
        return RunOutcome(state, results=tuple(results), plan=plan)

    # --- one task -------------------------------------------------------------

    def _attempt(
        self,
        task: PlannedTask,
        manifest: Manifest,
        inputs: tuple[DataRef, ...],
        params: dict[str, Any],
        hashes: tuple[str, ...],
        fingerprint: str,
        *,
        state: RunState,
        states: StateStore,
        audit: AuditLog,
        dispatcher: Dispatcher,
        moment: datetime,
    ) -> tuple[RunState, TaskResult, Verdict]:
        """Run one task and record what happened. Sequential path, unchanged."""
        done = self._work(
            task, manifest, inputs, params, state=state, dispatcher=dispatcher, moment=moment
        )
        for event, fields in done.audit_entries:
            audit.record(event, now=moment, **fields)
        state = self._record(
            state,
            states,
            task,
            done.result,
            hashes,
            fingerprint,
            done.attempts_total,
            _phase_for(done.verdict, done.result),
            moment,
        )
        return state, done.result, done.verdict

    def _work(
        self,
        task: PlannedTask,
        manifest: Manifest,
        inputs: tuple[DataRef, ...],
        params: dict[str, Any],
        *,
        state: RunState,
        dispatcher: Dispatcher,
        moment: datetime,
    ) -> Attempted:
        """Run one task, retrying while that is the verdict. Touches no state.

        Everything here is either read-only or the agent's own business, which
        is what lets a whole wave of these run at the same time. What the run
        *decides* - state, gates, halting - stays in the caller, in task order.
        """
        previous = state.task(task.task_id)
        # Attempts already spent, kept for the record. The retry budget itself
        # starts fresh: a task that failed and was then resumed by a person got
        # no retries at all when the count carried over, which made resuming
        # useless for exactly the failures a person resumes about.
        spent = previous.attempts if previous else 0
        attempts = 0
        # Luot cua model chinh bi bo qua vi no vua tra ve rong.
        skipped = 0
        entries: list[tuple[AuditEvent, dict[str, Any]]] = []

        while True:
            attempts += 1
            # Gio that cua tung luot. Dung gio bat dau run thi moi SCOPE_ISSUED va
            # TASK_STARTED deu ghi cung mot moc (khong doc duoc luot nao cham), va
            # tran thoi gian cua job khong bao gio bi vuot vi dong ho dung yen.
            stamp = moment if self._pinned else datetime.now(UTC)
            scope = dispatcher.issue_scope(task.task_id, manifest, params=params, now=stamp)
            agent, model_used = self._agent_for(manifest, attempts + skipped)
            result = dispatcher.dispatch(
                agent,
                scope,
                input_refs=inputs,
                instruction=task.instruction,
                now=stamp,
            )
            verdict = verify(result, manifest, scope, attempts=attempts)
            detail: dict[str, Any] = {
                "reasons": list(verdict.reasons),
                "attempt": attempts,
                "attempts_total": spent + attempts,
            }
            if model_used:
                # Which model answered. Without it a fallback would change who
                # produced a finding without leaving any record that it did.
                detail["model"] = model_used

            if verdict.decision == "RETRY":
                detail["backoff_s"] = self._wait_before_retry(result, attempts)
            entries.append(
                (
                    "VALIDATION_RESULT",
                    {
                        "task_id": task.task_id,
                        "agent_id": task.agent_id,
                        "status": verdict.decision,
                        "detail": detail,
                    },
                )
            )
            if verdict.decision != "RETRY":
                break
            skipped = after_empty_answer(attempts, skipped, result)

            # Ask again, but not the same question. Without the reasons the
            # next attempt is a coin flip; with them the model is being told
            # precisely what to fix.
            params = {
                **params,
                RETRY_FEEDBACK_PARAM: RetryFeedback(
                    attempt=attempts,
                    max_attempts=retry_ceiling(manifest, scope),
                    previous_answer=result.payload,
                    rejected_because=verdict.reasons,
                ).model_dump(mode="json"),
            }

        return Attempted(
            task_id=task.task_id,
            result=result,
            verdict=verdict,
            attempts_total=spent + attempts,
            audit_entries=tuple(entries),
        )

    def _wait_before_retry(self, result: TaskResult, attempts: int) -> float:
        """Wait out one failed attempt.

        When whatever refused said how long to wait, that wins over the policy.
        A service asking for forty-five seconds means it; backing off for two
        would spend the remaining retries inside the same refusal window.
        """
        asked = result.error.retry_after_s if result.error else None
        if asked is not None and asked > 0:
            self._sleep(asked)
            return asked
        return wait(self._retry, attempts, self._sleep)

    def _save_plan(self, plan: Plan) -> None:
        """Record the plan actually being executed, next to the state it produces."""
        storage.write_text(plan.model_dump_json(indent=2), self._run_dir / PLAN_FILENAME)

    def _halt_reason(self, manifest: Manifest, result: TaskResult) -> str | None:
        """Why this result must stop the run, if a declared condition says so.

        The condition lives in the manifest, not here. An agent id inside a
        conditional would be a rule nobody can see from outside the code.
        """
        for condition in manifest.halt_on:
            if condition.triggered_by(result.metrics):
                return condition.describe(result.metrics)
        return None

    def _agent_for(self, manifest: Manifest, attempt: int = 1) -> tuple[BaseAgent, str]:
        """Build the agent this manifest describes, and say which model it got.

        Whether it is handed a model is the manifest's call, not a list kept
        here: an agent whose manifest says `llm.enabled: false` cannot be given
        one by accident.

        Which model depends on how many attempts have already failed. The
        primary keeps the first two - one clean, one carrying the feedback,
        because being told what was wrong repairs a great many answers. After
        that the work moves to the next model rather than being abandoned: a
        fourth identical failure says nothing the third did not.

        Returns:
            The agent, and the model it is using. The name goes into the audit,
            because a run whose provenance says only "some model" cannot be
            checked afterwards.
        """
        factory = AGENT_TYPES.get(manifest.agent_id)
        if factory is None:
            raise DagError(f"Chua co code cho agent {manifest.agent_id!r}.")
        if not (manifest.allow.llm.enabled and self._llm is not None):
            return factory(self._settings, self._manifest_dir), ""

        # Which model, not only whether. A manifest naming none keeps the model
        # the run started with, so nothing changes for the agents that have no
        # preference.
        llm = self._llm.for_model(choose_model(manifest.allow.llm, attempt))
        agent = factory(self._settings, self._manifest_dir, llm=llm)  # type: ignore[call-arg]
        return agent, llm.model_name

    def _inputs_for(
        self, task: PlannedTask, state: RunState, source: DataRef
    ) -> tuple[DataRef, ...]:
        """What this task reads: upstream outputs, or the run source if it has none."""
        upstream_ids = task.reads_from
        if not upstream_ids:
            return (source,)
        refs: list[DataRef] = []
        for upstream_id in upstream_ids:
            stored = state.task(upstream_id)
            if stored is None or not stored.output_refs:
                raise DagError(
                    f"task {task.task_id!r} doc ket qua cua {upstream_id!r}, "
                    "nhung task do chua ghi ra gi."
                )
            refs.extend(stored.output_refs)
        return tuple(refs)

    def _params_for(
        self,
        task: PlannedTask,
        plan: Plan,
        state: RunState,
        reachable: dict[str, set[str]],
    ) -> dict[str, Any]:
        """The task's own params, plus any approval it inherits from upstream.

        A gate answered after an upstream task ran does not change that task -
        it already finished. What it changes is everything downstream, so the
        decision travels as a param, the same way an approved rule list does.
        """
        params = dict(task.params)
        by_id = {item.task_id: item for item in plan.tasks}
        for upstream_id in sorted(reachable[task.task_id]):
            manifest = load_manifest(by_id[upstream_id].agent_id, self._manifest_dir)
            gate = manifest.human_gate
            if not (gate.required and gate.at == AFTER):
                continue
            decision = state.gates.get(gate_id_for(upstream_id))
            if decision is not None:
                params[self._param_for(manifest)] = list(decision.approved)
        return params

    def _param_for(self, manifest: Manifest) -> str:
        """The scope param that carries this manifest's approval."""
        name = GATE_PARAM.get(manifest.human_gate.approve)
        if name is None:
            raise DagError(
                f"Manifest {manifest.agent_id!r} doi duyet {manifest.human_gate.approve!r}, "
                "nhung Manager khong biet chuyen quyet dinh do di dau."
            )
        return name

    # --- gates, pauses and state ----------------------------------------------

    def _gate_settled(
        self,
        gates: GateStore,
        gate_id: str,
        decision: GateDecision | None,
        state: RunState,
    ) -> bool:
        """True when a person has answered the question this gate is now asking.

        Not merely "has answered it once". A task that ran again may be asking
        something different, and an approval of three conclusions says nothing
        about the two a narrowed analysis produced.
        """
        if decision is None:
            return False
        try:
            asked = gates.read(gate_id)
        except GateError:
            # No question on disk to compare against. The decision is all there
            # is, and refusing to honour it would strand the run.
            return True
        return answered(state, asked)

    def _gate_current(self, gates: GateStore, gate_id: str, state: RunState, task_id: str) -> bool:
        """True when the question on disk was built from this task's current output."""
        stored = state.task(task_id)
        if stored is None:
            return False
        try:
            asked = gates.read(gate_id)
        except GateError:
            return False
        return asked.describes(_output_hash(stored.output_refs))

    def _write_gate(
        self,
        gates: GateStore,
        run_id: str,
        task: PlannedTask,
        manifest: Manifest,
        result: TaskResult,
        now: datetime,
    ) -> GateRequest:
        """Turn what an agent produced into something a person can answer."""
        kind = manifest.human_gate.approve
        payload = result.payload or {}

        if kind == "proposed_rules":
            proposal = payload.get("proposal") or {}
            rules = [rule for rule in (proposal.get("rules") or []) if isinstance(rule, dict)]
            # The scope travels beside the proposal, so a person is shown what
            # the rule will touch rather than what the model meant.
            options = rule_options(rules, payload.get("rule_scope"))
            stored = gate_payload(proposal)
            # What the examination found, carried to where the decision is made.
            # A person approving cleaning wants to know what was looked at and
            # what was counted, and that had been living only in the run report
            # - visible once, at the terminal, and gone by the time anybody
            # opened the gate again.
            stored["da_xem"] = list(result.declined)
            # "HUMAN GATE 1" la ten trong ma nguon, khong phai ten de hien len man
            # hinh. Nguoi dung doc mot tieu de bang tieng cua lap trinh vien
            # thi ho khong duyet, ho doan.
            title = "Duyệt cách làm sạch dữ liệu"
            question = (
                "Cách làm sạch nào được phép chạy? Chỉ những cách bạn đồng ý mới được thực hiện."
            )
        elif kind == "spans":
            found = [item for item in (payload.get("spans") or []) if isinstance(item, dict)]
            options = span_options(found)
            stored = {"extraction": payload}
            title = "Duyệt bản trích xuất: đoạn đọc chưa chắc chắn"
            question = "Đoạn nào đọc đúng? Đoạn không duyệt sẽ không được dùng ở bước sau."
        elif kind == "claims":
            found = [item for item in (payload.get("claims") or []) if isinstance(item, dict)]
            options = claim_options(found)
            stored = {"answer": payload}
            title = "Duyệt lập luận: câu trả lời của Manager"
            question = (
                "Luận điểm nào được đưa vào báo cáo? Luận điểm không duyệt sẽ không xuất hiện."
            )
        elif kind == "findings":
            found = [item for item in (payload.get("findings") or []) if isinstance(item, dict)]
            options = finding_options(found)
            stored = {"analysis": payload}
            title = "Duyệt kết luận"
            question = "Kết luận nào được đưa vào báo cáo? Kết luận không duyệt sẽ không xuất hiện."
        else:
            raise DagError(f"Gate loai {kind!r} chua duoc ho tro.")

        request = GateRequest(
            gate_id=gate_id_for(task.task_id),
            run_id=run_id,
            task_id=task.task_id,
            agent_id=task.agent_id,
            title=title,
            question=question,
            options=options,
            payload=stored,
            result_hash=_output_hash(result.output_refs),
            created_at=now,
        )
        gates.write(request)
        return request

    def _paused(
        self,
        state: RunState,
        states: StateStore,
        audit: AuditLog,
        task: PlannedTask,
        gate_id: str,
        results: list[TaskResult],
        plan: Plan,
        now: datetime,
    ) -> RunOutcome:
        """Stop cleanly, leaving a gate for a person and a state to resume from."""
        audit.record(
            "HUMAN_GATE",
            now=now,
            task_id=task.task_id,
            agent_id=task.agent_id,
            detail={"gate_id": gate_id},
        )
        state = state.with_phase("PAUSED_AWAITING_APPROVAL", now=now)
        states.save(state)
        return RunOutcome(state, paused_gate=gate_id, results=tuple(results), plan=plan)

    def _pause_for_handoff(
        self,
        states: StateStore,
        audit: AuditLog,
        run_id: str,
        moment: datetime,
        message: str,
        plan: Plan,
    ) -> RunOutcome:
        """Record that the run is waiting for a person to relay an answer."""
        state = states.load_or_create(run_id, now=moment)
        state = state.with_phase("PAUSED_AWAITING_APPROVAL", now=moment)
        states.save(state)
        audit.record("HUMAN_GATE", now=moment, detail={"kind": "llm_handoff"})
        return RunOutcome(state, pending_handoff=message, plan=plan)

    def _replan(
        self,
        current: Plan,
        source: DataRef,
        question: str,
        failure: str,
        round_number: int,
        state: RunState,
    ) -> Plan | None:
        """Ask for a different plan, or return None if that is not on offer.

        Replanning needs a model. Without one there is only the plan that just
        failed, and running it again would fail the same way.

        Whatever already ran is passed in as frozen, and a proposal that
        contradicts it is refused rather than executed. The run then keeps the
        failure it already had to report, which is worth more than a plan that
        rewrites what a person approved.
        """
        if self._planner is None or not self._planner.has_model:
            return None
        if round_number >= self._max_replans:
            return None
        try:
            return self._planner.replan(
                question, source.path, current, failure, tuple(sorted(frozen_tasks(state)))
            )
        except (PlanError, LlmError):
            # A replan that cannot reach the model, or that would overwrite
            # settled work, is not a crash - it is simply no replan.
            return None

    def _record(
        self,
        state: RunState,
        states: StateStore,
        task: PlannedTask,
        result: TaskResult,
        hashes: tuple[str, ...],
        params_hash: str,
        attempts: int,
        phase: TaskPhase,
        now: datetime,
    ) -> RunState:
        """Write one task outcome into the state, immediately."""
        updated = state.with_task(
            TaskState(
                task_id=task.task_id,
                agent_id=result.agent_id or task.agent_id,
                phase=phase,
                attempts=attempts,
                input_hashes=hashes,
                params_hash=params_hash,
                output_refs=result.output_refs,
                metrics=result.metrics,
                error=result.error,
                updated_at=now,
            ),
            now=now,
        )
        states.save(updated)
        return updated
