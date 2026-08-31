"""Contract tests: a malformed exchange must be rejected, never repaired."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from analysis_system.contracts.base import (
    DataRef,
    ErrorDetail,
    EvidenceRef,
    Limits,
    ScopeToken,
    TaskRequest,
    TaskResult,
)

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)


def make_token(**overrides: object) -> ScopeToken:
    """A valid token, with fields overridable per test."""
    fields: dict[str, object] = {
        "run_id": "r_0001",
        "task_id": "t_01",
        "agent_id": "a3_cleaner",
        "allow_read": ("staging://**",),
        "allow_write": ("clean://**",),
        "allow_tools": ("rulebook.apply",),
        "limits": Limits(max_rows_dropped_pct=5.0),
        "issued_at": NOW,
        "expires_at": NOW + timedelta(minutes=5),
    }
    fields.update(overrides)
    return ScopeToken(**fields)  # type: ignore[arg-type]


def make_ref(path: str = "clean://events.parquet") -> DataRef:
    """A minimal valid data reference."""
    return DataRef(path=path, format="parquet", content_hash="a" * 64, row_count=10)


def test_a_valid_token_round_trips() -> None:
    token = make_token()
    assert ScopeToken.model_validate(token.model_dump()) == token


def test_a_token_must_expire_after_it_is_issued() -> None:
    with pytest.raises(ValidationError):
        make_token(expires_at=NOW)


def test_an_expired_token_reports_itself_as_expired() -> None:
    token = make_token()
    assert not token.is_expired(NOW)
    assert token.is_expired(NOW + timedelta(minutes=6))


def test_a_token_cannot_grant_a_system_path() -> None:
    with pytest.raises(ValidationError):
        make_token(allow_write=("/home/phongle/analysis-data/clean/**",))


def test_a_token_cannot_grant_an_absolute_path_inside_a_layer() -> None:
    with pytest.raises(ValidationError):
        make_token(allow_read=("staging:///etc/passwd",))


def test_a_token_is_frozen_so_an_agent_cannot_widen_it() -> None:
    token = make_token()
    with pytest.raises(ValidationError):
        token.allow_write = ("raw://**",)


def test_a_data_ref_must_use_a_layer_uri() -> None:
    with pytest.raises(ValidationError):
        DataRef(path="/tmp/events.parquet", format="parquet", content_hash="x")


def test_a_data_ref_exposes_its_layer() -> None:
    assert make_ref("mart://po/summary.parquet").layer == "mart"


def test_evidence_must_point_at_a_layer_uri() -> None:
    with pytest.raises(ValidationError):
        EvidenceRef(source="somewhere", locator="row=3", value="12")


def test_a_successful_result_may_not_carry_an_error() -> None:
    with pytest.raises(ValidationError):
        TaskResult(
            task_id="t_01",
            agent_id="a3_cleaner",
            status="OK",
            error=ErrorDetail(code="X", message="loi"),
        )


def test_a_failed_result_must_explain_itself() -> None:
    with pytest.raises(ValidationError):
        TaskResult(task_id="t_01", agent_id="a3_cleaner", status="FAILED")


def test_a_boundary_violation_must_explain_itself() -> None:
    with pytest.raises(ValidationError):
        TaskResult(task_id="t_01", agent_id="a3_cleaner", status="BOUNDARY_VIOLATION")


def test_an_unknown_status_is_rejected() -> None:
    with pytest.raises(ValidationError):
        TaskResult(task_id="t_01", agent_id="a3_cleaner", status="ALMOST_OK")  # type: ignore[arg-type]


def test_an_unexpected_field_is_rejected_rather_than_ignored() -> None:
    with pytest.raises(ValidationError):
        TaskResult(
            task_id="t_01",
            agent_id="a3_cleaner",
            status="OK",
            khong_co_truong_nay=1,  # type: ignore[call-arg]
        )


def test_a_request_carries_references_never_the_data() -> None:
    request = TaskRequest(
        scope=make_token(),
        input_refs=(make_ref("staging://events.parquet"),),
        instruction="lam sach theo rule da duyet",
    )
    dumped = request.model_dump()
    assert dumped["input_refs"][0]["path"] == "staging://events.parquet"
    assert "rows" not in dumped["input_refs"][0]


def test_a_successful_result_reports_is_ok() -> None:
    result = TaskResult(
        task_id="t_01",
        agent_id="a3_cleaner",
        status="OK",
        output_refs=(make_ref(),),
        metrics={"rows_in": 1000.0, "rows_out": 998.0},
    )
    assert result.is_ok
    assert result.metrics["rows_out"] == 998.0
