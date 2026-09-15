"""Boundary tests, including every negative case the spec requires."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from analysis_system.contracts.base import DataRef, ScopeToken, TaskResult
from analysis_system.core.boundary import (
    BoundaryViolation,
    ManifestError,
    authorise_read,
    authorise_tool,
    authorise_write,
    load_manifest,
    postcheck,
    preflight,
    uri_matches,
)

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
MANIFEST_DIR = Path(__file__).resolve().parents[2] / "config" / "manifests"


def cleaner_token(**overrides: object) -> ScopeToken:
    """A token matching what the a3_cleaner manifest permits."""
    fields: dict[str, object] = {
        "run_id": "r_0001",
        "task_id": "t_03",
        "agent_id": "a3_cleaner",
        "allow_read": ("staging://**",),
        "allow_write": ("clean://**",),
        "allow_tools": ("rulebook.apply",),
        "issued_at": NOW,
        "expires_at": NOW + timedelta(minutes=5),
    }
    fields.update(overrides)
    return ScopeToken(**fields)  # type: ignore[arg-type]


def clean_result(**overrides: object) -> TaskResult:
    """A well formed result from a3_cleaner."""
    fields: dict[str, object] = {
        "task_id": "t_03",
        "agent_id": "a3_cleaner",
        "status": "OK",
        "output_refs": (
            DataRef(path="clean://events.parquet", format="parquet", content_hash="a" * 64),
        ),
        "metrics": {"rows_in": 1000.0, "rows_out": 995.0, "rows_dropped_pct": 0.5},
        "payload": {
            "rows_in": 1000,
            "rows_out": 995,
            "rules_applied": ["trim_whitespace"],
            "diff_log": [],
            "content_hash": "b" * 64,
        },
    }
    fields.update(overrides)
    return TaskResult(**fields)  # type: ignore[arg-type]


# --- manifest loading ---------------------------------------------------------


def test_the_cleaner_manifest_declares_its_boundary() -> None:
    manifest = load_manifest("a3_cleaner", MANIFEST_DIR)
    assert manifest.allow.write == ("clean://**",)
    assert manifest.limits["max_rows_dropped_pct"] == 5
    assert manifest.human_gate.required is True
    assert manifest.must_return is not None
    assert "diff_log" in manifest.must_return.required_fields


def test_a_missing_manifest_is_an_error_not_a_default(tmp_path: Path) -> None:
    with pytest.raises(ManifestError):
        load_manifest("a9_khong_co", tmp_path)


def test_a_manifest_naming_another_agent_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "a3_cleaner.yaml").write_text(
        "agent_id: a2_profiler\nversion: 1\n", encoding="utf-8"
    )
    with pytest.raises(ManifestError):
        load_manifest("a3_cleaner", tmp_path)


# --- pattern semantics --------------------------------------------------------


def test_double_star_crosses_directories_but_single_star_does_not() -> None:
    assert uri_matches("clean://**", "clean://a/b/c.parquet")
    assert not uri_matches("clean://*", "clean://a/b/c.parquet")
    assert uri_matches("clean://*", "clean://c.parquet")


def test_a_pattern_never_matches_across_layers() -> None:
    assert not uri_matches("staging://**", "clean://events.parquet")


# --- layer 1: pre-flight ------------------------------------------------------


def test_preflight_accepts_a_token_that_fits_the_manifest() -> None:
    preflight(cleaner_token(), load_manifest("a3_cleaner", MANIFEST_DIR), now=NOW)


def test_preflight_rejects_a_token_issued_for_another_agent() -> None:
    token = cleaner_token(agent_id="a2_profiler", allow_write=("profile://**",))
    with pytest.raises(BoundaryViolation):
        preflight(token, load_manifest("a3_cleaner", MANIFEST_DIR), now=NOW)


def test_preflight_rejects_an_expired_token() -> None:
    manifest = load_manifest("a3_cleaner", MANIFEST_DIR)
    with pytest.raises(BoundaryViolation) as error:
        preflight(cleaner_token(), manifest, now=NOW + timedelta(minutes=10))
    assert "het han" in str(error.value)


def test_preflight_rejects_a_token_granting_more_than_the_manifest() -> None:
    manifest = load_manifest("a3_cleaner", MANIFEST_DIR)
    with pytest.raises(BoundaryViolation):
        preflight(cleaner_token(allow_write=("raw://**",)), manifest, now=NOW)


def test_preflight_rejects_a_tool_the_manifest_does_not_list() -> None:
    manifest = load_manifest("a3_cleaner", MANIFEST_DIR)
    with pytest.raises(BoundaryViolation):
        preflight(cleaner_token(allow_tools=("shell_exec",)), manifest, now=NOW)


# --- layer 2: runtime ---------------------------------------------------------


def test_writing_outside_the_granted_scope_is_refused() -> None:
    with pytest.raises(BoundaryViolation) as error:
        authorise_write(cleaner_token(), "raw://sample.csv")
    assert "ngoai pham vi" in str(error.value)


def test_reading_outside_the_granted_scope_is_refused() -> None:
    with pytest.raises(BoundaryViolation):
        authorise_read(cleaner_token(), "mart://summary.parquet")


def test_an_unlisted_tool_is_refused() -> None:
    with pytest.raises(BoundaryViolation):
        authorise_tool(cleaner_token(), "shell_exec")


def test_the_granted_scope_is_accepted() -> None:
    token = cleaner_token()
    authorise_read(token, "staging://events.parquet")
    authorise_write(token, "clean://events.parquet")
    authorise_tool(token, "rulebook.apply")


# --- layer 3: post-check ------------------------------------------------------


def test_a_correct_result_produces_no_complaints() -> None:
    manifest = load_manifest("a3_cleaner", MANIFEST_DIR)
    assert postcheck(clean_result(), manifest, cleaner_token()) == []


def test_a_result_missing_a_required_field_is_rejected() -> None:
    manifest = load_manifest("a3_cleaner", MANIFEST_DIR)
    payload = {"rows_in": 1000, "rows_out": 995, "rules_applied": [], "diff_log": []}
    problems = postcheck(clean_result(payload=payload), manifest, cleaner_token())
    assert any("content_hash" in problem for problem in problems)


def test_a_result_writing_outside_scope_is_rejected() -> None:
    manifest = load_manifest("a3_cleaner", MANIFEST_DIR)
    stray = DataRef(path="raw://stolen.parquet", format="parquet", content_hash="c" * 64)
    problems = postcheck(clean_result(output_refs=(stray,)), manifest, cleaner_token())
    assert any("ngoai pham vi" in problem for problem in problems)


def test_dropping_more_than_five_percent_of_rows_is_rejected() -> None:
    manifest = load_manifest("a3_cleaner", MANIFEST_DIR)
    metrics = {"rows_in": 1000.0, "rows_out": 900.0, "rows_dropped_pct": 10.0}
    problems = postcheck(clean_result(metrics=metrics), manifest, cleaner_token())
    assert any("vuot tran" in problem for problem in problems)


def test_exceeding_the_token_ceiling_is_rejected() -> None:
    manifest = load_manifest("a3_cleaner", MANIFEST_DIR)
    metrics = {"rows_dropped_pct": 0.0, "tokens_total": 999_999.0}
    problems = postcheck(clean_result(metrics=metrics), manifest, cleaner_token())
    assert any("token" in problem for problem in problems)
