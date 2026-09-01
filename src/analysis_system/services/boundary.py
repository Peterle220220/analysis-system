"""Boundary enforcement: the manifest is the only source of truth about limits.

Three layers, as required by the spec:

* **Pre-flight** - before an agent runs, its ScopeToken is checked against the
  manifest. A token that grants more than the manifest allows, or has expired,
  stops the call before any work happens.
* **Runtime** - every read, write and tool use is authorised against the token
  while the agent runs.
* **Post-check** - the returned TaskResult is checked against what the manifest
  says the agent must return and must not exceed.

An honest limitation, stated here and in the README: agents run in the same
process as the Manager, so the runtime layer is a cooperative sandbox rather
than an OS-level one. It is backed by a lint rule and an AST test that stop an
agent from reaching the filesystem behind its back.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Final

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from analysis_system.contracts.base import URI_SEPARATOR, ScopeToken, TaskResult

DEFAULT_MANIFEST_DIR: Final[Path] = Path(__file__).resolve().parents[3] / "config" / "manifests"


class BoundaryViolation(RuntimeError):
    """An agent tried to do something its manifest or token does not allow."""


class ManifestError(RuntimeError):
    """A manifest file is missing or malformed."""


class LlmPolicy(BaseModel):
    """What the agent may use an LLM for, if anything."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = False
    purpose: str = ""
    max_sample_rows: int = 0


class ManifestAllow(BaseModel):
    """Everything the agent is permitted to touch."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    read: tuple[str, ...] = ()
    write: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    llm: LlmPolicy = LlmPolicy()


class MustReturn(BaseModel):
    """The shape of the payload the agent has to hand back."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    schema_name: str = Field(alias="schema")
    required_fields: tuple[str, ...] = ()


class HumanGate(BaseModel):
    """When a human has to approve before the run continues."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    required: bool = False
    at: str = ""
    approve: str = ""
    condition: str = ""


class HaltCondition(BaseModel):
    """A metric value that must stop the run rather than be passed downstream.

    Declared by the agent that measures it. A validator that reports a failure
    which nothing acts on is decoration, and putting the rule in the Manager
    instead would hide it inside code nobody reads when asking what stops a run.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    metric: str
    above: float = 0.0
    reason: str = ""

    def triggered_by(self, metrics: Mapping[str, float]) -> bool:
        """True when the measured value crosses the declared line."""
        value = metrics.get(self.metric)
        return value is not None and value > self.above

    def describe(self, metrics: Mapping[str, float]) -> str:
        """Why the run is stopping, in terms of the measurement that stopped it."""
        measured = metrics.get(self.metric, 0.0)
        detail = f"{self.metric}={measured:g} (nguong: > {self.above:g})"
        return f"{self.reason} [{detail}]" if self.reason else detail


class Manifest(BaseModel):
    """One agent boundary, loaded from config/manifests/<agent_id>.yaml."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_id: str
    version: int
    description: str = ""
    allow: ManifestAllow = ManifestAllow()
    deny: tuple[str, ...] = ()
    limits: dict[str, Any] = Field(default_factory=dict)
    must_return: MustReturn | None = None
    human_gate: HumanGate = HumanGate()
    # Measurements that stop the run outright. Nothing downstream may consume a
    # result that crossed one of these.
    halt_on: tuple[HaltCondition, ...] = ()
    on_violation: str = "HALT_AND_ESCALATE"


def load_manifest(agent_id: str, directory: Path | None = None) -> Manifest:
    """Read and validate one agent manifest.

    Raises:
        ManifestError: the file is missing, unreadable, or does not validate.
    """
    root = directory or DEFAULT_MANIFEST_DIR
    path = root / f"{agent_id}.yaml"
    if not path.is_file():
        raise ManifestError(f"Khong tim thay manifest cua agent {agent_id!r}: {path}")
    try:
        parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ManifestError(f"Khong doc duoc manifest {path}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ManifestError(f"Manifest {path} phai la mot mapping YAML.")
    try:
        manifest = Manifest.model_validate(parsed)
    except ValidationError as exc:
        raise ManifestError(f"Manifest {path} khong hop le:\n{exc}") from exc
    if manifest.agent_id != agent_id:
        raise ManifestError(
            f"Manifest {path} khai bao agent_id={manifest.agent_id!r}, khong khop {agent_id!r}."
        )
    return manifest


def _compile(pattern: str) -> re.Pattern[str]:
    """Translate a layer glob into a regular expression.

    ``**`` crosses directory separators, ``*`` does not, and ``?`` is a single
    character. Doing this explicitly matters: fnmatch lets ``*`` cross ``/``,
    which would quietly widen every pattern in every manifest.
    """
    out: list[str] = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if pattern.startswith("**", index):
            out.append(".*")
            index += 2
        elif char == "*":
            out.append("[^/]*")
            index += 1
        elif char == "?":
            out.append("[^/]")
            index += 1
        else:
            out.append(re.escape(char))
            index += 1
    return re.compile("^" + "".join(out) + "$")


def uri_matches(pattern: str, uri: str) -> bool:
    """True when a layer URI falls inside a manifest pattern."""
    pattern_layer, _, pattern_path = pattern.partition(URI_SEPARATOR)
    uri_layer, _, uri_path = uri.partition(URI_SEPARATOR)
    if not uri_layer or not uri_path or pattern_layer != uri_layer:
        return False
    return bool(_compile(pattern_path).match(uri_path))


def _covered(patterns: tuple[str, ...], uri: str) -> bool:
    """True when at least one pattern covers the URI."""
    return any(uri_matches(pattern, uri) for pattern in patterns)


def preflight(scope: ScopeToken, manifest: Manifest, *, now: datetime | None = None) -> None:
    """Layer 1. Refuse to start when the token does not fit the manifest.

    Raises:
        BoundaryViolation: the token is for another agent, has expired, or grants
            more than the manifest allows.
    """
    if scope.agent_id != manifest.agent_id:
        raise BoundaryViolation(
            f"Token cap cho agent {scope.agent_id!r} nhung manifest la {manifest.agent_id!r}."
        )
    if scope.is_expired(now):
        raise BoundaryViolation(
            f"ScopeToken cua task {scope.task_id!r} da het han luc {scope.expires_at.isoformat()}."
        )
    for pattern in scope.allow_read:
        if not _within(pattern, manifest.allow.read):
            raise BoundaryViolation(
                f"Token cho doc {pattern!r} nhung manifest cua {manifest.agent_id} khong cho."
            )
    for pattern in scope.allow_write:
        if not _within(pattern, manifest.allow.write):
            raise BoundaryViolation(
                f"Token cho ghi {pattern!r} nhung manifest cua {manifest.agent_id} khong cho."
            )
    for tool in scope.allow_tools:
        if tool not in manifest.allow.tools:
            raise BoundaryViolation(
                f"Token cho dung tool {tool!r} nhung manifest cua {manifest.agent_id} khong cho."
            )


def _within(granted: str, allowed: tuple[str, ...]) -> bool:
    """True when a granted pattern is covered by the manifest patterns.

    A pattern is covered when it matches one of the allowed patterns literally,
    or when everything it can address also falls inside an allowed pattern. The
    second case is approximated by matching the granted pattern as if it were a
    concrete URI, which is exact for the ``layer://prefix/**`` shape manifests use.
    """
    if granted in allowed:
        return True
    return _covered(allowed, granted)


def authorise_read(scope: ScopeToken, uri: str) -> None:
    """Layer 2. Raise unless the token allows reading this URI."""
    if not _covered(scope.allow_read, uri):
        raise BoundaryViolation(
            f"Agent {scope.agent_id!r} doc {uri!r} ngoai pham vi duoc cap: {list(scope.allow_read)}"
        )


def authorise_write(scope: ScopeToken, uri: str) -> None:
    """Layer 2. Raise unless the token allows writing this URI."""
    if not _covered(scope.allow_write, uri):
        raise BoundaryViolation(
            f"Agent {scope.agent_id!r} ghi {uri!r} ngoai pham vi duoc cap: "
            f"{list(scope.allow_write)}"
        )


def authorise_tool(scope: ScopeToken, tool: str) -> None:
    """Layer 2. Raise unless the token allows this tool."""
    if tool not in scope.allow_tools:
        raise BoundaryViolation(
            f"Agent {scope.agent_id!r} dung tool {tool!r} khong nam trong {list(scope.allow_tools)}"
        )


def postcheck(result: TaskResult, manifest: Manifest, scope: ScopeToken) -> list[str]:
    """Layer 3. Report every way the result breaks its contract.

    Returns:
        A list of problems. An empty list means the result may be accepted.
    """
    problems: list[str] = []

    # A failed task legitimately has no payload; demanding one would turn every
    # honest failure into a boundary violation and hide the real cause.
    if manifest.must_return is not None and result.status == "OK":
        for field in manifest.must_return.required_fields:
            if field not in result.payload:
                problems.append(f"payload thieu truong bat buoc {field!r}")

    for ref in result.output_refs:
        if not _covered(scope.allow_write, ref.path):
            problems.append(f"ghi ra {ref.path!r} ngoai pham vi duoc cap")

    # A conclusion must be traceable to data this agent was allowed to see
    # (criterion S4). Checked here as contract only - whether the file exists is
    # a separate question, answered separately, so neither check covers for the
    # other going wrong.
    for evidence in result.evidence:
        if not _covered(scope.allow_read, evidence.source):
            problems.append(f"dan nguon {evidence.source!r} ngoai pham vi duoc doc")

    # Limits are checked only against a result claiming success. An agent that
    # already reported FAILED has stopped itself, and relabelling that as a
    # boundary violation would replace a precise reason with a vague one.
    if result.status != "OK":
        return problems

    limit = manifest.limits.get("max_rows_dropped_pct")
    measured = result.metrics.get("rows_dropped_pct")
    if isinstance(limit, int | float) and measured is not None and measured > float(limit):
        problems.append(f"bo {measured:.2f}% so dong, vuot tran {float(limit):.2f}%")

    token_limit = manifest.limits.get("max_tokens")
    tokens = result.metrics.get("tokens_total")
    if isinstance(token_limit, int | float) and tokens is not None and tokens > float(token_limit):
        problems.append(f"dung {tokens:.0f} token, vuot tran {float(token_limit):.0f}")

    return problems
