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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Protocol

from pydantic import BaseModel, ValidationError

from analysis_system.services import storage
from analysis_system.services.audit import AuditLog
from analysis_system.services.budget import BudgetTracker
from analysis_system.services.pii import assert_no_pii

DEFAULT_MAX_TOKENS: Final[int] = 4_000
FINGERPRINT_LENGTH: Final[int] = 16


class LlmError(RuntimeError):
    """A model call could not be completed."""


class CassetteMissingError(LlmError):
    """No recorded answer exists for this exact request."""


class HandoffPendingError(LlmError):
    """The prompt was written out and is waiting for a human to answer it."""


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
        budget: BudgetTracker | None = None,
        client: Any | None = None,
    ) -> None:
        """Bind the provider to one model and, optionally, a budget guard."""
        self._model = model
        self._budget = budget
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
            BudgetExceeded: this call would cross a ceiling.
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
        if self._budget is not None:
            self._budget.record_call(self._model, tokens_in=tokens_in, tokens_out=tokens_out)

        return LlmResponse(
            data=parsed,
            provider=self.name,
            model=self._model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )


class LlmClient:
    """The only way the rest of the system talks to a model.

    It runs the PII guard before every call, so no provider can skip it - not
    even a future one.
    """

    def __init__(self, provider: LlmProvider, *, audit: AuditLog | None = None) -> None:
        """Wrap one provider."""
        self._provider = provider
        self._audit = audit

    @property
    def provider_name(self) -> str:
        """Which provider is in use."""
        return self._provider.name

    def complete(self, request: LlmRequest) -> LlmResponse:
        """Send one request, after proving it carries no personal data.

        Raises:
            PiiLeakError: the prompt still contains something identifiable.
        """
        assert_no_pii(request.system)
        assert_no_pii(request.prompt)
        response = self._provider.complete(request)
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
