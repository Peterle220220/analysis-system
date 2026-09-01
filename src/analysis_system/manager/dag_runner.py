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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from analysis_system.agents.a1_ingest import IngestAgent
from analysis_system.agents.a2_profiler import ProfilerAgent
from analysis_system.agents.a3_cleaner import CleanerAgent
from analysis_system.agents.a4_transformer import TransformerAgent
from analysis_system.agents.a5_validator import ValidatorAgent
from analysis_system.agents.a7_analyst import AnalystAgent
from analysis_system.agents.a8_reporter import ReporterAgent
from analysis_system.agents.base import BaseAgent, ManifestDir
from analysis_system.contracts.agents import Plan, PlannedTask
from analysis_system.contracts.base import DataRef, TaskResult
from analysis_system.manager.dispatcher import Dispatcher
from analysis_system.manager.gates import (
    GateRequest,
    GateStore,
    approved_rules_from,
    finding_options,
    gate_payload,
    rule_options,
)
from analysis_system.manager.planner import (
    PlanError,
    Planner,
    ordered_tasks,
    transitive_dependencies,
)
from analysis_system.manager.retry import RetryPolicy, Sleep, wait
from analysis_system.manager.runner import RunOutcome
from analysis_system.manager.state import (
    RunState,
    StateStore,
    TaskPhase,
    TaskState,
    frozen_tasks,
    should_skip,
)
from analysis_system.manager.verifier import Verdict, verify
from analysis_system.services import storage
from analysis_system.services.audit import AUDIT_FILENAME, AuditLog
from analysis_system.services.boundary import Manifest, load_manifest
from analysis_system.services.budget import BudgetTracker
from analysis_system.services.llm import HandoffPendingError, LlmClient, LlmError
from analysis_system.settings import Settings

PLAN_FILENAME: Final[str] = "plan.json"

BEFORE: Final[str] = "before_execution"
AFTER: Final[str] = "after_execution"

# What a manifest asks to have approved, and the scope param that carries the
# answer. A gate whose `approve` is not in here is refused loudly: a gate the
# Manager cannot act on would pause a run forever.
GATE_PARAM: Final[Mapping[str, str]] = {
    "proposed_rules": "approved_rules",
    "findings": "approved_findings",
}

AGENT_TYPES: Final[Mapping[str, type[BaseAgent]]] = {
    "a1_ingest": IngestAgent,
    "a2_profiler": ProfilerAgent,
    "a3_cleaner": CleanerAgent,
    "a4_transformer": TransformerAgent,
    "a5_validator": ValidatorAgent,
    "a7_analyst": AnalystAgent,
    "a8_reporter": ReporterAgent,
}


class DagError(RuntimeError):
    """The plan cannot be carried out, for a reason no retry would change."""


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
    ) -> None:
        """Bind the loop to one run directory."""
        self._settings = settings
        self._run_dir = run_dir
        self._llm = llm
        self._manifest_dir = manifest_dir
        self._budget = budget
        self._retry = retry or RetryPolicy()
        self._sleep = sleep
        self._planner = planner
        self._max_replans = max_replans

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
        """Walk the plan in order, one task at a time."""
        state = states.load_or_create(run_id, now=moment)
        if state.source is None:
            state = state.with_source(source)
            states.save(state)

        dispatcher = Dispatcher(run_id, audit, budget=self._budget)
        reachable = transitive_dependencies(plan)
        results: list[TaskResult] = []

        for task in ordered_tasks(plan):
            manifest = load_manifest(task.agent_id, self._manifest_dir)
            gate = manifest.human_gate
            gate_id = gate_id_for(task.task_id)
            decision = state.gates.get(gate_id)
            waits_after = gate.required and gate.at == AFTER

            try:
                inputs = self._inputs_for(task, state, source)
            except DagError as error:
                return RunOutcome(state, results=tuple(results), escalation=str(error), plan=plan)

            hashes = tuple(sorted(ref.content_hash for ref in inputs))

            if should_skip(state, task.task_id, hashes):
                # Done already - but a gate it never answered still blocks
                # everything downstream, even across a restart.
                if waits_after and decision is None:
                    return self._paused(state, states, audit, task, gate_id, results, plan, moment)
                continue

            params = self._params_for(task, plan, state, reachable)
            if gate.required and gate.at == BEFORE and decision is not None:
                params[self._param_for(manifest)] = approved_rules_from(
                    gates.read(gate_id), decision
                )

            state, result, verdict = self._attempt(
                task,
                manifest,
                inputs,
                params,
                hashes,
                state=state,
                states=states,
                audit=audit,
                dispatcher=dispatcher,
                moment=moment,
            )
            results.append(result)

            if verdict.decision == "GATE":
                self._write_gate(gates, run_id, task, manifest, result, moment)
                return self._paused(state, states, audit, task, gate_id, results, plan, moment)

            if verdict.decision != "PASS":
                reason = f"{task.task_id}: {'; '.join(verdict.reasons) or verdict.decision}"
                state = state.with_phase("HALTED", now=moment)
                states.save(state)
                audit.record("RUN_ENDED", now=moment, status="HALTED", detail={"reason": reason})
                return RunOutcome(state, results=tuple(results), escalation=reason, plan=plan)

            blocked = self._halt_reason(manifest, result)
            if blocked is not None:
                # An exclusive gateway: nothing downstream may consume a result
                # that failed its declared checks. Not an escalation - a replan
                # over the same data would fail the same way.
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
                audit.record("RUN_ENDED", now=moment, status="HALTED", detail={"reason": blocked})
                return RunOutcome(
                    state, results=tuple(results), halted=f"{task.task_id}: {blocked}", plan=plan
                )

            if waits_after and decision is None:
                self._write_gate(gates, run_id, task, manifest, result, moment)
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
        *,
        state: RunState,
        states: StateStore,
        audit: AuditLog,
        dispatcher: Dispatcher,
        moment: datetime,
    ) -> tuple[RunState, TaskResult, Verdict]:
        """Run one task, retrying with backoff for as long as that is the verdict."""
        previous = state.task(task.task_id)
        attempts = previous.attempts if previous else 0

        while True:
            attempts += 1
            scope = dispatcher.issue_scope(task.task_id, manifest, params=params, now=moment)
            result = dispatcher.dispatch(
                self._agent_for(manifest),
                scope,
                input_refs=inputs,
                instruction=task.instruction,
                now=moment,
            )
            verdict = verify(result, manifest, scope, attempts=attempts)
            detail: dict[str, Any] = {"reasons": list(verdict.reasons), "attempt": attempts}

            if verdict.decision == "RETRY":
                detail["backoff_s"] = self._wait_before_retry(result, attempts)
            audit.record(
                "VALIDATION_RESULT",
                now=moment,
                task_id=task.task_id,
                agent_id=task.agent_id,
                status=verdict.decision,
                detail=detail,
            )
            if verdict.decision != "RETRY":
                break

        state = self._record(
            state, states, task, result, hashes, attempts, _phase_for(verdict, result), moment
        )
        return state, result, verdict

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

    def _agent_for(self, manifest: Manifest) -> BaseAgent:
        """Build the agent this manifest describes.

        Whether it is handed a model is the manifest's call, not a list kept
        here: an agent whose manifest says `llm.enabled: false` cannot be given
        one by accident.
        """
        factory = AGENT_TYPES.get(manifest.agent_id)
        if factory is None:
            raise DagError(f"Chua co code cho agent {manifest.agent_id!r}.")
        if manifest.allow.llm.enabled and self._llm is not None:
            return factory(self._settings, self._manifest_dir, llm=self._llm)  # type: ignore[call-arg]
        return factory(self._settings, self._manifest_dir)

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
            options = rule_options(rules)
            stored = gate_payload(proposal)
            title = "HUMAN GATE 1 - duyet rule lam sach"
            question = "Rule nao duoc phep chay? Chi rule duoc duyet moi duoc thuc thi."
        elif kind == "findings":
            found = [item for item in (payload.get("findings") or []) if isinstance(item, dict)]
            options = finding_options(found)
            stored = {"analysis": payload}
            title = "HUMAN GATE 2 - duyet ket luan"
            question = "Ket luan nao duoc dua vao bao cao? Ket luan khong duyet se khong xuat hien."
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
                output_refs=result.output_refs,
                metrics=result.metrics,
                error=result.error,
                updated_at=now,
            ),
            now=now,
        )
        states.save(updated)
        return updated
