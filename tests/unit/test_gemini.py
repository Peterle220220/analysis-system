"""Gemini provider tests: the transport is faked, the contract is not.

What is being pinned down here is everything except the network - the request
body, how an answer is found in a reply whose shape the vendor controls, and
what happens when the answer does not fit the schema. The one live call is a
separate script, because a test that needs an API key is not a test.
"""

from __future__ import annotations

import email.message
import io
import json
import urllib.error
import urllib.request
from typing import Any

import pytest

from analysis_system.domains.ai_planner import llm as llm_module
from analysis_system.domains.ai_planner.llm import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_RETRY_AFTER_S,
    GEMINI_KEY_ENV,
    GeminiProvider,
    LlmError,
    LlmRequest,
    RateLimitedError,
    TransientLlmError,
    post_json,
)
from analysis_system.models.agents import ProfileInterpretation, SqlProposal

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


# --- failures only a live endpoint produces ------------------------------------


def refuse_with(monkeypatch: pytest.MonkeyPatch, code: int, body: str) -> None:
    """Make the next HTTP call fail the way a real service would."""

    def explode(*_args: Any, **_kwargs: Any) -> None:
        raise urllib.error.HTTPError(
            "https://x", code, "loi", email.message.Message(), io.BytesIO(body.encode())
        )

    monkeypatch.setattr(urllib.request, "urlopen", explode)


def test_being_rate_limited_carries_the_waiting_time_the_service_named(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The service knows its own limit. A policy guessing two seconds against a
    # limit measured in minutes just spends its retries faster.
    refuse_with(monkeypatch, 429, '{"error":{"message":"Please retry in 46.9s."}}')
    with pytest.raises(RateLimitedError) as refused:
        post_json("https://x", {}, {}, 5)
    assert refused.value.retry_after_s == pytest.approx(46.9)


def test_a_rate_limit_with_no_stated_delay_still_waits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refuse_with(monkeypatch, 429, "{}")
    with pytest.raises(RateLimitedError) as refused:
        post_json("https://x", {}, {}, 5)
    assert refused.value.retry_after_s == DEFAULT_RETRY_AFTER_S


def test_a_server_having_a_bad_minute_is_transient(monkeypatch: pytest.MonkeyPatch) -> None:
    refuse_with(monkeypatch, 503, "qua tai")
    with pytest.raises(TransientLlmError):
        post_json("https://x", {}, {}, 5)


def test_a_rejected_request_is_not_transient(monkeypatch: pytest.MonkeyPatch) -> None:
    # A 400 will be a 400 again. Waiting changes nothing.
    refuse_with(monkeypatch, 400, "sai tham so")
    with pytest.raises(LlmError) as error:
        post_json("https://x", {}, {}, 5)
    assert not isinstance(error.value, TransientLlmError)


def test_a_read_that_times_out_is_transient(monkeypatch: pytest.MonkeyPatch) -> None:
    # A socket timeout arrives as OSError, not URLError, so it used to escape
    # every handler and crash the run.
    def stall(*_args: Any, **_kwargs: Any) -> None:
        raise TimeoutError("The read operation timed out")

    monkeypatch.setattr(urllib.request, "urlopen", stall)
    with pytest.raises(TransientLlmError, match="qua han"):
        post_json("https://x", {}, {}, 5)


class Trickle:
    """Một câu trả lời đến từng mẩu, như máy chủ gửi khoảng trắng giữ kết nối."""

    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = list(chunks)
        self.reads = 0

    def __enter__(self) -> Trickle:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read1(self, _size: int) -> bytes:
        self.reads += 1
        return self.chunks.pop(0) if self.chunks else b""


def serve(monkeypatch: pytest.MonkeyPatch, reply: Trickle, seconds_per_read: float) -> None:
    """Trả `reply` cho lần gọi tới, mỗi lần đọc làm đồng hồ nhích `seconds_per_read`."""
    ticks = iter(range(10_000))
    monkeypatch.setattr(urllib.request, "urlopen", lambda *_args, **_kwargs: reply)
    monkeypatch.setattr(llm_module, "_clock", lambda: next(ticks) * seconds_per_read)


def test_a_reply_that_trickles_past_its_limit_is_abandoned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Real run: every read arrived inside the socket timeout, so a call with a
    # 420 s limit ran for 13.5 minutes. The limit is for the whole call.
    reply = Trickle([b" "] * 1000)
    serve(monkeypatch, reply, seconds_per_read=2.0)
    with pytest.raises(TransientLlmError, match="van chua xong"):
        post_json("https://x", {}, {}, 5)
    assert reply.reads < 10


def test_a_reply_read_in_pieces_within_its_limit_is_joined(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reply = Trickle([b'{"a": ', "\"Quý 4\"".encode()[:4], "\"Quý 4\"".encode()[4:], b"}"])
    serve(monkeypatch, reply, seconds_per_read=0.0)
    assert post_json("https://x", {}, {}, 5) == {"a": "Quý 4"}


# --- both output limits must be stated -----------------------------------------


def test_the_request_says_how_much_output_it_will_accept() -> None:
    # Leaving this unsaid was a real failure: the model reasoned at length, ran
    # out of budget, and returned an object cut off mid-string.
    engine, transport = provider({"output_text": json.dumps(SQL_ANSWER)})
    engine.complete(request())
    config = transport.calls[0]["body"]["generation_config"]
    assert config["max_output_tokens"] == DEFAULT_MAX_TOKENS
    assert config["thinking_level"] == "low"


def test_how_much_thinking_to_buy_is_configurable() -> None:
    engine, transport = provider({"output_text": json.dumps(SQL_ANSWER)}, thinking="high")
    engine.complete(request())
    assert transport.calls[0]["body"]["generation_config"]["thinking_level"] == "high"


def test_the_usage_names_the_live_endpoint_actually_uses_are_read() -> None:
    # Observed on the wire: total_input_tokens, not input_tokens.
    reply = {
        "output_text": json.dumps(SQL_ANSWER),
        "usage": {"total_input_tokens": 2011, "total_output_tokens": 296},
    }
    engine, _ = provider(reply)
    answer = engine.complete(request())
    assert (answer.tokens_in, answer.tokens_out) == (2011, 296)
