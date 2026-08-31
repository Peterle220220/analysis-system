"""The Manager decision step: PASS, RETRY, REPLAN, ESCALATE, or GATE.

Two rules here are absolute and worth stating plainly.

A boundary violation is **never** retried. Retrying it would mean asking an
agent that just tried to step outside its scope to try again, which is exactly
the wrong response; it goes straight to a human.

A budget halt is **never** retried either. The spec says a job that hits a
ceiling halts and reports, and never continues automatically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from analysis_system.contracts.base import ScopeToken, TaskResult
from analysis_system.services.boundary import Manifest, postcheck

Decision = Literal["PASS", "RETRY", "REPLAN", "ESCALATE", "GATE"]


@dataclass(frozen=True)
class Verdict:
    """What the Manager decided about one result, and why."""

    decision: Decision
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def accepted(self) -> bool:
        """True when the result may be written into the state."""
        return self.decision == "PASS"


def verify(
    result: TaskResult,
    manifest: Manifest,
    scope: ScopeToken,
    *,
    attempts: int,
    max_retries: int | None = None,
) -> Verdict:
    """Decide what happens next after one agent call.

    Args:
        result: what the agent returned. It has already passed contract
            validation, because an invalid result is rejected before reaching here.
        manifest: the boundary the agent runs inside.
        scope: the token the agent was given.
        attempts: how many times this task has run, including this one.
        max_retries: ceiling on retries; taken from the manifest when omitted.

    Returns:
        The verdict. A result is accepted only when it is OK and clean.
    """
    ceiling = max_retries if max_retries is not None else _retry_ceiling(manifest, scope)

    if result.status == "BOUNDARY_VIOLATION":
        return Verdict("ESCALATE", (_error_text(result, "vi pham boundary"),))

    if result.status == "HALTED_BUDGET":
        return Verdict("ESCALATE", (_error_text(result, "cham tran ngan sach"),))

    if result.status == "NEEDS_REVIEW":
        return Verdict("GATE", ("agent yeu cau nguoi duyet truoc khi di tiep",))

    if result.status == "FAILED":
        reason = _error_text(result, "task that bai")
        retryable = result.error is not None and result.error.retryable
        if retryable and attempts < ceiling:
            return Verdict("RETRY", (f"{reason} (lan {attempts}/{ceiling})",))
        if retryable:
            return Verdict("ESCALATE", (f"{reason} - da het {ceiling} lan thu",))
        return Verdict("ESCALATE", (f"{reason} - loi khong the thu lai",))

    problems = postcheck(result, manifest, scope)
    if problems:
        if attempts < ceiling:
            return Verdict("RETRY", tuple(problems))
        return Verdict("ESCALATE", (*problems, f"da het {ceiling} lan thu"))

    return Verdict("PASS")


def _retry_ceiling(manifest: Manifest, scope: ScopeToken) -> int:
    """Retry ceiling from the manifest, falling back to the token limits."""
    declared = manifest.limits.get("max_retries")
    if isinstance(declared, int):
        return declared
    return scope.limits.max_retries


def _error_text(result: TaskResult, fallback: str) -> str:
    """Readable reason from the result error, if it carries one."""
    if result.error is None:
        return fallback
    return f"{fallback}: {result.error.message}"
