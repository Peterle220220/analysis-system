"""Loi goi le (soan nhap chu giai) thu model du phong, va noi bang loi khi tat ca deu hong.

Truoc day mot model bi gioi han luot goi (gemma-3-12b, HTTP 429) la het: trang hien
nguyen van "OpenRouter tra ve loi HTTP 429: {...}".
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from analysis_system.services.llm import (
    AllModelsFailedError,
    CassetteMissingError,
    EmptyAnswerError,
    LlmClient,
    LlmError,
    LlmRequest,
    LlmResponse,
    RateLimitedError,
    TransientLlmError,
)
from analysis_system.settings import load_settings


class Answer(BaseModel):
    text: str


REQUEST = LlmRequest(purpose="thu", system="he thong", prompt="cau hoi", schema=Answer)


class Scripted:
    """Provider gia: moi model tra loi, hoac hong, dung theo kich ban."""

    name = "scripted"

    def __init__(self, script: dict[str, object], model: str, calls: list[str]) -> None:
        self._script = script
        self.model = model
        self._calls = calls

    def with_model(self, model: str) -> Scripted:
        return Scripted(self._script, model, self._calls)

    def complete(self, _request: LlmRequest) -> LlmResponse:
        self._calls.append(self.model)
        outcome = self._script[self.model]
        if isinstance(outcome, Exception):
            raise outcome
        return LlmResponse(data=Answer(text=str(outcome)), provider=self.name, model=self.model)


def client(script: dict[str, object], calls: list[str]) -> LlmClient:
    return LlmClient(Scripted(script, "chinh", calls))


def test_a_rate_limited_model_hands_over_to_the_fallback() -> None:
    calls: list[str] = []
    script: dict[str, object] = {"chinh": RateLimitedError("429", 30.0), "du_phong": "xong"}
    answer = client(script, calls).complete_with_fallback(REQUEST, ["du_phong"])
    assert answer.model == "du_phong"
    assert calls == ["chinh", "du_phong"]


def test_when_every_model_fails_the_reason_is_said_in_words() -> None:
    script: dict[str, object] = {
        "chinh": RateLimitedError("OpenRouter tra ve loi HTTP 429: {...}", 46.9),
        "hai": EmptyAnswerError("rong"),
        "ba": TransientLlmError("qua tai"),
        "bon": LlmError("OpenRouter tra ve loi HTTP 400:\n{raw}"),
    }
    with pytest.raises(AllModelsFailedError) as failed:
        client(script, []).complete_with_fallback(REQUEST, ["hai", "ba", "bon"])
    said = str(failed.value)
    assert said.startswith("Đã thử 4 model")
    assert "chinh đang bị nhà cung cấp giới hạn lượt gọi" in said
    assert "hai trả về rỗng" in said
    assert "ba tạm thời không trả lời được" in said
    assert "bon báo lỗi (OpenRouter tra ve loi HTTP 400:)" in said
    assert said.endswith("Thử lại sau khoảng 47 giây.")
    assert "{raw}" not in said


def test_the_same_model_is_not_asked_twice() -> None:
    calls: list[str] = []
    script: dict[str, object] = {"chinh": TransientLlmError("x"), "du_phong": "xong"}
    client(script, calls).complete_with_fallback(REQUEST, ["chinh", "du_phong", "du_phong"])
    assert calls == ["chinh", "du_phong"]


def test_a_missing_recording_is_not_passed_to_another_model() -> None:
    # Mot cassette thieu thi thieu voi moi model; hoi tiep chi giau loi that.
    calls: list[str] = []
    script: dict[str, object] = {"chinh": CassetteMissingError("thieu"), "du_phong": "xong"}
    with pytest.raises(CassetteMissingError):
        client(script, calls).complete_with_fallback(REQUEST, ["du_phong"])
    assert calls == ["chinh"]


def test_the_configuration_names_a_fallback_other_than_the_default() -> None:
    llm = load_settings().llm
    assert llm.openrouter_fallback
    assert llm.openrouter_model not in llm.openrouter_fallback
