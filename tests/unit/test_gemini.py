"""Gemini provider tests: the transport is faked, the contract is not.

What is being pinned down here is everything except the network - the request
body, how an answer is found in a reply whose shape the vendor controls, and
what happens when the answer does not fit the schema. The one live call is a
separate script, because a test that needs an API key is not a test.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from analysis_system.contracts.agents import ProfileInterpretation, SqlProposal
from analysis_system.services.llm import (
    GEMINI_KEY_ENV,
    GeminiProvider,
    LlmError,
    LlmRequest,
)

# Long enough to pass the shape check - the code refuses anything that plainly
# cannot be a key, which caught the eight-character placeholder this used to use.
FAKE_KEY = "AQ." + "t" * 45

SQL_ANSWER = {
    "sql": "SELECT city FROM houses",
    "target_table": "mart",
    "lineage": [{"output": "city", "sources": ["city"], "transform": "giu nguyen"}],
    "reason": "thu",
}


def request(schema: type = SqlProposal) -> LlmRequest:
    return LlmRequest(
        purpose="a4_transformer_sql",
        system="ban la mot tro ly",
        prompt='{"question": "gia theo thanh pho"}',
        schema=schema,
    )


class Transport:
    """Stands in for the network. Records what it was asked, returns what it was told."""

    def __init__(self, reply: Any) -> None:
        self._reply = reply
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self, url: str, headers: dict[str, str], body: dict[str, Any], timeout: int
    ) -> Any:
        self.calls.append({"url": url, "headers": headers, "body": body, "timeout": timeout})
        if isinstance(self._reply, Exception):
            raise self._reply
        return self._reply


def provider(reply: Any, **kwargs: Any) -> tuple[GeminiProvider, Transport]:
    transport = Transport(reply)
    return GeminiProvider(api_key=FAKE_KEY, transport=transport, **kwargs), transport


# --- the request that goes out -------------------------------------------------


def test_the_answer_shape_is_declared_in_the_request() -> None:
    # The model is constrained by the schema, not asked politely to comply.
    engine, transport = provider({"output_text": json.dumps(SQL_ANSWER)})
    engine.complete(request())
    schema = transport.calls[0]["body"]["response_format"]["schema"]
    assert "sql" in schema["properties"]
    assert transport.calls[0]["body"]["response_format"]["mime_type"] == "application/json"


def test_the_key_travels_in_the_header_not_the_url() -> None:
    # A key in a query string ends up in logs and proxy caches.
    engine, transport = provider({"output_text": json.dumps(SQL_ANSWER)})
    engine.complete(request())
    assert transport.calls[0]["headers"]["x-goog-api-key"] == FAKE_KEY
    assert FAKE_KEY not in transport.calls[0]["url"]


def test_both_halves_of_the_question_are_sent() -> None:
    engine, transport = provider({"output_text": json.dumps(SQL_ANSWER)})
    engine.complete(request())
    sent = transport.calls[0]["body"]["input"]
    assert "ban la mot tro ly" in sent
    assert "gia theo thanh pho" in sent


def test_the_configured_model_is_the_one_asked_for() -> None:
    engine, transport = provider({"output_text": json.dumps(SQL_ANSWER)}, model="gemini-thu-nghiem")
    answer = engine.complete(request())
    assert transport.calls[0]["body"]["model"] == "gemini-thu-nghiem"
    assert answer.model == "gemini-thu-nghiem"


def test_a_free_form_dictionary_survives_the_round_trip() -> None:
    # Column names are not known until the data is seen, so this field cannot be
    # a fixed set of properties. If the vendor ever stops accepting it, this
    # test is where it shows.
    reply = {"output_text": json.dumps({"column_meanings": {"case_id": "ma don hang"}})}
    engine, transport = provider(reply)
    answer = engine.complete(request(ProfileInterpretation))
    schema = transport.calls[0]["body"]["response_format"]["schema"]
    assert schema["properties"]["column_meanings"]["additionalProperties"] == {"type": "string"}
    assert isinstance(answer.data, ProfileInterpretation)
    assert answer.data.column_meanings == {"case_id": "ma don hang"}


# --- finding the answer in a reply we do not control ---------------------------


@pytest.mark.parametrize(
    "reply",
    [
        {"output_text": json.dumps(SQL_ANSWER)},
        {"output": {"text": json.dumps(SQL_ANSWER)}},
        {"candidates": [{"content": {"parts": [{"text": json.dumps(SQL_ANSWER)}]}}]},
        {"la_mot_khoa_la": [{"noi_dung": json.dumps(SQL_ANSWER)}]},
    ],
)
def test_the_answer_is_found_wherever_the_vendor_puts_it(reply: dict[str, Any]) -> None:
    # Field names move between API versions. Hard-coding one path would break
    # silently on the next release.
    engine, _ = provider(reply)
    assert isinstance(engine.complete(request()).data, SqlProposal)


def test_a_fenced_answer_is_accepted() -> None:
    fenced = "```json\n" + json.dumps(SQL_ANSWER) + "\n```"
    engine, _ = provider({"output_text": fenced})
    assert isinstance(engine.complete(request()).data, SqlProposal)


def test_a_reply_with_no_answer_in_it_reports_the_whole_reply() -> None:
    # So a shape change is diagnosable in one run instead of guessed at.
    engine, _ = provider({"error": {"message": "khong hieu"}})
    with pytest.raises(LlmError, match="khong hieu"):
        engine.complete(request())


# --- what is refused -----------------------------------------------------------


def test_an_answer_that_misses_the_schema_is_rejected_not_patched() -> None:
    engine, _ = provider({"output_text": json.dumps({"khong": "dung khuon"})})
    with pytest.raises(LlmError, match="khong dung khuon SqlProposal"):
        engine.complete(request())


def test_a_missing_key_says_exactly_how_to_get_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(GEMINI_KEY_ENV, raising=False)
    engine = GeminiProvider(transport=Transport({}))
    with pytest.raises(LlmError, match="aistudio.google.com"):
        engine.complete(request())


def test_the_key_is_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(GEMINI_KEY_ENV, FAKE_KEY)
    transport = Transport({"output_text": json.dumps(SQL_ANSWER)})
    GeminiProvider(transport=transport).complete(request())
    assert transport.calls[0]["headers"]["x-goog-api-key"] == FAKE_KEY


def test_the_provider_names_itself() -> None:
    engine, _ = provider({"output_text": json.dumps(SQL_ANSWER)})
    assert engine.complete(request()).provider == "gemini"


# --- what it cost --------------------------------------------------------------


def test_token_counts_are_read_when_the_reply_reports_them() -> None:
    reply = {
        "output_text": json.dumps(SQL_ANSWER),
        "usage": {"input_tokens": 120, "output_tokens": 45},
    }
    engine, _ = provider(reply)
    answer = engine.complete(request())
    assert (answer.tokens_in, answer.tokens_out) == (120, 45)


def test_a_reply_without_token_counts_is_not_an_error() -> None:
    # Not knowing what it cost is worth recording as zero, not worth failing on.
    engine, _ = provider({"output_text": json.dumps(SQL_ANSWER)})
    assert engine.complete(request()).tokens_total == 0


# --- a key that cannot work says so, in terms that can be acted on -------------


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("khoacokytutiengviet" + "\u0111" + "x" * 40, "khong phai ASCII"),
        ("co khoang trang " + "x" * 40, "khoang trang"),
        ("ngan", "ngoai khoang hop ly"),
        ("x" * 500, "ngoai khoang hop ly"),
    ],
)
def test_an_unusable_key_is_reported_before_anything_leaves(key: str, expected: str) -> None:
    # Otherwise it surfaces as a UnicodeEncodeError from inside urllib, which
    # says nothing about what to fix. This is a real paste accident, not a
    # hypothetical one.
    transport = Transport({})
    engine = GeminiProvider(api_key=key, transport=transport)
    with pytest.raises(LlmError, match=expected):
        engine.complete(request())
    assert transport.calls == []


def test_surrounding_whitespace_is_forgiven() -> None:
    # A trailing newline read from a file is not the operator's mistake.
    transport = Transport({"output_text": json.dumps(SQL_ANSWER)})
    GeminiProvider(api_key="  " + "k" * 40 + "\n", transport=transport).complete(request())
    assert transport.calls[0]["headers"]["x-goog-api-key"] == "k" * 40
