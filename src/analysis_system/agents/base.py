"""BaseAgent: where the three boundary layers are actually applied.

Every agent subclasses this and implements execute(). It never calls preflight
or postcheck itself, and it never receives a filesystem path - only a
ScopedStorage bound to the token it was given.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import ClassVar

from analysis_system.contracts.base import ErrorDetail, TaskRequest, TaskResult
from analysis_system.services.boundary import (
    BoundaryViolation,
    Manifest,
    load_manifest,
    postcheck,
    preflight,
)
from analysis_system.services.llm import (
    CassetteMissingError,
    HandoffPendingError,
    LlmError,
    RateLimitedError,
    TransientLlmError,
)
from analysis_system.services.scoped_storage import ScopedStorage
from analysis_system.settings import Settings

# Agents are forbidden from importing pathlib - the AST guard enforces it -
# so the harness exports the one type they need to accept a manifest directory.
ManifestDir = Path | None


class BaseAgent(ABC):
    """An agent that can only act inside the boundary its manifest declares."""

    agent_id: ClassVar[str] = ""

    def __init__(self, settings: Settings, manifest_dir: Path | None = None) -> None:
        """Load the manifest that defines this boundary.

        Raises:
            ValueError: the subclass did not declare an agent_id.
        """
        if not self.agent_id:
            raise ValueError(f"{type(self).__name__} phai khai bao agent_id.")
        self._settings = settings
        self._manifest = load_manifest(self.agent_id, manifest_dir)

    @property
    def manifest(self) -> Manifest:
        """The boundary this agent runs inside."""
        return self._manifest

    @abstractmethod
    def execute(self, request: TaskRequest, files: ScopedStorage) -> TaskResult:
        """Do the work. Called only after pre-flight has passed."""

    def run(self, request: TaskRequest, *, now: datetime | None = None) -> TaskResult:
        """Run one task through all three boundary layers.

        Returns:
            The result, or a BOUNDARY_VIOLATION result when any layer refuses.
            A refusal is always returned as a value, never raised past here, so
            the Manager can record it and decide what happens next.
        """
        try:
            preflight(request.scope, self._manifest, now=now)
        except BoundaryViolation as violation:
            return self._violation(request, "PREFLIGHT", str(violation))

        files = ScopedStorage(request.scope, self._settings)
        try:
            result = self.execute(request, files)
        except BoundaryViolation as violation:
            return self._violation(request, "RUNTIME", str(violation))
        except HandoffPendingError:
            # Not a failure: the run is waiting for a person, and the Manager
            # is the only thing that can decide to pause. Let it through.
            raise
        except LlmError as error:
            return self._model_failed(request, error)

        problems = postcheck(result, self._manifest, request.scope)
        if problems:
            return self._violation(request, "POSTCHECK", "; ".join(problems))
        return result

    def _model_failed(self, request: TaskRequest, error: LlmError) -> TaskResult:
        """Report a model failure as a result the Manager can act on.

        Whether to try again is decided here because only here is it known what
        kind of failure it was. A missing cassette will be missing next time
        too; a rate limit will not.
        """
        retry_after = getattr(error, "retry_after_s", None)
        retryable = not isinstance(error, CassetteMissingError)
        code = (
            "LLM_RATE_LIMITED"
            if isinstance(error, RateLimitedError)
            else "LLM_UNAVAILABLE"
            if isinstance(error, TransientLlmError)
            else "LLM_FAILED"
        )
        return TaskResult(
            task_id=request.scope.task_id,
            agent_id=self.agent_id,
            status="FAILED",
            error=ErrorDetail(
                code=code,
                message=str(error),
                retryable=retryable,
                retry_after_s=retry_after,
            ),
        )

    def _violation(self, request: TaskRequest, layer: str, message: str) -> TaskResult:
        """Build the result that reports a refused call."""
        return TaskResult(
            task_id=request.scope.task_id,
            agent_id=self.agent_id,
            status="BOUNDARY_VIOLATION",
            error=ErrorDetail(
                code=f"BOUNDARY_{layer}",
                message=message,
                retryable=False,
            ),
        )
