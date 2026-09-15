"""The Phase 1 orchestration loop: A2, then a human gate, then A3.

Phase 1 has exactly two agents, so its DAG is fixed and declared here. The
planner that derives a DAG with a model arrives in Phase 2, when there are eight
agents whose order actually needs reasoning about. Declaring it now means Phase 1
runs end to end with no model call at all except the two the agents make
themselves - and with `handoff` even those cost nothing.

The loop obeys three rules from the spec:

* The Manager never opens a data file. It passes DataRef values around.
* State is written after every task, so a kill can be resumed.
* A gate writes a file and stops. It never blocks waiting for a person.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from analysis_system.agents.a2_profiler import ProfilerAgent
from analysis_system.agents.a3_cleaner import APPROVED_RULES_PARAM, CleanerAgent
from analysis_system.agents.base import ManifestDir
from analysis_system.core.audit import AUDIT_FILENAME, AuditLog
from analysis_system.core.boundary import load_manifest
from analysis_system.core.budget import BudgetTracker
from analysis_system.core.settings import Settings
from analysis_system.manager.dispatcher import Dispatcher
from analysis_system.manager.gates import (
    GateRequest,
    GateStore,
    approved_rules_from,
    gate_payload,
    rule_options,
)
from analysis_system.manager.state import (
    RunState,
    StateStore,
    TaskState,
    params_fingerprint,
    should_skip,
)
from analysis_system.manager.verifier import verify
from analysis_system.models.agents import Plan
from analysis_system.models.base import DataRef, TaskResult
from analysis_system.services.llm import HandoffPendingError, LlmClient

TASK_PROFILE: Final[str] = "t_profile"
TASK_CLEAN: Final[str] = "t_clean"
GATE_RULES: Final[str] = "gate_1_rules"

PHASE1_DAG: Final[tuple[tuple[str, str], ...]] = (
    (TASK_PROFILE, "a2_profiler"),
    (TASK_CLEAN, "a3_cleaner"),
)


@dataclass(frozen=True)
class RunOutcome:
    """What one invocation of the loop achieved."""

    state: RunState
    paused_gate: str | None = None
    pending_handoff: str | None = None
    results: tuple[TaskResult, ...] = ()
    # Set when the run stopped for a reason no retry would fix. A pause is not
    # an escalation: one is waiting for a person, the other is giving up.
    escalation: str | None = None
    # Set when a declared measurement stopped the run - a table that failed its
    # checks, say. Kept apart from escalation because no replan can fix it: the
    # data did not pass, and a different graph over the same data will not pass
    # either.
    halted: str | None = None
    # Whether the failure that stopped the run was about the plan. Most are not:
    # a model writing a poor answer is not fixed by a different graph, and
    # asking for one spends a planning call to arrive back where it started.
    can_replan: bool = False
    # Which plan was being executed when it stopped. Phase 1 declares its own,
    # so it leaves this empty; Phase 2 carries the plan it actually ran, which
    # after a replan is not the plan it started with.
    plan: Plan | None = None

    @property
    def is_paused(self) -> bool:
        """True when a person has to do something before anything else can happen."""
        return self.paused_gate is not None or self.pending_handoff is not None

    @property
    def is_complete(self) -> bool:
        """True when every task in the DAG finished."""
        return self.state.phase == "COMPLETED"


class Phase1Runner:
    """Runs A2, pauses at the rule gate, then runs A3 with what was approved."""

    def __init__(
        self,
        settings: Settings,
        run_dir: Path,
        *,
        llm: LlmClient | None = None,
        manifest_dir: ManifestDir = None,
        budget: BudgetTracker | None = None,
    ) -> None:
        """Bind the loop to one run directory."""
        self._settings = settings
        self._run_dir = run_dir
        self._llm = llm
        self._manifest_dir = manifest_dir
        self._budget = budget

    def run(self, source: DataRef, *, run_id: str, now: datetime | None = None) -> RunOutcome:
        """Run as far as it can, stopping at the first thing a person must do.

        Two things can stop it: an undecided gate, or a prompt waiting to be
        relayed by hand. Both are pauses, not failures.
        """
        moment = now or datetime.now(UTC)
        try:
            return self._run(source, run_id=run_id, moment=moment)
        except HandoffPendingError as pending:
            return self._pause_for_handoff(run_id, moment, str(pending))

    def _pause_for_handoff(self, run_id: str, moment: datetime, message: str) -> RunOutcome:
        """Record that the run is waiting for a person to relay an answer."""
        states = StateStore(self._run_dir / "state.json")
        audit = AuditLog(self._run_dir / AUDIT_FILENAME, run_id)
        state = states.load_or_create(run_id, now=moment)
        state = state.with_phase("PAUSED_AWAITING_APPROVAL", now=moment)
        states.save(state)
        audit.record("HUMAN_GATE", now=moment, detail={"kind": "llm_handoff"})
        return RunOutcome(state, pending_handoff=message)

    def _run(self, source: DataRef, *, run_id: str, moment: datetime) -> RunOutcome:
        """The loop itself."""
        self._run_dir.mkdir(parents=True, exist_ok=True)

        audit = AuditLog(self._run_dir / AUDIT_FILENAME, run_id)
        states = StateStore(self._run_dir / "state.json")
        gates = GateStore(self._run_dir)
        state = states.load_or_create(run_id, now=moment)

        if state.source is None:
            state = state.with_source(source)
            states.save(state)
        if not state.tasks:
            audit.record("RUN_STARTED", now=moment, detail={"source": source.path})
            audit.record(
                "PLAN_CREATED",
                now=moment,
                detail={"dag": [task for task, _ in PHASE1_DAG], "planner": "declared_phase1"},
            )

        dispatcher = Dispatcher(run_id, audit, budget=self._budget)
        results: list[TaskResult] = []

        # --- A2 -------------------------------------------------------------
        state, profiled = self._profile(state, states, dispatcher, audit, source, moment)
        if profiled is not None:
            results.append(profiled)
            if not profiled.is_ok:
                return RunOutcome(states.load(), results=tuple(results))

        # --- the gate --------------------------------------------------------
        decision = state.gates.get(GATE_RULES)
        if decision is None:
            state, proposal_result = self._propose(state, states, dispatcher, source, moment)
            if proposal_result is not None:
                results.append(proposal_result)
            request = self._write_gate(gates, run_id, proposal_result, moment)
            audit.record(
                "HUMAN_GATE",
                now=moment,
                task_id=TASK_CLEAN,
                agent_id="a3_cleaner",
                detail={"gate_id": request.gate_id, "options": list(request.option_ids)},
            )
            state = state.with_phase("PAUSED_AWAITING_APPROVAL", now=moment)
            states.save(state)
            return RunOutcome(state, paused_gate=request.gate_id, results=tuple(results))

        # --- A3, with exactly what was approved ------------------------------
        request = gates.read(GATE_RULES)
        approved = approved_rules_from(request, decision)
        state, cleaned = self._clean(state, states, dispatcher, source, approved, moment)
        if cleaned is not None:
            results.append(cleaned)
            if not cleaned.is_ok:
                return RunOutcome(states.load(), results=tuple(results))

        state = state.with_phase("COMPLETED", now=moment)
        states.save(state)
        audit.record("RUN_ENDED", now=moment, status="COMPLETED")
        return RunOutcome(state, results=tuple(results))

    # --- individual steps -----------------------------------------------------

    def _profile(
        self,
        state: RunState,
        states: StateStore,
        dispatcher: Dispatcher,
        audit: AuditLog,
        source: DataRef,
        now: datetime,
    ) -> tuple[RunState, TaskResult | None]:
        """Run A2 unless a previous run already did it on the same input."""
        if should_skip(state, TASK_PROFILE, (source.content_hash,), params_fingerprint({})):
            return state, None

        manifest = load_manifest("a2_profiler", self._manifest_dir)
        scope = dispatcher.issue_scope(TASK_PROFILE, manifest, now=now)
        agent = ProfilerAgent(self._settings, self._manifest_dir, llm=self._llm)
        result = dispatcher.dispatch(
            agent, scope, input_refs=(source,), instruction="Mo ta du lieu staging.", now=now
        )
        verdict = verify(result, manifest, scope, attempts=1)
        audit.record(
            "VALIDATION_RESULT",
            now=now,
            task_id=TASK_PROFILE,
            agent_id="a2_profiler",
            status=verdict.decision,
            detail={"reasons": list(verdict.reasons)},
        )
        state = self._record(
            state,
            states,
            TASK_PROFILE,
            result,
            (source.content_hash,),
            params_fingerprint({}),
            now,
        )
        return state, result

    def _propose(
        self,
        state: RunState,
        states: StateStore,
        dispatcher: Dispatcher,
        source: DataRef,
        now: datetime,
    ) -> tuple[RunState, TaskResult | None]:
        """Ask A3 for a proposal without letting it clean anything."""
        manifest = load_manifest("a3_cleaner", self._manifest_dir)
        scope = dispatcher.issue_scope(TASK_CLEAN, manifest, now=now)
        agent = CleanerAgent(self._settings, self._manifest_dir, llm=self._llm)
        result = dispatcher.dispatch(
            agent, scope, input_refs=(source,), instruction="De xuat rule lam sach.", now=now
        )
        state = state.with_task(
            TaskState(
                task_id=TASK_CLEAN,
                agent_id="a3_cleaner",
                phase="AWAITING_APPROVAL",
                attempts=1,
                input_hashes=(source.content_hash,),
                metrics=result.metrics,
                updated_at=now,
            ),
            now=now,
        )
        states.save(state)
        return state, result

    def _clean(
        self,
        state: RunState,
        states: StateStore,
        dispatcher: Dispatcher,
        source: DataRef,
        approved: list[dict[str, object]],
        now: datetime,
    ) -> tuple[RunState, TaskResult | None]:
        """Run A3 with the approved rules, unless it already succeeded.

        "Already succeeded" has to mean succeeded *at this*. Someone who goes
        back to the gate, approves a different set of rules and resumes is asking
        for the data to be cleaned differently; skipping here would hand them the
        previous cleaning without a word.
        """
        params: dict[str, object] = {APPROVED_RULES_PARAM: approved}
        fingerprint = params_fingerprint(params)
        if should_skip(state, TASK_CLEAN, (source.content_hash,), fingerprint):
            return state, None

        manifest = load_manifest("a3_cleaner", self._manifest_dir)
        scope = dispatcher.issue_scope(TASK_CLEAN, manifest, params=params, now=now)
        agent = CleanerAgent(self._settings, self._manifest_dir, llm=self._llm)
        result = dispatcher.dispatch(
            agent, scope, input_refs=(source,), instruction="Chay rule da duyet.", now=now
        )
        state = self._record(
            state, states, TASK_CLEAN, result, (source.content_hash,), fingerprint, now
        )
        return state, result

    def _record(
        self,
        state: RunState,
        states: StateStore,
        task_id: str,
        result: TaskResult,
        input_hashes: tuple[str, ...],
        params_hash: str,
        now: datetime,
    ) -> RunState:
        """Write one task outcome into the state, immediately."""
        previous = state.task(task_id)
        attempts = (previous.attempts if previous else 0) + 1
        phase = "OK" if result.is_ok else result.status
        updated = state.with_task(
            TaskState(
                task_id=task_id,
                agent_id=result.agent_id,
                phase=phase,  # type: ignore[arg-type]
                attempts=attempts,
                input_hashes=input_hashes,
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

    def _write_gate(
        self,
        gates: GateStore,
        run_id: str,
        result: TaskResult | None,
        now: datetime,
    ) -> GateRequest:
        """Turn a proposal into a gate a person can answer."""
        proposal = (result.payload.get("proposal") if result else None) or {}
        rules = [rule for rule in (proposal.get("rules") or []) if isinstance(rule, dict)]
        # The scope travels beside the proposal, so a person is shown what the
        # rule will touch rather than what the model meant by it.
        scope = (result.payload.get("rule_scope") if result else None) or None
        options = rule_options(rules, scope)

        request = GateRequest(
            gate_id=GATE_RULES,
            run_id=run_id,
            task_id=TASK_CLEAN,
            agent_id="a3_cleaner",
            title="HUMAN GATE 1 - duyet rule lam sach",
            question="Rule nao duoc phep chay? Chi rule duoc duyet moi duoc thuc thi.",
            options=options,
            payload=gate_payload(proposal),
            created_at=now,
        )
        gates.write(request)
        return request
