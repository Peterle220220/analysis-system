"""Tests for the validator: it must judge objectively and never touch the data."""

from __future__ import annotations

import pandas as pd

from analysis_system.services.validation import (
    ColumnRule,
    SchemaSpec,
    check_row_count_drift,
    run_checks,
)

SPEC = SchemaSpec(
    columns=(
        ColumnRule("case_id", nullable=False),
        ColumnRule("event_seq", nullable=False),
        ColumnRule("activity", nullable=False),
    ),
    unique_together=(("case_id", "event_seq"),),
)


def _valid_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "case_id": ["c1", "c1", "c2"],
            "event_seq": [0, 1, 0],
            "activity": ["Create", "Approve", "Create"],
        }
    )


def test_a_clean_frame_passes_every_check() -> None:
    report = run_checks(_valid_frame(), SPEC)
    assert report.is_ok
    assert report.failed == 0
    assert report.passed == SPEC.check_count()


def test_a_null_in_a_required_column_fails_with_example_rows() -> None:
    frame = _valid_frame()
    frame.loc[1, "activity"] = None
    report = run_checks(frame, SPEC)
    assert not report.is_ok
    assert report.failed == 1
    failure = report.failures[0]
    assert "activity" in failure.test
    assert failure.count == 1
    assert failure.sample_rows, "phai kem dong vi pham lam vi du"


def test_a_duplicate_key_pair_is_caught() -> None:
    frame = pd.DataFrame(
        {
            "case_id": ["c1", "c1"],
            "event_seq": [0, 0],
            "activity": ["Create", "Create"],
        }
    )
    report = run_checks(frame, SPEC)
    assert not report.is_ok


def test_a_missing_column_is_reported_not_ignored() -> None:
    frame = _valid_frame().drop(columns=["activity"])
    report = run_checks(frame, SPEC)
    assert not report.is_ok


def test_row_count_drift_within_the_threshold_passes() -> None:
    assert check_row_count_drift(1000, 990, max_drop_pct=5.0) == []


def test_row_count_drift_above_the_threshold_fails() -> None:
    failures = check_row_count_drift(1000, 900, max_drop_pct=5.0)
    assert len(failures) == 1
    assert failures[0].count == 100
    assert "10.00%" in failures[0].detail


def test_validation_never_modifies_the_frame() -> None:
    frame = _valid_frame()
    frame.loc[1, "activity"] = None
    before = frame.copy()
    run_checks(frame, SPEC, rows_in=10, max_drop_pct=5.0)
    pd.testing.assert_frame_equal(frame, before)
