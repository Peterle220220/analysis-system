"""Issues scope tokens and calls agents, writing the audit trail as it goes.

The Manager never opens a data file. It sees DataRef values - path, hash, row
count - and metrics, and nothing else. That constraint lives here: the
dispatcher passes references to an agent and reads references back.

Tokens are always derived from the manifest, never assembled by hand. That makes
a token that grants more than the manifest allows impossible to issue in the
first place, rather than something pre-flight has to catch later.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Final

from analysis_system.agents.base import BaseAgent
from analysis_system.contracts.base import (
    DataRef,
    Limits,
    ScopeToken,
    TaskRequest,
    TaskResult,
)
from analysis_system.core.audit import AuditLog
from analysis_system.core.boundary import Manifest
from analysis_system.core.budget import BudgetExceeded, BudgetTracker

DEFAULT_TOKEN_TTL_S: Final[int] = 300


class Dispatcher:
    """Hands work to agents under a token cut from their own manifest."""

    def __init__(
        self,
        run_id: str,
        audit: AuditLog,
        *,
        budget: BudgetTracker | None = None,
        token_ttl_s: int = DEFAULT_TOKEN_TTL_S,
    ) -> None:
        """Bind the dispatcher to one run."""
        self._run_id = run_id
        self._audit = audit
        self._budget = budget
        self._ttl = token_ttl_s

    def issue_scope(
        self,
        task_id: str,
        manifest: Manifest,
        *,
        params: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> ScopeToken:
        """Cut a token from the manifest and record that it was issued.

        The token can never be wider than the manifest, because it is built from
        it. Narrowing is done by passing explicit params, never by widening.
        """
        moment = now or datetime.now(UTC)
        token = ScopeToken(
            run_id=self._run_id,
            task_id=task_id,
            agent_id=manifest.agent_id,
            allow_read=manifest.allow.read,
            allow_write=manifest.allow.write,
            allow_tools=manifest.allow.tools,
            params=params or {},
            limits=_limits_from(manifest),
            issued_at=moment,
            expires_at=moment + timedelta(seconds=self._ttl),
        )
        self._audit.record(
            "SCOPE_ISSUED",
            now=moment,
            task_id=task_id,
            agent_id=manifest.agent_id,
            detail={
                "allow_read": list(token.allow_read),
                "allow_write": list(token.allow_write),
                "allow_tools": list(token.allow_tools),
                "expires_at": token.expires_at.isoformat(),
            },
        )
        return token

    def dispatch(
        self,
        agent: BaseAgent,
        scope: ScopeToken,
        *,
        input_refs: tuple[DataRef, ...] = (),
        instruction: str = "",
        now: datetime | None = None,
    ) -> TaskResult:
        """Run one task and write the audit trail around it.

        Returns:
            The agent result, unchanged. Judging it is the verifier job, not
            this one.
        """
        moment = now or datetime.now(UTC)
        self._audit.record(
            "TASK_STARTED",
            now=moment,
            task_id=scope.task_id,
            agent_id=agent.agent_id,
            input_hash=_combined_hash(input_refs),
            detail={"instruction": instruction} if instruction else {},
        )

        if self._budget is not None:
            try:
                self._budget.check_wallclock(moment)
            except BudgetExceeded as exceeded:
                return self._halted(scope, agent, str(exceeded))

        request = TaskRequest(scope=scope, input_refs=input_refs, instruction=instruction)
        result = agent.run(request, now=moment)

        event = "BOUNDARY_VIOLATION" if result.status == "BOUNDARY_VIOLATION" else "TASK_COMPLETED"
        self._audit.record(
            event,  # type: ignore[arg-type]
            now=datetime.now(UTC),
            task_id=scope.task_id,
            agent_id=agent.agent_id,
            status=result.status,
            input_hash=_combined_hash(input_refs),
            output_hash=_combined_hash(result.output_refs),
            metrics=result.metrics,
            detail={"error": result.error.message} if result.error else {},
        )
        return result

    def _halted(self, scope: ScopeToken, agent: BaseAgent, message: str) -> TaskResult:
        """Build the result for a task stopped by the budget, and log it."""
        self._audit.record(
            "BUDGET_WARNING",
            task_id=scope.task_id,
            agent_id=agent.agent_id,
            status="HALTED_BUDGET",
            detail={"message": message},
        )
        return TaskResult(
            task_id=scope.task_id,
            agent_id=agent.agent_id,
            status="HALTED_BUDGET",
        )


def _limits_from(manifest: Manifest) -> Limits:
    """Read the per-call ceilings out of a manifest."""
    limits = manifest.limits
    return Limits(
        max_rows_dropped_pct=_number(limits.get("max_rows_dropped_pct")),
        max_runtime_s=_integer(limits.get("max_runtime_s")),
        max_tokens=_integer(limits.get("max_tokens")),
        max_retries=_integer(limits.get("max_retries")) or 3,
    )


def _number(value: object) -> float | None:
    """Read a float limit, ignoring anything that is not numeric."""
    return float(value) if isinstance(value, int | float) else None


def _integer(value: object) -> int | None:
    """Read an integer limit, ignoring anything that is not numeric."""
    return int(value) if isinstance(value, int | float) else None


def _combined_hash(refs: tuple[DataRef, ...]) -> str | None:
    """One hash string standing for a set of references, in a stable order."""
    if not refs:
        return None
    return ",".join(sorted(ref.content_hash for ref in refs))
