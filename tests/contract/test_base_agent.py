"""BaseAgent tests: proving each of the three layers actually stops an agent."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
import yaml

from analysis_system.agents.base import EMPTY_ANSWER_CODE, BaseAgent
from analysis_system.core.scoped_storage import ScopedStorage
from analysis_system.core.settings import LAYER_NAMES, LayerPaths, Settings, load_settings
from analysis_system.models.base import ScopeToken, TaskRequest, TaskResult
from analysis_system.services.llm import (
    CassetteMissingError,
    EmptyAnswerError,
    HandoffPendingError,
    LlmError,
    RateLimitedError,
    TransientLlmError,
)

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)

MANIFEST = {
    "agent_id": "t9_tester",
    "version": 1,
    "description": "Agent gia dung cho test boundary",
    "allow": {
        "read": ["staging://**"],
        "write": ["clean://**"],
        "tools": ["pandas"],
    },
    "limits": {"max_rows_dropped_pct": 5},
    "must_return": {"schema": "TestResult", "required_fields": ["rows_out"]},
}


@pytest.fixture
def manifest_dir(tmp_path: Path) -> Path:
    """A directory holding the fake agent manifest."""
    directory = tmp_path / "manifests"
    directory.mkdir()
    (directory / "t9_tester.yaml").write_text(yaml.safe_dump(MANIFEST), encoding="utf-8")
    return directory


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Real settings with every layer pointed at a throwaway directory."""
    roots = {name: tmp_path / name for name in LAYER_NAMES}
    for root in roots.values():
        root.mkdir(parents=True, exist_ok=True)
    return load_settings().model_copy(update={"layers": LayerPaths(**roots)})


def token(**overrides: object) -> ScopeToken:
    """A token that fits the fake manifest."""
    fields: dict[str, object] = {
        "run_id": "r_test",
        "task_id": "t_01",
        "agent_id": "t9_tester",
        "allow_read": ("staging://**",),
        "allow_write": ("clean://**",),
        "allow_tools": ("pandas",),
        "issued_at": NOW,
        "expires_at": NOW + timedelta(minutes=5),
    }
    fields.update(overrides)
    return ScopeToken(**fields)  # type: ignore[arg-type]


def request_for(scope: ScopeToken) -> TaskRequest:
    """Wrap a token into a task request."""
    return TaskRequest(scope=scope, instruction="ghi mot bang nho")


class WellBehavedAgent(BaseAgent):
    """Writes exactly where it is allowed to."""

    agent_id = "t9_tester"

    def execute(self, request: TaskRequest, files: ScopedStorage) -> TaskResult:
        frame = pd.DataFrame({"x": [1, 2, 3]})
        ref = files.save_parquet(frame, "clean://out.parquet")
        return TaskResult(
            task_id=request.scope.task_id,
            agent_id=self.agent_id,
            status="OK",
            output_refs=(ref,),
            metrics={"rows_out": 3.0},
            payload={"rows_out": 3},
        )


class EscapingAgent(BaseAgent):
    """Tries to write into a layer it was never granted."""

    agent_id = "t9_tester"

    def execute(self, _request: TaskRequest, files: ScopedStorage) -> TaskResult:
        frame = pd.DataFrame({"x": [1]})
        files.save_parquet(frame, "raw://stolen.parquet")
        raise AssertionError("khong duoc chay toi day")


class ForgetfulAgent(BaseAgent):
    """Returns a payload missing a field the manifest requires."""

    agent_id = "t9_tester"

    def execute(self, request: TaskRequest, _files: ScopedStorage) -> TaskResult:
        return TaskResult(
            task_id=request.scope.task_id,
            agent_id=self.agent_id,
            status="OK",
            payload={"khong_phai_rows_out": 3},
        )


class NamelessAgent(BaseAgent):
    """Declares no agent id at all."""

    def execute(self, _request: TaskRequest, _files: ScopedStorage) -> TaskResult:
        raise AssertionError("khong bao gio chay")


def test_a_well_behaved_agent_succeeds(settings: Settings, manifest_dir: Path) -> None:
    agent = WellBehavedAgent(settings, manifest_dir)
    result = agent.run(request_for(token()), now=NOW)
    assert result.is_ok, result.error
    assert result.output_refs[0].path == "clean://out.parquet"
    assert result.output_refs[0].row_count == 3


def test_layer_1_refuses_an_expired_token(settings: Settings, manifest_dir: Path) -> None:
    agent = WellBehavedAgent(settings, manifest_dir)
    result = agent.run(request_for(token()), now=NOW + timedelta(hours=1))
    assert result.status == "BOUNDARY_VIOLATION"
    assert result.error is not None
    assert result.error.code == "BOUNDARY_PREFLIGHT"


def test_layer_1_refuses_a_token_wider_than_the_manifest(
    settings: Settings, manifest_dir: Path
) -> None:
    agent = WellBehavedAgent(settings, manifest_dir)
    result = agent.run(request_for(token(allow_write=("raw://**",))), now=NOW)
    assert result.status == "BOUNDARY_VIOLATION"
    assert result.error is not None
    assert result.error.code == "BOUNDARY_PREFLIGHT"


def test_layer_2_stops_a_write_outside_the_scope(settings: Settings, manifest_dir: Path) -> None:
    agent = EscapingAgent(settings, manifest_dir)
    result = agent.run(request_for(token()), now=NOW)
    assert result.status == "BOUNDARY_VIOLATION"
    assert result.error is not None
    assert result.error.code == "BOUNDARY_RUNTIME"
    # The refused write must not have produced anything.
    assert not (settings.layers.raw / "stolen.parquet").exists()


def test_layer_3_rejects_a_result_missing_a_required_field(
    settings: Settings, manifest_dir: Path
) -> None:
    agent = ForgetfulAgent(settings, manifest_dir)
    result = agent.run(request_for(token()), now=NOW)
    assert result.status == "BOUNDARY_VIOLATION"
    assert result.error is not None
    assert result.error.code == "BOUNDARY_POSTCHECK"
    assert "rows_out" in result.error.message


def test_an_agent_without_an_id_cannot_be_built(settings: Settings, manifest_dir: Path) -> None:
    with pytest.raises(ValueError, match="agent_id"):
        NamelessAgent(settings, manifest_dir)


def test_an_unlisted_tool_is_refused_at_runtime(settings: Settings) -> None:
    files = ScopedStorage(token(), settings)
    files.use_tool("pandas")
    with pytest.raises(Exception, match="shell_exec"):
        files.use_tool("shell_exec")


# --- a model failure is a result, not a traceback ------------------------------


class ModelBreaks(BaseAgent):
    """An agent whose model call fails, in whichever way the test chooses."""

    agent_id = "t9_tester"

    def __init__(self, settings: Settings, manifest_dir: Path, error: Exception) -> None:
        """Carry the failure this agent will raise."""
        super().__init__(settings, manifest_dir)
        self._error = error

    def execute(self, _request: TaskRequest, _files: ScopedStorage) -> TaskResult:
        raise self._error


def break_with(settings: Settings, manifest_dir: Path, error: Exception) -> TaskResult:
    agent = ModelBreaks(settings, manifest_dir, error)
    return agent.run(request_for(token()), now=NOW)


def test_a_rate_limit_becomes_a_retryable_failure(settings: Settings, manifest_dir: Path) -> None:
    # Before this, a 429 from a live API crashed the whole run with a traceback.
    # Nothing about a rate limit deserves that.
    result = break_with(settings, manifest_dir, RateLimitedError("het luot", 46.9))
    assert result.status == "FAILED"
    assert result.error is not None
    assert result.error.code == "LLM_RATE_LIMITED"
    assert result.error.retryable
    assert result.error.retry_after_s == 46.9


def test_a_bad_minute_at_the_provider_is_retryable(settings: Settings, manifest_dir: Path) -> None:
    result = break_with(settings, manifest_dir, TransientLlmError("qua tai"))
    assert result.error is not None
    assert result.error.code == "LLM_UNAVAILABLE"
    assert result.error.retryable
    assert result.error.retry_after_s is None


def test_a_model_answering_the_wrong_shape_is_worth_one_more_try(
    settings: Settings, manifest_dir: Path
) -> None:
    # Models are not deterministic; the next answer may well fit.
    result = break_with(settings, manifest_dir, LlmError("sai khuon"))
    assert result.error is not None
    assert result.error.code == "LLM_FAILED"
    assert result.error.retryable


def test_an_empty_answer_is_its_own_retryable_failure(
    settings: Settings, manifest_dir: Path
) -> None:
    # Ma rieng de vong chay chuyen sang model du phong ngay luot sau.
    result = break_with(settings, manifest_dir, EmptyAnswerError("rong"))
    assert result.error is not None
    assert result.error.code == EMPTY_ANSWER_CODE
    assert result.error.retryable


def test_a_missing_cassette_is_not_worth_retrying(settings: Settings, manifest_dir: Path) -> None:
    # It will be missing next time too.
    result = break_with(settings, manifest_dir, CassetteMissingError("khong co ban ghi"))
    assert result.error is not None
    assert not result.error.retryable


def test_a_prompt_waiting_for_a_person_is_not_a_failure(
    settings: Settings, manifest_dir: Path
) -> None:
    # Only the Manager can decide to pause, so this one goes past the agent.
    with pytest.raises(HandoffPendingError):
        break_with(settings, manifest_dir, HandoffPendingError("dang cho nguoi tra loi"))
