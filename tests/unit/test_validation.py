"""Tests for the validator: it must judge objectively and never touch the data."""

from __future__ import annotations

import pandas as pd

from analysis_system.domains.data_ingestion.validation import (
    ColumnRule,
    SchemaSpec,
    check_pattern,
    check_row_count_drift,
    check_time_window,
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


# --- dinh dang: cai ma tai lieu quet ra hay lam hong -------------------------------


def test_a_value_of_the_wrong_shape_is_caught_with_its_row() -> None:
    """The failure OCR produces: `O` for `0`, `l` for `1`, `S` for `5`.

    A code typed into a spreadsheet is usually the right shape. The same code
    read off a scan is not, and nothing downstream notices until a join quietly
    matches nothing at all.
    """
    frame = pd.DataFrame({"ma": ["AB-123", "O8-4S6", "CD-789"]})
    failures = check_pattern(frame, [("ma_hop_le", "ma", r"[A-Z]{2}-[0-9]{3}")])

    assert len(failures) == 1
    assert failures[0].count == 1
    assert failures[0].sample_rows, "phai chi ra duoc dong nao, khong chi dua con so"


def test_a_column_of_the_right_shape_passes() -> None:
    """The other direction, so a check cannot pass by failing everything."""
    frame = pd.DataFrame({"ma": ["AB-123", "CD-789"]})
    assert check_pattern(frame, [("ma", "ma", r"[A-Z]{2}-[0-9]{3}")]) == []


def test_the_pattern_must_match_the_whole_value() -> None:
    """ "Contains a code somewhere" is a different assertion from "is a code"."""
    frame = pd.DataFrame({"ma": ["xx AB-123 yy"]})
    assert check_pattern(frame, [("ma", "ma", r"[A-Z]{2}-[0-9]{3}")])


def test_a_missing_value_is_not_a_wrongly_shaped_one() -> None:
    """Whether a column may be empty is what `not_null` is for.

    Answering it in two places is how the two answers start to disagree.
    """
    frame = pd.DataFrame({"ma": ["AB-123", None]})
    assert check_pattern(frame, [("ma", "ma", r"[A-Z]{2}-[0-9]{3}")]) == []


def test_a_pattern_that_will_not_compile_is_reported_not_raised() -> None:
    """A specification is written by a person, or proposed by a model.

    Neither is incapable of typing `[unclosed`, and falling over takes the whole
    run down for a typo instead of naming the rule that has one.
    """
    frame = pd.DataFrame({"ma": ["AB-123"]})
    failures = check_pattern(frame, [("hong", "ma", "[chua dong")])
    assert len(failures) == 1
    assert "khong bien dich duoc" in failures[0].detail


def test_a_pattern_on_a_column_that_is_not_there_says_so() -> None:
    frame = pd.DataFrame({"khac": ["x"]})
    failures = check_pattern(frame, [("ma", "ma", r"[A-Z]+")])
    assert "Khong co cot" in failures[0].detail


# --- moc thoi gian: mot dong nam 1970 lam lech moi trung binh ----------------------


def test_a_timestamp_outside_the_window_is_caught() -> None:
    """Quiet and expensive: one row dated 1970 moves every average and trend.

    It looks like data right up until somebody plots it.
    """
    frame = pd.DataFrame({"ngay": ["2026-01-05", "1970-01-01", "2026-03-01"]})
    failures = check_time_window(frame, [("trong_ky", "ngay", "2026-01-01", "2026-12-31")])

    assert len(failures) == 1
    assert failures[0].count == 1
    assert failures[0].sample_rows


def test_timestamps_inside_the_window_pass() -> None:
    frame = pd.DataFrame({"ngay": ["2026-01-05", "2026-03-01"]})
    assert check_time_window(frame, [("ky", "ngay", "2026-01-01", "2026-12-31")]) == []


def test_one_open_bound_is_allowed() -> None:
    """ "Nothing before the system existed" is a complete assertion on its own."""
    frame = pd.DataFrame({"ngay": ["2019-01-01", "2026-03-01"]})
    failures = check_time_window(frame, [("khong_qua_som", "ngay", "2025-01-01", None)])
    assert failures[0].count == 1


def test_a_value_nobody_can_read_counts_as_outside_every_window() -> None:
    """Saying otherwise would let it be counted as inside one."""
    frame = pd.DataFrame({"ngay": ["2026-01-05", "khong doc duoc"]})
    failures = check_time_window(frame, [("ky", "ngay", "2026-01-01", "2026-12-31")])
    assert failures[0].count == 1


def test_a_column_that_holds_no_timestamps_is_reported_not_coerced() -> None:
    """Parsing what parses and ignoring the rest reports a clean column.

    It would be clean because it was never checked, which is the worst kind of
    pass this system can produce.
    """
    frame = pd.DataFrame({"ten": ["ha noi", "da nang"]})
    failures = check_time_window(frame, [("ky", "ten", "2026-01-01", None)])
    assert len(failures) == 1
    assert "khong doc duoc thanh moc thoi gian" in failures[0].detail


def test_a_bound_that_cannot_be_read_is_reported_by_name() -> None:
    frame = pd.DataFrame({"ngay": ["2026-01-05"]})
    failures = check_time_window(frame, [("ky", "ngay", "hom qua", None)])
    assert any("khong doc duoc" in failure.detail for failure in failures)
