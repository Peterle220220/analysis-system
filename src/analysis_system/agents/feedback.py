"""Reading the rejection from the last attempt, for agents that can act on it.

Only the agents whose work is judged by shape need this: A4 writes SQL a guard
may refuse, A7 writes claims a check may reject, A8 writes a summary that may
carry a typed digit. Each of them can do better on a second attempt if told what
was wrong - and can do no better at all if not told.
"""

from __future__ import annotations

from typing import Any, Final

from analysis_system.contracts.base import RetryFeedback

RETRY_FEEDBACK_PARAM: Final[str] = "retry_feedback"


def feedback_from(params: dict[str, Any]) -> RetryFeedback | None:
    """The rejection from the previous attempt, if this is one.

    A malformed value is treated as absent rather than fatal: feedback is a help
    to the next attempt, never a precondition for it.
    """
    raw = params.get(RETRY_FEEDBACK_PARAM)
    if not isinstance(raw, dict):
        return None
    try:
        return RetryFeedback.model_validate(raw)
    except Exception:  # noqa: BLE001 - unusable feedback is simply no feedback
        return None


def as_prompt_fields(feedback: RetryFeedback | None) -> dict[str, Any]:
    """The part of the question that says what went wrong last time.

    Empty when this is a first attempt, so the prompt - and therefore the
    request fingerprint - is unchanged in the ordinary case.
    """
    if feedback is None:
        return {}
    return {
        "attempt": f"{feedback.attempt + 1}/{feedback.max_attempts}",
        "previous_answer": feedback.previous_answer,
        "rejected_because": list(feedback.rejected_because),
    }


RETRY_RULE: Final[str] = (
    "Cau tra loi truoc cua ban DA BI LOAI vi ly do ghi o 'rejected_because'. "
    "Sua dung nhung cho do, dung lap lai cung loi."
)
