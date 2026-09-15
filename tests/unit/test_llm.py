"""LLM tests: three providers, one interface, and a PII guard nobody can skip."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from analysis_system.core.budget import (
    BudgetTracker,
    load_budget,
    load_pricing,
)
from analysis_system.core.pii import PiiLeakError
from analysis_system.domains.ai_planner.llm import (
    AnthropicProvider,
    CassetteMissingError,
    CassetteProvider,
    HandoffPendingError,
    HandoffProvider,
    LlmClient,
    LlmError,
    LlmRequest,
    LlmResponse,
)


class RuleProposal(BaseModel):
    """The shape an A3 rule proposal must take."""

    rules: list[str]
    reason: str


def make_request(prompt: str = "Cot amount co 12 gia tri khong ep duoc ve so.") -> LlmRequest:
    """A request with no personal data in it."""
    return LlmRequest(
        purpose="a3_propose_rules",
        system="Ban de xuat rule lam sach. Chi tra ve JSON.",
        prompt=prompt,
        schema=RuleProposal,
    )


# --- request identity ---------------------------------------------------------


def test_the_same_question_always_has_the_same_fingerprint() -> None:
    assert make_request().fingerprint() == make_request().fingerprint()


def test_changing_the_prompt_by_one_character_asks_a_new_question() -> None:
    # Otherwise a reworded prompt would silently replay the old answer.
    assert make_request("a").fingerprint() != make_request("b").fingerprint()


# --- cassette -----------------------------------------------------------------


def test_a_recorded_answer_is_replayed(tmp_path: Path) -> None:
    provider = CassetteProvider(tmp_path)
    request = make_request()
    provider.record(
        request,
        LlmResponse(
            data=RuleProposal(rules=["trim_whitespace"], reason="co khoang trang thua"),
            provider="anthropic",
            model="claude-sonnet-5",
            tokens_in=1200,
            tokens_out=300,
        ),
    )
    replayed = provider.complete(request)
    assert isinstance(replayed.data, RuleProposal)
    assert replayed.data.rules == ["trim_whitespace"]
    assert replayed.tokens_in == 1200


def test_replay_is_identical_every_time(tmp_path: Path) -> None:
    # This is what lets the golden tests stay reproducible with a model in the loop.
    provider = CassetteProvider(tmp_path)
    request = make_request()
    provider.record(
        request,
        LlmResponse(
            data=RuleProposal(rules=["cast_numeric_safe"], reason="x"),
            provider="anthropic",
            model="claude-sonnet-5",
        ),
    )
    first = provider.complete(request)
    second = provider.complete(request)
    assert first.data.model_dump() == second.data.model_dump()


def test_a_missing_recording_says_exactly_which_file_to_create(tmp_path: Path) -> None:
    with pytest.raises(CassetteMissingError) as error:
        CassetteProvider(tmp_path).complete(make_request())
    assert "a3_propose_rules" in str(error.value)


def test_a_recording_that_breaks_the_schema_is_rejected(tmp_path: Path) -> None:
    request = make_request()
    path = tmp_path / f"{request.slug}.json"
    path.write_text(json.dumps({"data": {"rules": "khong phai list"}}), encoding="utf-8")
    with pytest.raises(LlmError, match="khong dung khuon"):
        CassetteProvider(tmp_path).complete(request)


# --- handoff ------------------------------------------------------------------


def test_the_first_call_writes_the_question_and_pauses(tmp_path: Path) -> None:
    provider = HandoffProvider(tmp_path)
    request = make_request()
    with pytest.raises(HandoffPendingError) as error:
        provider.complete(request)
    written = provider.request_path(request)
    assert written.is_file()
    assert str(provider.answer_path(request)) in str(error.value)


def test_the_handoff_directory_is_created_if_it_does_not_exist(tmp_path: Path) -> None:
    # Found by running the CLI for real: the run directory exists but the
    # handoff subdirectory does not, and storage refuses to create it.
    missing = tmp_path / "runs" / "r_1" / "handoff"
    assert not missing.exists()
    provider = HandoffProvider(missing)
    with pytest.raises(HandoffPendingError):
        provider.complete(make_request())
    assert provider.request_path(make_request()).is_file()


def test_the_cassette_directory_is_created_on_record(tmp_path: Path) -> None:
    provider = CassetteProvider(tmp_path / "chua" / "ton" / "tai")
    request = make_request()
    provider.record(
        request,
        LlmResponse(data=RuleProposal(rules=[], reason="x"), provider="test", model="test"),
    )
    assert provider.path_for(request).is_file()


def test_the_written_question_carries_everything_a_person_needs(tmp_path: Path) -> None:
    provider = HandoffProvider(tmp_path)
    request = make_request()
    with pytest.raises(HandoffPendingError):
        provider.complete(request)
    text = provider.request_path(request).read_text(encoding="utf-8")
    assert request.system in text
    assert request.prompt in text
    assert "json" in text.lower()
    assert "RuleProposal" in text or "rules" in text


def test_the_pasted_answer_is_used_on_the_next_call(tmp_path: Path) -> None:
    provider = HandoffProvider(tmp_path)
    request = make_request()
    with pytest.raises(HandoffPendingError):
        provider.complete(request)
    provider.answer_path(request).write_text(
        json.dumps({"rules": ["trim_whitespace"], "reason": "nguoi duyet dan vao"}),
        encoding="utf-8",
    )
    answered = provider.complete(request)
    assert answered.data.rules == ["trim_whitespace"]  # type: ignore[attr-defined]
    assert answered.provider == "handoff"


def test_an_answer_for_the_wrong_question_says_exactly_that(tmp_path: Path) -> None:
    # Hit for real: the A2 answer was pasted into the A3 answer file, and the
    # raw pydantic dump gave no hint what had actually happened.
    provider = HandoffProvider(tmp_path)
    request = make_request()
    provider.answer_path(request).write_text(
        json.dumps({"column_meanings": {}, "pii_columns": [], "observations": []}),
        encoding="utf-8",
    )
    with pytest.raises(LlmError) as error:
        provider.complete(request)
    message = str(error.value)
    assert "MOT CAU HOI KHAC" in message
    assert "a3_propose_rules" in message


def test_a_missing_required_key_is_named(tmp_path: Path) -> None:
    provider = HandoffProvider(tmp_path)
    request = make_request()
    provider.answer_path(request).write_text(
        json.dumps({"reason": "thieu rules"}), encoding="utf-8"
    )
    with pytest.raises(LlmError) as error:
        provider.complete(request)
    assert "Thieu khoa bat buoc" in str(error.value)


def test_an_answer_file_with_a_stray_extension_is_pointed_out(tmp_path: Path) -> None:
    # Hit for real: VS Code saved the answer as ...answer.json.md and the run
    # just said "still waiting", with no hint that the file was right there.
    provider = HandoffProvider(tmp_path)
    request = make_request()
    wrong = provider.answer_path(request).with_suffix(".json.md")
    wrong.write_text('{"rules": [], "reason": "x"}', encoding="utf-8")
    with pytest.raises(HandoffPendingError) as error:
        provider.complete(request)
    assert "SAI TEN" in str(error.value)
    assert wrong.name in str(error.value)


def test_an_answer_pasted_inside_a_markdown_fence_is_accepted(tmp_path: Path) -> None:
    # This is how Claude normally returns JSON, so it is how a person will paste it.
    provider = HandoffProvider(tmp_path)
    request = make_request()
    provider.answer_path(request).write_text(
        '```json\n{"rules": ["trim_whitespace"], "reason": "dan kem fence"}\n```\n',
        encoding="utf-8",
    )
    assert provider.complete(request).data.rules == ["trim_whitespace"]  # type: ignore[attr-defined]


def test_an_answer_that_is_not_json_says_so_plainly(tmp_path: Path) -> None:
    provider = HandoffProvider(tmp_path)
    request = make_request()
    provider.answer_path(request).write_text("Chao ban, day la de xuat cua toi:", encoding="utf-8")
    with pytest.raises(LlmError, match="JSON"):
        provider.complete(request)


def test_a_pasted_answer_that_breaks_the_schema_is_rejected(tmp_path: Path) -> None:
    provider = HandoffProvider(tmp_path)
    request = make_request()
    provider.answer_path(request).write_text(
        json.dumps({"reason": "thieu rules"}), encoding="utf-8"
    )
    with pytest.raises(LlmError, match="khong dung khuon"):
        provider.complete(request)


# --- anthropic ----------------------------------------------------------------


class FakeUsage:
    """Stands in for the usage block the SDK returns."""

    input_tokens = 1_500
    output_tokens = 400


class FakeMessages:
    """Records what the provider sent to the SDK."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def parse(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return type(
            "Parsed",
            (),
            {
                "parsed_output": RuleProposal(rules=["trim_whitespace"], reason="tu model"),
                "usage": FakeUsage(),
            },
        )()


class FakeClient:
    """A stand-in for anthropic.Anthropic()."""

    def __init__(self) -> None:
        self.messages = FakeMessages()


def test_the_api_provider_asks_the_sdk_to_enforce_the_schema() -> None:
    client = FakeClient()
    provider = AnthropicProvider("claude-sonnet-5", client=client)
    request = make_request()
    answered = provider.complete(request)

    sent = client.messages.calls[0]
    assert sent["model"] == "claude-sonnet-5"
    assert sent["output_format"] is RuleProposal
    assert sent["system"] == request.system
    assert answered.tokens_in == 1_500
    assert answered.tokens_out == 400


def budget_guard() -> BudgetTracker:
    """A tracker built from the committed ceilings and prices."""
    root = Path(__file__).resolve().parents[2] / "config"
    return BudgetTracker(
        load_budget(root / "budget.yaml"),
        load_pricing(root / "pricing.yaml"),
        started_at=datetime(2026, 8, 31, tzinfo=UTC),
    )


class CountlessProvider:
    """Answers, reports what it used, and keeps no accounts of its own."""

    name = "countless"

    def complete(self, request: LlmRequest) -> LlmResponse:
        return LlmResponse(
            # Shape does not matter here; what is being tested is the counting.
            data=request.schema.model_construct(),
            provider=self.name,
            model="claude-sonnet-5",
            tokens_in=200,
            tokens_out=100,
        )


def test_the_client_counts_what_a_call_cost() -> None:
    guard = budget_guard()
    client = LlmClient(AnthropicProvider("claude-sonnet-5", client=FakeClient()), budget=guard)
    client.complete(make_request())
    assert guard.tokens_total == 1_900
    assert guard.cost_usd > 0


def test_a_provider_that_counts_nothing_itself_is_still_counted() -> None:
    # This is why the counting moved out of the providers. A scripted or
    # replayed provider does no accounting of its own, and the ceiling used to
    # stop applying entirely - silently.
    guard = budget_guard()
    LlmClient(CountlessProvider(), budget=guard).complete(make_request())
    assert guard.tokens_total == 300


def test_without_a_budget_the_client_simply_does_not_count() -> None:
    # Counting is optional; skipping it must not be an error.
    answer = LlmClient(CountlessProvider()).complete(make_request())
    assert answer.tokens_total == 300


# --- the guard that wraps every provider --------------------------------------


def test_the_client_refuses_to_send_unmasked_personal_data(tmp_path: Path) -> None:
    client = LlmClient(CassetteProvider(tmp_path))
    leaky = LlmRequest(
        purpose="a3_propose_rules",
        system="Ban de xuat rule.",
        prompt="Nguoi ban lien he qua ban@vendor.com",
        schema=RuleProposal,
    )
    with pytest.raises(PiiLeakError):
        client.complete(leaky)


def test_a_masked_request_passes_the_guard(tmp_path: Path) -> None:
    provider = CassetteProvider(tmp_path)
    request = make_request("Nguoi ban lien he qua <EMAIL_1>")
    provider.record(
        request,
        LlmResponse(
            data=RuleProposal(rules=[], reason="khong can lam sach"),
            provider="cassette",
            model="recorded",
        ),
    )
    assert LlmClient(provider).complete(request).data.rules == []  # type: ignore[attr-defined]
