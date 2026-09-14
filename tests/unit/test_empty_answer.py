"""Model tra ve rong: nhan ra dung loai, va luot sau sang model du phong ngay."""

from __future__ import annotations

from typing import Any

from analysis_system.agents.base import EMPTY_ANSWER_CODE
from analysis_system.contracts.base import ErrorDetail, TaskResult
from analysis_system.manager.dag_runner import (
    ATTEMPTS_BEFORE_FALLBACK,
    after_empty_answer,
    choose_model,
)
from analysis_system.services.boundary import LlmPolicy
from analysis_system.services.llm import said_nothing

# Dung hinh phan hoi that cua gpt-oss-20b qua OpenRouter, 2026-09-15.
THOUGHT_ONLY: dict[str, Any] = {
    "choices": [
        {
            "finish_reason": "stop",
            "message": {"role": "assistant", "content": None, "reasoning": "We need SQL..."},
        }
    ]
}


def failed(code: str) -> TaskResult:
    return TaskResult(
        task_id="t1",
        agent_id="a4_transformer",
        status="FAILED",
        error=ErrorDetail(code=code, message="x", retryable=True),
    )


def test_a_reply_with_only_reasoning_said_nothing() -> None:
    assert said_nothing(THOUGHT_ONLY)
    assert said_nothing({"choices": [{"message": {"content": "   "}}]})
    gemini_thought = {"candidates": [{"content": {"parts": [{"text": "...", "thought": True}]}}]}
    assert said_nothing(gemini_thought)


def test_a_reply_with_any_text_is_not_empty() -> None:
    # Sai dinh dang la chuyen khac: hoi lai kem gop y van co ich.
    assert not said_nothing({"choices": [{"message": {"content": "day la van xuoi"}}]})
    assert not said_nothing({"candidates": [{"content": {"parts": [{"text": "{}"}]}}]})
    assert not said_nothing({"output": "hinh dang la"})
    assert not said_nothing("chuoi")


def test_an_empty_first_answer_sends_the_next_attempt_to_the_fallback() -> None:
    policy = LlmPolicy(model="chinh", fallback=("du_phong",))
    skipped = after_empty_answer(1, 0, failed(EMPTY_ANSWER_CODE))
    assert choose_model(policy, 2 + skipped) == "du_phong"


def test_other_failures_keep_the_primary_for_its_second_turn() -> None:
    policy = LlmPolicy(model="chinh", fallback=("du_phong",))
    skipped = after_empty_answer(1, 0, failed("LINEAGE_INVALID"))
    assert skipped == 0
    assert choose_model(policy, 2 + skipped) == "chinh"


def test_an_empty_answer_from_the_fallback_moves_on_without_going_back() -> None:
    skipped = after_empty_answer(1, 0, failed(EMPTY_ANSWER_CODE))
    skipped = after_empty_answer(2, skipped, failed(EMPTY_ANSWER_CODE))
    assert 3 + skipped > ATTEMPTS_BEFORE_FALLBACK + 1
