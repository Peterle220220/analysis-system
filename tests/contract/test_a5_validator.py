"""A5 tests: it judges objectively, explains itself, and never edits the data."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from analysis_system.agents.a5_validator import ValidatorAgent, build_checks, count_checks
from analysis_system.contracts.base import DataRef, ScopeToken, TaskRequest, TaskResult
from analysis_system.core import storage
from analysis_system.core.hashing import canonical_hash
from analysis_system.core.settings import LAYER_NAMES, LayerPaths, Settings, load_settings, resolve
from analysis_system.services.validation import (
    ValidationSpecError,
    check_comparisons,
    check_ranges,
    check_references,
)

NOW = datetime(2026, 8, 31, 17, 0, tzinfo=UTC)
MANIFEST_DIR = Path(__file__).resolve().parents[2] / "config" / "manifests"


def houses() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id": ["1", "2", "3", "4"],
            "price": ["300000", "0", "450000", "-5"],
            "city": ["Seattle", "Renton", "Seattle", "Kent"],
            "listed": ["2014-05-02", "2014-05-03", "2014-05-04", "2014-05-05"],
            "sold": ["2014-06-01", "2014-05-01", "2014-06-04", "2014-06-05"],
        }
    )


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    roots = {name: tmp_path / name for name in LAYER_NAMES}
    for root in roots.values():
        root.mkdir(parents=True, exist_ok=True)
    return load_settings().model_copy(update={"layers": LayerPaths(**roots)})


def token(checks: dict[str, Any] | None = None) -> ScopeToken:
    """A token matching the shipped a5_validator manifest."""
    return ScopeToken(
        run_id="r_val",
        task_id="t_check",
        agent_id="a5_validator",
        allow_read=("staging://**", "clean://**", "mart://**", "profile://**", "extracted://**"),
        allow_write=("validation://**",),
        allow_tools=("pandas", "pandera"),
        params={"checks": checks} if checks is not None else {},
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
    )


def stage(settings: Settings, frame: pd.DataFrame) -> DataRef:
    storage.write_parquet(frame, resolve("clean://events.parquet", settings))
    return DataRef(path="clean://events.parquet", format="parquet", content_hash="a" * 64)


def judge(settings: Settings, frame: pd.DataFrame, checks: dict[str, Any] | None) -> TaskResult:
    agent = ValidatorAgent(settings, MANIFEST_DIR)
    request = TaskRequest(
        scope=token(checks), input_refs=(stage(settings, frame),), instruction="cham"
    )
    return agent.run(request, now=NOW)


# --- the individual checks ----------------------------------------------------


def test_a_range_check_finds_values_outside_the_bounds() -> None:
    failures = check_ranges(houses(), [("price", 1.0, None)])
    assert len(failures) == 1
    assert failures[0].count == 2  # the 0 and the -5
    assert failures[0].sample_rows


def test_a_range_check_on_a_clean_column_says_nothing() -> None:
    assert check_ranges(houses(), [("price", -100.0, 1_000_000.0)]) == []


def test_a_missing_column_is_reported_not_ignored() -> None:
    failures = check_ranges(houses(), [("khong_co", 0.0, None)])
    assert len(failures) == 1
    assert "Khong co cot" in failures[0].detail


def test_a_business_rule_compares_two_columns() -> None:
    # Row 2 was sold before it was listed.
    failures = check_comparisons(houses(), [("sold_after_listed", "sold", ">=", "listed")])
    assert len(failures) == 1
    assert failures[0].count == 1


def test_dates_are_compared_as_dates_not_as_text() -> None:
    frame = pd.DataFrame({"a": ["2014-1-9"], "b": ["2014-1-10"]})
    # As text "2014-1-9" sorts after "2014-1-10"; as dates it does not.
    assert check_comparisons(frame, [("a_before_b", "a", "<=", "b")]) == []


def test_a_row_missing_either_side_cannot_break_a_comparison() -> None:
    frame = pd.DataFrame({"a": ["5", None], "b": ["3", "9"]})
    failures = check_comparisons(frame, [("a_le_b", "a", "<=", "b")])
    assert failures[0].count == 1  # only the row where both are present


def test_an_unknown_operator_is_a_specification_error() -> None:
    with pytest.raises(ValidationSpecError, match="khong hop le"):
        check_comparisons(houses(), [("x", "price", "=~", "price")])


def test_a_reference_check_finds_values_with_no_match() -> None:
    failures = check_references(houses(), "city", ["Seattle", "Renton"])
    assert len(failures) == 1
    assert failures[0].count == 1  # Kent
    assert "Kent" in failures[0].detail


def test_a_reference_check_passes_when_everything_matches() -> None:
    assert check_references(houses(), "city", ["Seattle", "Renton", "Kent"]) == []


# --- assembling a specification -----------------------------------------------


def test_every_kind_of_check_can_be_asked_for_at_once() -> None:
    spec = {
        "not_null": ["id", "price"],
        "unique_together": [["id"]],
        "ranges": [{"column": "price", "min": 1}],
        "comparisons": [
            {"name": "sold_after_listed", "left": "sold", "operator": ">=", "right": "listed"}
        ],
        "references": [{"column": "city", "allowed": ["Seattle", "Renton", "Kent"]}],
    }
    assert count_checks(spec) == 6
    failures = build_checks(houses(), spec)
    names = {failure.test for failure in failures}
    assert "price:range" in names
    assert "sold_after_listed" in names


def test_a_malformed_reference_rule_is_refused() -> None:
    with pytest.raises(ValidationSpecError):
        build_checks(houses(), {"references": [{"column": "city"}]})


# --- the agent ----------------------------------------------------------------


def test_a_clean_table_passes(settings: Settings) -> None:
    frame = pd.DataFrame({"id": ["1", "2"], "price": ["100", "200"]})
    result = judge(settings, frame, {"not_null": ["id", "price"], "unique_together": [["id"]]})
    assert result.is_ok, result.error
    assert result.payload["failed"] == 0
    assert result.payload["passed"] == 3


def test_failures_come_with_a_count_and_example_rows(settings: Settings) -> None:
    result = judge(settings, houses(), {"ranges": [{"column": "price", "min": 1}]})
    assert result.is_ok, result.error
    assert result.payload["failed"] == 1
    failure = result.payload["failures"][0]
    assert failure["count"] == 2
    assert failure["sample_rows"], "moi loi phai kem dong vi pham"


def test_the_verdict_is_written_into_the_validation_layer(settings: Settings) -> None:
    result = judge(settings, houses(), {"not_null": ["id"]})
    assert result.output_refs[0].path.startswith("validation://")
    assert list(settings.layers.validation.iterdir())


def test_it_never_alters_the_table_it_judges(settings: Settings) -> None:
    # The rule the spec states in capitals: no editing data to make a check pass.
    frame = houses()
    before = canonical_hash(frame)
    judge(settings, frame, {"ranges": [{"column": "price", "min": 1}]})
    staged = storage.read_parquet(resolve("clean://events.parquet", settings))
    assert canonical_hash(staged) == before


def test_it_cannot_write_into_the_clean_layer(settings: Settings) -> None:
    agent = ValidatorAgent(settings, MANIFEST_DIR)
    wider = token({"not_null": ["id"]}).model_copy(update={"allow_write": ("clean://**",)})
    result = agent.run(
        TaskRequest(scope=wider, input_refs=(stage(settings, houses()),), instruction="cham"),
        now=NOW,
    )
    assert result.status == "BOUNDARY_VIOLATION"


def test_row_count_drift_is_checked_when_asked(settings: Settings) -> None:
    frame = pd.DataFrame({"id": ["1", "2"]})
    result = judge(settings, frame, {"rows_in": 100, "max_rows_dropped_pct": 5.0})
    assert result.payload["failed"] == 1
    assert result.payload["failures"][0]["test"] == "row_count_drift"


def test_being_given_no_checks_is_a_failure_not_a_pass(settings: Settings) -> None:
    # Silently passing a table nobody specified checks for would be worse than
    # useless: it would look like a verdict.
    result = judge(settings, houses(), None)
    assert result.status == "FAILED"
    assert result.error is not None
    assert result.error.code == "NO_CHECKS"


def test_a_malformed_specification_is_reported(settings: Settings) -> None:
    result = judge(settings, houses(), {"references": [{"column": "city"}]})
    assert result.status == "FAILED"
    assert result.error is not None
    assert result.error.code == "BAD_SPEC"


def test_the_manifest_forbids_a_model(settings: Settings) -> None:
    agent = ValidatorAgent(settings, MANIFEST_DIR)
    assert agent.manifest.allow.llm.enabled is False
    assert "modify_data_to_pass" in agent.manifest.deny


# --- hai luat cho tu Phase 5, gio chay duoc qua dung duong A5 ----------------------


def test_a_pattern_rule_reaches_the_referee(settings: Settings) -> None:
    """Declared like every other check, and refused like every other failure.

    Worth having now that scans and recordings feed this pipeline: a code typed
    by a person is usually the right shape, and the same code read by OCR is
    where `O` becomes `0`.
    """
    frame = pd.DataFrame({"ma": ["AB-123", "O8-4S6"], "gia": ["10", "20"]})
    result = judge(
        settings,
        frame,
        {"patterns": [{"name": "ma_hop_le", "column": "ma", "pattern": "[A-Z]{2}-[0-9]{3}"}]},
    )
    assert result.payload["failed"] == 1
    assert result.payload["failures"][0]["test"] == "ma_hop_le"


def test_a_time_window_rule_reaches_the_referee(settings: Settings) -> None:
    frame = pd.DataFrame({"ngay": ["2026-01-05", "1970-01-01"], "gia": ["10", "20"]})
    result = judge(
        settings,
        frame,
        {"time_windows": [{"name": "trong_ky", "column": "ngay", "from": "2026-01-01"}]},
    )
    assert result.payload["failed"] == 1
    assert result.payload["failures"][0]["test"] == "trong_ky"


def test_a_specification_of_only_new_rules_is_not_called_empty(settings: Settings) -> None:
    """The counter has to know about them, or the referee refuses to run.

    A5 rejects a specification that asserts nothing. A check the counter cannot
    see is a check that cannot stop that rejection, so a run asserting only
    patterns would be told it had asserted nothing at all.
    """
    frame = pd.DataFrame({"ma": ["AB-123"], "ngay": ["2026-01-05"]})
    result = judge(
        settings,
        frame,
        {
            "patterns": [{"column": "ma", "pattern": "[A-Z]{2}-[0-9]{3}"}],
            "time_windows": [{"column": "ngay", "from": "2026-01-01"}],
        },
    )
    assert result.status == "OK", result.error
    assert result.payload["passed"] == 2
    assert result.payload["failed"] == 0
