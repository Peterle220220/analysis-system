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
from typing import Final, Literal

from analysis_system.contracts.base import ScopeToken, TaskResult
from analysis_system.core.boundary import Manifest, postcheck

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
    ceiling = max_retries if max_retries is not None else retry_ceiling(manifest, scope)

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

    thrown_out = mostly_thrown_out(result)
    if thrown_out:
        if attempts < ceiling:
            return Verdict("RETRY", thrown_out)
        # Het luot thu thi di tiep voi phan con lai, KHONG chan ca lan chay.
        # Mot phan cau tra loi van hon mot trang loi - va nhung cau bi nem di
        # deu duoc ghi lai va hien ra, nen khong co gi bi giau.
        return Verdict("PASS")

    return Verdict("PASS")


# Cap so tung agent ghi lai: bao nhieu cai giu, bao nhieu cai bi nem.
KEPT_AND_DROPPED: Final[tuple[tuple[str, str], ...]] = (
    ("claims", "claims_rejected"),
    ("findings", "findings_rejected"),
)


def mostly_thrown_out(result: TaskResult) -> tuple[str, ...]:
    """Lý do thử lại khi lớp kiểm duyệt ném đi nhiều hơn giữ lại.

    Một lần chạy thật giữ 1 kết luận và ném đi 5, rồi trả về OK và đi tiếp như
    thể không có gì xảy ra. Ba trong năm cái bị ném là **nói sai nhóm nào cao
    nhất** - loại sai mà chỉ cần bảo model nó sai chỗ nào là lần sau sửa được.

    Ngưỡng là "ném nhiều hơn giữ", không phải "ném cái nào cũng thử lại": một
    câu lạc đề trong sáu câu là chuyện bình thường, và thử lại vì nó là đốt
    tiền cho một thứ không hỏng.

    Returns:
        Lý do, để chuyển thẳng vào `RetryFeedback`. Rỗng nghĩa là không cần thử
        lại.
    """
    for kept_key, dropped_key in KEPT_AND_DROPPED:
        kept = result.metrics.get(kept_key)
        dropped = result.metrics.get(dropped_key)
        if kept is None or dropped is None or dropped <= kept:
            continue
        reasons = [
            str(line) for line in (result.payload.get("rejected") or []) if str(line).strip()
        ]
        head = (
            f"lop kiem duyet nem di {int(dropped)} ket luan va chi giu {int(kept)} - "
            "hay viet lai nhung cau bi nem, dung nhung cau da duoc giu"
        )
        return (head, *reasons)
    return ()


def retry_ceiling(manifest: Manifest, scope: ScopeToken) -> int:
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
