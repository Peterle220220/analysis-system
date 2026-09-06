"""LLM access behind one interface, with three interchangeable providers.

The spec draws a hard line: the model decides, code executes. Everything that
crosses that line is a small piece of structured JSON validated against a
Pydantic model, which is what makes the model a replaceable component rather
than something woven through the system.

| Provider    | What it does                                    | Cost |
|-------------|-------------------------------------------------|------|
| `cassette`  | replays a recorded answer                       | none |
| `handoff`   | writes the prompt out for a human to run         | none |
| `anthropic` | calls the API                                    | paid |

`cassette` is what every test uses: an LLM in the loop would make the golden
tests non-reproducible, which would defeat criterion S1. `handoff` runs the real
thing through a Claude subscription with a person relaying the answer - the
human gate the spec already requires makes that a natural fit rather than a
workaround. `anthropic` is the same flow without the person.

Every provider goes through LlmClient, which refuses to send anything that still
looks like personal data.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, Final, Protocol

from pydantic import BaseModel, ValidationError

from analysis_system.services import storage
from analysis_system.services.audit import AuditLog
from analysis_system.services.budget import BudgetTracker
from analysis_system.services.pii import assert_no_pii

# Tran dau ra mac dinh. Doi voi model co suy nghi noi bo, phan nghi tinh CHUNG
# vao day: mot lan chay that tra ve `finish_reason: "length"` va `content: null`
# - model tieu het 4.000 token vao viec can nhac roi bi cat truoc khi viet duoc
# cau tra loi. Khong ai bao duoc gi, chi thay "khong tim thay JSON".
#
# 4.000 la du cho phan TRA LOI; khong du cho phan nghi cong phan tra loi.
DEFAULT_MAX_TOKENS: Final[int] = 16_000
FINGERPRINT_LENGTH: Final[int] = 16

GEMINI_ENDPOINT: Final[str] = "https://generativelanguage.googleapis.com/v1beta/interactions"
OPENROUTER_ENDPOINT: Final[str] = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_KEY_ENV: Final[str] = "OPENROUTER_API_KEY"
# Free, reaches a real model, and returns JSON against a schema - the three
# things this system needs before anything else is worth measuring. Which
# model belongs on which skill is decided by measurement, not by this default.
DEFAULT_OPENROUTER_MODEL: Final[str] = "dots-studio/dots-3-note-preview:free"
# Same value and same reasoning as gemini_thinking: these tasks fill a
# declared shape, and thinking longer spends the output budget that the
# answer itself needs.
DEFAULT_REASONING: Final[str] = "low"
GEMINI_KEY_ENV: Final[str] = "GEMINI_API_KEY"
DEFAULT_GEMINI_MODEL: Final[str] = "gemini-3.7-flash"
DEFAULT_THINKING: Final[str] = "low"
HTTP_TIMEOUT_S: Final[int] = 120
TOO_MANY_REQUESTS: Final[int] = 429
SERVER_ERROR: Final[int] = 500
DEFAULT_RETRY_AFTER_S: Final[float] = 60.0
MIN_KEY_LENGTH: Final[int] = 20
MAX_KEY_LENGTH: Final[int] = 200


class LlmError(RuntimeError):
    """A model call could not be completed."""


class CassetteMissingError(LlmError):
    """No recorded answer exists for this exact request."""


class HandoffPendingError(LlmError):
    """The prompt was written out and is waiting for a human to answer it."""


class TransientLlmError(LlmError):
    """The call failed for a reason that may not be there a minute from now."""


class RateLimitedError(TransientLlmError):
    """The service refused because too many calls were made, and said when to return.

    The waiting time comes from the service, not from a guess here: a policy
    that backs off for two seconds against a limit measured in minutes just
    burns its retries faster.
    """

    def __init__(self, message: str, retry_after_s: float) -> None:
        """Carry how long the service asked to be left alone."""
        super().__init__(message)
        self.retry_after_s = retry_after_s


@dataclass(frozen=True)
class LlmRequest:
    """One question for the model, and the shape the answer must take."""

    purpose: str
    system: str
    prompt: str
    schema: type[BaseModel]
    max_tokens: int = DEFAULT_MAX_TOKENS

    def fingerprint(self) -> str:
        """Stable id for this exact question.

        Cassettes and handoff files are keyed by it, so changing a prompt by one
        character asks for a new answer instead of silently reusing the old one.
        """
        material = "\n".join([self.purpose, self.system, self.prompt, self.schema.__name__]).encode(
            "utf-8"
        )
        return hashlib.sha256(material).hexdigest()[:FINGERPRINT_LENGTH]

    @property
    def slug(self) -> str:
        """Filename stem used by the file-backed providers."""
        return f"{self.purpose}_{self.fingerprint()}"


@dataclass(frozen=True)
class LlmResponse:
    """A validated answer, plus what it cost to get."""

    data: BaseModel
    provider: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0

    @property
    def tokens_total(self) -> int:
        """Every token this call used."""
        return self.tokens_in + self.tokens_out


class LlmProvider(Protocol):
    """Anything that can answer an LlmRequest."""

    name: str

    def complete(self, request: LlmRequest) -> LlmResponse:
        """Answer one request with data validated against the request schema."""
        ...


def strip_fences(text: str) -> str:
    """Remove a surrounding markdown code fence, if the answer arrived in one."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def parse_answer(text: str, source: str) -> dict[str, Any]:
    """Parse a pasted answer, tolerating a markdown fence around it.

    Raises:
        LlmError: the text is not JSON, or is JSON but not an object.
    """
    cleaned = strip_fences(text)
    try:
        loaded = json.loads(cleaned)
    except json.JSONDecodeError as error:
        raise LlmError(
            f"Noi dung tai {source} khong phai JSON hop le: {error}\n"
            "Chi dan phan JSON, khong kem loi giai thich."
        ) from error
    if not isinstance(loaded, dict):
        raise LlmError(f"Noi dung tai {source} phai la mot object JSON.")
    return loaded


def _describe_mismatch(payload: dict[str, Any], request: LlmRequest, source: str) -> str:
    """Explain a schema mismatch in terms a person can act on."""
    expected = set(request.schema.model_fields)
    required = {name for name, field in request.schema.model_fields.items() if field.is_required()}
    found = set(payload)
    lines = [
        f"Cau tra loi tai {source} khong dung khuon {request.schema.__name__}.",
        "",
        f"  Can co khoa : {sorted(expected)}",
        f"  Dang co khoa: {sorted(found)}",
    ]
    if not (found & expected):
        lines += [
            "",
            "  Khong mot khoa nao trung nhau. Rat co the day la cau tra loi cua",
            f"  MOT CAU HOI KHAC bi dan nham vao day. Cau hoi nay la {request.purpose!r} -",
            "  hay mo dung file .request.md tuong ung, dan vao Claude, roi lay JSON moi.",
        ]
    else:
        missing = sorted(required - found)
        extra = sorted(found - expected)
        if missing:
            lines.append(f"  Thieu khoa bat buoc: {missing}")
        if extra:
            lines.append(f"  Thua khoa khong duoc phep: {extra}")
    return "\n".join(lines)


def _validate(payload: dict[str, Any], request: LlmRequest, source: str) -> BaseModel:
    """Validate raw JSON against the schema the request demands.

    Raises:
        LlmError: the answer does not fit the schema. It is rejected outright
            rather than patched up, exactly as the Manager rejects a malformed
            TaskResult.
    """
    try:
        return request.schema.model_validate(payload)
    except ValidationError as error:
        raise LlmError(f"{_describe_mismatch(payload, request, source)}\n\n{error}") from error


class CassetteProvider:
    """Replays a recorded answer. Free, offline, and perfectly repeatable."""

    name = "cassette"

    def __init__(self, directory: Path, *, model: str = "recorded") -> None:
        """Bind the provider to a directory of recorded answers."""
        self._directory = directory
        self._model = model

    def path_for(self, request: LlmRequest) -> Path:
        """Where the recording for this request lives."""
        return self._directory / f"{request.slug}.json"

    def complete(self, request: LlmRequest) -> LlmResponse:
        """Return the recorded answer.

        Raises:
            CassetteMissingError: nothing has been recorded for this request.
        """
        path = self.path_for(request)
        if not path.is_file():
            raise CassetteMissingError(
                f"Chua co ban ghi cho {request.purpose!r}.\n"
                f"Can tao file: {path}\n"
                f"Noi dung: JSON dung schema {request.schema.__name__}."
            )
        payload = parse_answer(storage.read_text(path), str(path))
        data = payload.get("data", payload)
        return LlmResponse(
            data=_validate(data, request, str(path)),
            provider=self.name,
            model=str(payload.get("model", self._model)),
            tokens_in=int(payload.get("tokens_in", 0)),
            tokens_out=int(payload.get("tokens_out", 0)),
        )

    def record(self, request: LlmRequest, response: LlmResponse) -> Path:
        """Save an answer so later runs can replay it."""
        self._directory.mkdir(parents=True, exist_ok=True)
        payload = {
            "purpose": request.purpose,
            "model": response.model,
            "tokens_in": response.tokens_in,
            "tokens_out": response.tokens_out,
            "data": response.data.model_dump(mode="json"),
        }
        return storage.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            self.path_for(request),
        )


class HandoffProvider:
    """Writes the prompt out for a person to run, then reads the answer back.

    This is the zero-cost path: the prompt goes to Claude through a
    subscription, and the answer comes back as a file. The run pauses in exactly
    the same way it pauses at a human gate, so no new machinery is needed.
    """

    name = "handoff"

    def __init__(self, directory: Path, *, model: str = "claude-pro-handoff") -> None:
        """Bind the provider to the directory used to exchange files."""
        self._directory = directory
        self._model = model

    def request_path(self, request: LlmRequest) -> Path:
        """Where the question is written for the human."""
        return self._directory / f"{request.slug}.request.md"

    def answer_path(self, request: LlmRequest) -> Path:
        """Where the human is expected to paste the answer."""
        return self._directory / f"{request.slug}.answer.json"

    def near_misses(self, request: LlmRequest) -> list[Path]:
        """Files that look like the answer but are not named exactly right.

        The usual cause is an editor appending its own extension, which leaves
        ...answer.json.md sitting next to the name being looked for.
        """
        answer = self.answer_path(request)
        if not self._directory.is_dir():
            return []
        return sorted(
            candidate
            for candidate in self._directory.glob(f"{answer.name}*")
            if candidate != answer
        )

    def complete(self, request: LlmRequest) -> LlmResponse:
        """Return the pasted answer, or write the question and pause.

        Raises:
            HandoffPendingError: no answer file yet. The caller should pause the
                run rather than treat this as a failure.
        """
        answer = self.answer_path(request)
        if answer.is_file():
            payload = parse_answer(storage.read_text(answer), str(answer))
            return LlmResponse(
                data=_validate(payload, request, str(answer)),
                provider=self.name,
                model=self._model,
            )

        close = self.near_misses(request)
        if close:
            names = "\n  ".join(path.name for path in close)
            raise HandoffPendingError(
                f"Tim thay file gan dung nhung SAI TEN:\n  {names}\n\n"
                f"Doi ten thanh dung:\n  {answer.name}\n"
                "(Trinh soan thao thuong tu them duoi .md - hay bo di.)"
            )

        self._directory.mkdir(parents=True, exist_ok=True)
        written = storage.write_text(self._render(request), self.request_path(request))
        raise HandoffPendingError(
            f"Da ghi cau hoi ra: {written}\n"
            f"Mo file do, dan noi dung vao Claude, roi luu JSON tra ve tai:\n  {answer}\n"
            "Sau do chay lai lenh resume."
        )

    def _render(self, request: LlmRequest) -> str:
        """Build the file a person copies into Claude."""
        schema = json.dumps(request.schema.model_json_schema(), ensure_ascii=False, indent=2)
        return "\n".join(
            [
                f"# Yeu cau LLM - {request.purpose}",
                "",
                "Dan TOAN BO phan duoi day vao Claude, roi luu JSON tra ve vao file:",
                f"`{self.answer_path(request).name}`",
                "",
                "Chi tra ve JSON, khong kem giai thich.",
                "",
                "---",
                "",
                "## System",
                "",
                request.system,
                "",
                "## Prompt",
                "",
                request.prompt,
                "",
                "## JSON schema bat buoc",
                "",
                "```json",
                schema,
                "```",
                "",
            ]
        )


class AnthropicProvider:
    """Calls the API. This is the only provider that spends money."""

    name = "anthropic"

    def __init__(
        self,
        model: str,
        *,
        client: Any | None = None,
    ) -> None:
        """Bind the provider to one model.

        It does not count what it spends: LlmClient does that for every
        provider, so no provider can turn the ceiling off by forgetting.
        """
        self._model = model
        self._client = client

    def _ensure_client(self) -> Any:
        """Build the SDK client on first use, so the package stays optional."""
        if self._client is None:
            try:
                import anthropic
            except ImportError as error:  # pragma: no cover - depends on install
                raise LlmError("Chua cai goi anthropic. Cai bang: pip install anthropic") from error
            self._client = anthropic.Anthropic()
        return self._client

    def complete(self, request: LlmRequest) -> LlmResponse:
        """Ask the model, with the answer shape enforced by the SDK.

        Raises:
            LlmError: the call failed or the answer did not fit the schema.
        """
        client = self._ensure_client()
        response = client.messages.parse(
            model=self._model,
            max_tokens=request.max_tokens,
            system=request.system,
            messages=[{"role": "user", "content": request.prompt}],
            output_format=request.schema,
        )
        parsed = response.parsed_output
        if parsed is None:
            raise LlmError(f"Model khong tra ve du lieu dung schema cho {request.purpose!r}.")

        tokens_in = int(getattr(response.usage, "input_tokens", 0))
        tokens_out = int(getattr(response.usage, "output_tokens", 0))
        return LlmResponse(
            data=parsed,
            provider=self.name,
            model=self._model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )


def _first_text(payload: Any) -> str | None:
    """Find the answer text in a response whose exact shape we do not control.

    Providers move fields between versions. Rather than hard-code one path and
    break silently on the next release, this walks the response for the first
    string that parses as a JSON object - and the caller reports the whole
    response when nothing does, so a shape change is diagnosable in one run
    instead of guessed at.
    """
    if isinstance(payload, str):
        candidate = strip_fences(payload)
        if candidate.startswith("{"):
            return candidate
        return None
    if isinstance(payload, dict):
        # Look under the likely carriers first, then everywhere else.
        preferred = ("output_text", "text", "output", "content", "parts", "candidates")
        for key in preferred:
            if key in payload:
                found = _first_text(payload[key])
                if found is not None:
                    return found
        for key, value in payload.items():
            if key not in preferred:
                found = _first_text(value)
                if found is not None:
                    return found
        return None
    if isinstance(payload, list):
        for item in payload:
            found = _first_text(item)
            if found is not None:
                return found
    return None


def _usage_from(payload: dict[str, Any]) -> tuple[int, int]:
    """Token counts, if the response reports them. Absent means zero, not an error."""
    for key in ("usage", "usage_metadata", "usageMetadata"):
        usage = payload.get(key)
        if isinstance(usage, dict):
            reads = (
                "input_tokens",
                "total_input_tokens",
                "inputTokens",
                "prompt_token_count",
                "promptTokenCount",
                # What an OpenAI-shaped reply calls them. Missing these does not
                # fail a call - it silently reports every OpenRouter run as
                # having cost nothing, which is worse than failing.
                "prompt_tokens",
            )
            writes = (
                "output_tokens",
                "total_output_tokens",
                "outputTokens",
                "candidates_token_count",
                "candidatesTokenCount",
                "completion_tokens",
            )
            tokens_in = next((int(usage[name]) for name in reads if name in usage), 0)
            tokens_out = next((int(usage[name]) for name in writes if name in usage), 0)
            return tokens_in, tokens_out
    return 0, 0


def _retry_after(detail: str) -> float:
    """How long the service asked to be left alone.

    Read out of the refusal itself when it says so. When it does not, a minute
    is assumed - long enough to be worth calling a wait, short enough that a
    run is not abandoned over it.
    """
    match = re.search(r"retry in ([0-9.]+)s", detail)
    return float(match.group(1)) if match else DEFAULT_RETRY_AFTER_S


def post_json(
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    timeout_s: int,
    *,
    service: str = "Model",
) -> Any:
    """POST JSON and read JSON back, using only the standard library.

    A second HTTP client would be a dependency bought for one call. The retry
    and backoff this needs already live in the Manager, so there is nothing left
    here for a bigger library to do.

    Args:
        service: whose endpoint this is, for the failure messages. It was
            hard-coded to one vendor while there was only one, which would have
            started blaming Gemini for OpenRouter timeouts the moment a second
            provider used this - and a message that names the wrong service
            sends the reader to the wrong place entirely.

    Raises:
        LlmError: the call failed, or the reply was not JSON.
    """
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    http_request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(http_request, timeout=timeout_s) as reply:  # noqa: S310
            text = reply.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:2000]
        message = f"{service} tra ve loi HTTP {error.code}:\n{detail}"
        if error.code == TOO_MANY_REQUESTS:
            raise RateLimitedError(message, _retry_after(detail)) from error
        if error.code >= SERVER_ERROR:
            raise TransientLlmError(message) from error
        raise LlmError(message) from error
    except urllib.error.URLError as error:
        # A network that is down now may be up in a moment; that is the
        # Manager's call to make, not this function's.
        raise TransientLlmError(f"Khong goi duoc {service}: {error.reason}") from error
    except OSError as error:
        # A read that timed out arrives here rather than as a URLError, and a
        # slow minute is the most transient failure there is.
        raise TransientLlmError(f"Goi {service} qua han sau {timeout_s}s: {error}") from error

    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise LlmError(f"{service} tra ve thu khong phai JSON:\n{text[:2000]}") from error


def _key_problem(key: str) -> str | None:
    """Why this string cannot be an API key, or None when it looks like one.

    Deliberately loose: it rejects what is certainly wrong rather than guessing
    at a vendor format that changes.
    """
    if not key.isascii():
        odd = sorted({character for character in key if not character.isascii()})
        return f"co ky tu khong phai ASCII ({''.join(odd)!r})"
    if any(character.isspace() for character in key):
        return "co khoang trang hoac xuong dong"
    if not MIN_KEY_LENGTH <= len(key) <= MAX_KEY_LENGTH:
        return f"dai {len(key)} ky tu, ngoai khoang hop ly {MIN_KEY_LENGTH}-{MAX_KEY_LENGTH}"
    return None


class GeminiProvider:
    """Calls the Gemini API over plain HTTP.

    Added so the provider abstraction has a second real implementation. Until
    now it served exactly one vendor, which made "vendor independent" a belief
    rather than a demonstrated fact.

    **The free tier trains on what you send it.** That is acceptable for the
    committed fixture, which is a public dataset with a DOI. It is not
    acceptable for client data, and nothing here can enforce that distinction -
    it is a decision the operator makes when choosing the provider.
    """

    name = "gemini"

    def __init__(
        self,
        model: str = DEFAULT_GEMINI_MODEL,
        *,
        api_key: str | None = None,
        endpoint: str = GEMINI_ENDPOINT,
        timeout_s: int = HTTP_TIMEOUT_S,
        thinking: str = DEFAULT_THINKING,
        transport: Any | None = None,
    ) -> None:
        """Bind the provider to one model.

        Args:
            transport: injected for tests - anything callable as
                (url, headers, body, timeout) returning parsed JSON. Left unset,
                the standard library does the call.
        """
        self._model = model
        self._api_key = api_key
        self._endpoint = endpoint
        self._timeout_s = timeout_s
        self._thinking = thinking
        self._transport = transport or partial(post_json, service="Gemini")

    def _key(self) -> str:
        """The API key, checked for shape before it is put in a header.

        Checked here rather than at the HTTP layer because this is where the
        message can still be useful. An unusable key otherwise surfaces as a
        UnicodeEncodeError from inside urllib, which says nothing about what to
        fix.

        Raises:
            LlmError: no key, or something that cannot be a key.
        """
        key = (self._api_key or os.environ.get(GEMINI_KEY_ENV, "")).strip()
        where = (
            f"Dat bien moi truong {GEMINI_KEY_ENV}, hoac ghi vao file .env.\n"
            "Lay khoa mien phi tai: https://aistudio.google.com/apikey"
        )
        if not key:
            raise LlmError(f"Chua co khoa Gemini. {where}")

        problem = _key_problem(key)
        if problem:
            raise LlmError(
                f"Khoa Gemini khong dung dinh dang: {problem}.\n"
                "Rat co the ban da dan nham noi dung khac vao .env - kiem tra file "
                "chi co dung mot dong:\n"
                f"  {GEMINI_KEY_ENV}=<khoa>\n\n{where}"
            )
        return key

    def build_body(self, request: LlmRequest) -> dict[str, Any]:
        """The request body, with the answer shape declared up front.

        The schema goes over the wire, so the model is constrained rather than
        asked politely. An answer that still misses the shape is rejected by
        _validate, the same as for every other provider.
        """
        return {
            "model": self._model,
            "input": f"{request.system}\n\n---\n\n{request.prompt}",
            "response_format": {
                "type": "text",
                "mime_type": "application/json",
                "schema": request.schema.model_json_schema(),
            },
            # Both limits matter, and leaving either unsaid was a real failure:
            # the model reasoned at length, ran out of output budget, and
            # returned an object cut off mid-string.
            "generation_config": {
                "thinking_level": self._thinking,
                "max_output_tokens": request.max_tokens,
            },
        }

    def complete(self, request: LlmRequest) -> LlmResponse:
        """Ask the model, and refuse anything that does not fit the schema.

        Raises:
            LlmError: the call failed, or the answer did not fit the schema.
        """
        headers = {"x-goog-api-key": self._key(), "Content-Type": "application/json"}
        payload = self._transport(
            self._endpoint, headers, self.build_body(request), self._timeout_s
        )

        text = _first_text(payload)
        if text is None:
            raise LlmError(
                f"Khong tim thay cau tra loi JSON trong phan hoi cua Gemini cho "
                f"{request.purpose!r}. Phan hoi day du:\n"
                f"{json.dumps(payload, ensure_ascii=False, indent=2)[:2000]}"
            )

        data = _validate(parse_answer(text, "Gemini"), request, "Gemini")
        tokens_in, tokens_out = _usage_from(payload if isinstance(payload, dict) else {})
        return LlmResponse(
            data=data,
            provider=self.name,
            model=self._model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )


class OpenRouterProvider:
    """One endpoint, several hundred models, chosen per skill.

    This is what makes the team idea real. Until now a run used one model for
    everything; through here the agent that writes SQL can run on a
    code-strong model while the two that write Vietnamese prose run on
    something else, and swapping either is a line of configuration.

    **Free models here trade data for the price.** OpenRouter only routes to a
    free endpoint once the account has enabled *may train on request data* and
    *may publish prompts* - and publishing means a public dataset. That is fine
    for the committed fixture, which is public already. It is not fine for
    client data, and nothing in this code can tell the difference: the paid
    models carry no such condition and cost about $0.002 a question, which is
    the answer for anything real.
    """

    name = "openrouter"

    def __init__(
        self,
        model: str = DEFAULT_OPENROUTER_MODEL,
        *,
        api_key: str | None = None,
        endpoint: str = OPENROUTER_ENDPOINT,
        timeout_s: int = HTTP_TIMEOUT_S,
        reasoning: str = DEFAULT_REASONING,
        transport: Any | None = None,
    ) -> None:
        """Bind the provider to one model.

        Args:
            reasoning: how much internal thinking to ask for. Low, for
                the same reason Gemini is asked for low: these tasks fill
                a declared shape from figures already supplied, and
                whether the answer is any good is decided afterwards by
                code rather than by how long the model thought.
            transport: injected for tests - anything callable as
                (url, headers, body, timeout) returning parsed JSON.
        """
        self._model = model
        self._api_key = api_key
        self._endpoint = endpoint
        self._timeout_s = timeout_s
        self._reasoning = reasoning
        self._transport = transport or partial(post_json, service="OpenRouter")

    @property
    def model(self) -> str:
        """Which model this instance speaks to."""
        return self._model

    def with_model(self, model: str) -> OpenRouterProvider:
        """The same provider settings, pointed at another model.

        The key, endpoint, timeout and injected transport all carry over, so a
        test double stays in place and a run does not start reading the
        environment again half way through.
        """
        return OpenRouterProvider(
            model,
            api_key=self._api_key,
            endpoint=self._endpoint,
            timeout_s=self._timeout_s,
            reasoning=self._reasoning,
            transport=self._transport,
        )

    def _key(self) -> str:
        """The API key, checked for shape before it goes in a header.

        Raises:
            LlmError: no key, or something that cannot be a key.
        """
        key = (self._api_key or os.environ.get(OPENROUTER_KEY_ENV, "")).strip()
        where = (
            f"Dat bien moi truong {OPENROUTER_KEY_ENV}, hoac ghi vao file .env.\n"
            "Lay khoa mien phi tai: https://openrouter.ai/keys"
        )
        if not key:
            raise LlmError(f"Chua co khoa OpenRouter. {where}")

        problem = _key_problem(key)
        if problem:
            raise LlmError(
                f"Khoa OpenRouter khong dung dinh dang: {problem}.\n"
                f"File .env chi nen co dung mot dong:\n"
                f"  {OPENROUTER_KEY_ENV}=<khoa>\n\n{where}"
            )
        return key

    def build_body(self, request: LlmRequest) -> dict[str, Any]:
        """The request body, with the answer shape declared up front.

        `strict` is set, so the schema is enforced by whoever serves the model
        rather than hoped for. An answer that misses the shape anyway is
        refused by _validate, exactly as it is for every other provider - the
        wire-level constraint is a first line, never the only one.
        """
        return {
            "model": self._model,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.prompt},
            ],
            "max_tokens": request.max_tokens,
            # Measured, and the measurement mattered twice over. Left unsaid,
            # one model spent its whole output budget reasoning and returned a
            # sentence cut in half; another overran the cap and emitted its own
            # deliberation as the answer - "Okay, let\'s tackle this problem".
            # Both then scored as unable to produce JSON, which was neither true
            # nor their fault.
            #
            # Asking for `exclude` as well looked obviously right and made
            # things worse: it sometimes left `content` empty altogether, and
            # the best candidate went from 5/5 valid answers to 3/5. Two changes
            # that both read as improvements, pulling opposite ways - only
            # running them separately told them apart.
            "reasoning": {"effort": self._reasoning},
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "answer",
                    "strict": True,
                    "schema": request.schema.model_json_schema(),
                },
            },
        }

    def complete(self, request: LlmRequest) -> LlmResponse:
        """Ask the model, and refuse anything that does not fit the schema.

        Raises:
            LlmError: the call failed, or the answer did not fit the schema.
        """
        headers = {
            "Authorization": f"Bearer {self._key()}",
            "Content-Type": "application/json",
            # OpenRouter asks callers to identify themselves. Sending the
            # project rather than nothing keeps this run distinguishable in the
            # account's own logs.
            "X-Title": "analysis-system",
        }
        payload = self._transport(
            self._endpoint, headers, self.build_body(request), self._timeout_s
        )

        text = _first_text(payload)
        if text is None:
            raise LlmError(
                f"Khong tim thay cau tra loi JSON trong phan hoi cua OpenRouter "
                f"(model {self._model}) cho {request.purpose!r}. Phan hoi day du:\n"
                f"{json.dumps(payload, ensure_ascii=False, indent=2)[:2000]}"
            )

        data = _validate(parse_answer(text, "OpenRouter"), request, "OpenRouter")
        tokens_in, tokens_out = _usage_from(payload if isinstance(payload, dict) else {})
        return LlmResponse(
            data=data,
            provider=self.name,
            model=self._model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )


class LlmClient:
    """The only way the rest of the system talks to a model.

    It runs the PII guard before every call and counts what every call cost, so
    no provider can skip either - not even a future one. Both used to be the
    provider's own business, and a provider that simply did not count made the
    budget ceiling quietly stop applying.
    """

    def __init__(
        self,
        provider: LlmProvider,
        *,
        audit: AuditLog | None = None,
        budget: BudgetTracker | None = None,
    ) -> None:
        """Wrap one provider."""
        self._provider = provider
        self._audit = audit
        self._budget = budget

    @property
    def provider_name(self) -> str:
        """Which provider is in use."""
        return self._provider.name

    @property
    def model_name(self) -> str:
        """Which model is in use, where the provider names one."""
        return str(getattr(self._provider, "model", ""))

    def for_model(self, model: str) -> LlmClient:
        """The same client, pointed at a different model.

        Returns self when the name is empty or the provider cannot switch -
        handoff and cassette have exactly one source of answers, and a line of
        YAML does not change who is pasting into Claude.

        **The budget and the audit log carry over.** A per-agent client that
        started its own budget would turn one ceiling into nine, which is the
        same as having none, and the failure would show up as a bill rather
        than as a test.
        """
        if not model or model == self.model_name:
            return self
        switch = getattr(self._provider, "with_model", None)
        if switch is None:
            return self
        return LlmClient(switch(model), audit=self._audit, budget=self._budget)

    def complete(self, request: LlmRequest) -> LlmResponse:
        """Send one request, after proving it carries no personal data.

        Raises:
            PiiLeakError: the prompt still contains something identifiable.
            BudgetExceeded: this call takes the job past one of its ceilings.
        """
        assert_no_pii(request.system)
        assert_no_pii(request.prompt)
        response = self._provider.complete(request)
        if self._budget is not None:
            # Counted here rather than in the provider, so a provider that
            # forgets cannot turn the ceiling off.
            self._budget.record_call(
                response.model, tokens_in=response.tokens_in, tokens_out=response.tokens_out
            )
        if self._audit is not None:
            self._audit.record(
                "TASK_COMPLETED",
                agent_id=request.purpose,
                status="LLM_OK",
                metrics={
                    "tokens_in": float(response.tokens_in),
                    "tokens_out": float(response.tokens_out),
                },
                detail={"provider": response.provider, "model": response.model},
            )
        return response
