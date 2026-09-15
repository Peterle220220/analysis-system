"""One endpoint, many models, one budget.

The provider is tested through an injected transport, so none of this reaches
the network or spends anything. What is checked is the part that has to be right
before any model comparison is worth running: that the schema goes over the wire,
that a per-skill choice is honoured, and that nine agents on nine models still
answer to a single ceiling.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from analysis_system.core.budget import BudgetTracker, load_budget, load_pricing
from analysis_system.domains.ai_planner.llm import (
    LlmClient,
    LlmError,
    LlmRequest,
    LlmResponse,
    OpenRouterProvider,
)


class Answer(BaseModel):
    """The shape every call here has to come back in."""

    ket_luan: str
    he_so: float


REPO_ROOT = Path(__file__).resolve().parents[2]


def a_budget() -> BudgetTracker:
    """A tracker over the configuration the project actually ships."""
    return BudgetTracker(
        load_budget(REPO_ROOT / "config" / "budget.yaml"),
        load_pricing(REPO_ROOT / "config" / "pricing.yaml"),
        started_at=datetime.now(UTC),
    )


def a_request(purpose: str = "test") -> LlmRequest:
    return LlmRequest(
        system="ban la mot tro ly phan tich",
        prompt="he so la 0.27",
        schema=Answer,
        purpose=purpose,
        max_tokens=500,
    )


class Recorder:
    """A transport that answers correctly and remembers what it was asked."""

    def __init__(self, content: str = '{"ket_luan": "co lien he", "he_so": 0.27}') -> None:
        self.calls: list[dict[str, Any]] = []
        self._content = content

    def __call__(
        self, url: str, headers: dict[str, str], body: dict[str, Any], _timeout: int
    ) -> dict[str, Any]:
        self.calls.append({"url": url, "headers": headers, "body": body})
        return {
            "choices": [{"message": {"content": self._content}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30},
        }


# --- speaking OpenRouter's dialect -------------------------------------------------


def test_the_answer_shape_goes_over_the_wire() -> None:
    """The schema is enforced by whoever serves the model, not hoped for.

    It is still checked again on the way back - a wire-level constraint is a
    first line and never the only one.
    """
    transport = Recorder()
    OpenRouterProvider("some/model", api_key="k" * 40, transport=transport).complete(a_request())

    sent = transport.calls[0]["body"]
    assert sent["model"] == "some/model"
    assert sent["response_format"]["type"] == "json_schema"
    assert sent["response_format"]["json_schema"]["strict"] is True
    assert "he_so" in sent["response_format"]["json_schema"]["schema"]["properties"]


def test_the_system_prompt_and_the_question_stay_apart() -> None:
    transport = Recorder()
    OpenRouterProvider("m", api_key="k" * 40, transport=transport).complete(a_request())
    roles = [message["role"] for message in transport.calls[0]["body"]["messages"]]
    assert roles == ["system", "user"]


def test_the_key_travels_as_a_bearer_token() -> None:
    transport = Recorder()
    OpenRouterProvider("m", api_key="k" * 40, transport=transport).complete(a_request())
    assert transport.calls[0]["headers"]["Authorization"].startswith("Bearer ")


def test_tokens_are_counted_from_an_openai_shaped_reply() -> None:
    """Missing these names would not fail a call - it would report every run free.

    A provider that quietly counts nothing makes the budget ceiling stop
    applying, and that shows up as a bill rather than as a failure.
    """
    reply = OpenRouterProvider("m", api_key="k" * 40, transport=Recorder()).complete(a_request())
    assert reply.tokens_in == 120
    assert reply.tokens_out == 30


def test_an_answer_that_misses_the_shape_is_refused() -> None:
    off_shape = Recorder('{"ket_luan": "thieu he so"}')
    with pytest.raises(LlmError):
        OpenRouterProvider("m", api_key="k" * 40, transport=off_shape).complete(a_request())


def test_a_missing_key_says_where_to_get_one() -> None:
    with pytest.raises(LlmError, match="OPENROUTER_API_KEY"):
        OpenRouterProvider("m", api_key="", transport=Recorder()).complete(a_request())


def test_a_key_that_cannot_be_a_key_is_refused_before_the_call() -> None:
    """Otherwise it surfaces as a UnicodeEncodeError from inside urllib."""
    transport = Recorder()
    with pytest.raises(LlmError, match="khong dung dinh dang"):
        OpenRouterProvider("m", api_key="dan nham ca cau tieng Việt", transport=transport).complete(
            a_request()
        )
    assert transport.calls == [], "khong duoc goi ra ngoai voi mot khoa hong"


# --- one skill, one model ----------------------------------------------------------


def test_switching_model_keeps_everything_else() -> None:
    """The key, endpoint and injected transport carry over.

    Without this a run would start reading the environment again half way
    through, and a test double would fall out from under the second agent.
    """
    transport = Recorder()
    first = OpenRouterProvider("model/a", api_key="k" * 40, transport=transport)
    second = first.with_model("model/b")

    second.complete(a_request())
    assert transport.calls[0]["body"]["model"] == "model/b"
    assert first.model == "model/a", "ban goc khong duoc doi"


def test_a_client_can_be_pointed_at_another_model() -> None:
    client = LlmClient(OpenRouterProvider("model/a", api_key="k" * 40, transport=Recorder()))
    assert client.for_model("model/b").model_name == "model/b"


def test_naming_no_model_leaves_the_client_alone() -> None:
    """A manifest that says nothing must behave exactly as it did before."""
    client = LlmClient(OpenRouterProvider("model/a", api_key="k" * 40, transport=Recorder()))
    assert client.for_model("") is client
    assert client.for_model("model/a") is client


def test_a_provider_that_cannot_switch_is_left_alone() -> None:
    """Handoff and cassette have one source of answers.

    A line of YAML does not change who is pasting into Claude, and pretending
    otherwise would silently ignore the manifest instead of admitting it.
    """

    class OneSource:
        name = "fixed"

        def complete(self, _request: LlmRequest) -> LlmResponse:  # pragma: no cover
            raise AssertionError

    client = LlmClient(OneSource())
    assert client.for_model("model/b") is client


def test_every_model_answers_to_the_same_ceiling() -> None:
    """Nine agents on nine models, one budget.

    A per-agent client that started its own budget would turn one ceiling into
    nine, which is the same as having none - and the bill would arrive before
    the test did.
    """
    budget = a_budget()
    first = LlmClient(
        OpenRouterProvider("model/a", api_key="k" * 40, transport=Recorder()), budget=budget
    )
    second = first.for_model("model/b")

    first.complete(a_request("mot"))
    second.complete(a_request("hai"))

    counted = budget.snapshot()
    assert counted["calls"] == 2, "ca hai model phai cung dem vao mot ngan sach"
    assert counted["tokens_in"] == 240
