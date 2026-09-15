"""Tests for report rendering: numbers come from the context, never from text."""

from __future__ import annotations

import pandas as pd

from analysis_system.domains.visualization.reporting import (
    VOLATILE_MARKER,
    ColumnStat,
    ReportContext,
    render_report,
    report_hash,
    summarise_columns,
    summarise_diff,
)
from analysis_system.services.rulebook import DiffEntry
from analysis_system.services.validation import Failure, ValidationReport


def _context(**overrides: object) -> ReportContext:
    base: dict[str, object] = {
        "run_id": "r_0001",
        "generated_at": "2026-08-30T22:00:00Z",
        "duration_s": 4.25,
        "source_path": "raw://sample.csv",
        "source_hash": "abc123",
        "rows_in": 1000,
        "rows_out": 990,
        "rules_applied": ("trim_whitespace", "cast_numeric_safe"),
        "diff_summary": (("cat khoang trang thua", 12),),
        "validation": ValidationReport(passed=8, failed=0, failures=()),
        "column_stats": (ColumnStat("timestamp", "object", 990, 1.0, 900),),
        "output_hashes": (("clean", "deadbeef"),),
    }
    base.update(overrides)
    return ReportContext(**base)  # type: ignore[arg-type]


def test_every_number_comes_from_the_context() -> None:
    text = render_report(_context())
    assert "**1000**" in text
    assert "**990**" in text
    assert "1.00%" in text
    assert "`trim_whitespace`" in text


def test_changing_a_metric_changes_the_report() -> None:
    first = render_report(_context())
    second = render_report(_context(rows_out=500))
    assert first != second


def test_only_marked_lines_are_treated_as_volatile() -> None:
    first = render_report(_context())
    second = render_report(
        _context(run_id="r_9999", generated_at="2027-01-01T00:00:00Z", duration_s=99.9)
    )
    assert first != second
    assert report_hash(first) == report_hash(second)


def test_a_column_named_timestamp_still_counts_towards_the_hash() -> None:
    # The whole reason for an explicit marker: this row is substantive content.
    changed = _context(column_stats=(ColumnStat("timestamp", "object", 12, 98.8, 3),))
    assert report_hash(render_report(_context())) != report_hash(render_report(changed))


def test_failures_are_printed_with_their_counts() -> None:
    report = ValidationReport(
        passed=7,
        failed=1,
        failures=(Failure(test="activity:not_nullable", count=3, detail="thieu gia tri"),),
    )
    text = render_report(_context(validation=report))
    assert "**FAIL**" in text
    assert "`activity:not_nullable`" in text
    assert "| 3 |" in text


def test_volatile_marker_covers_run_metadata_and_the_source_path() -> None:
    marked = [line for line in render_report(_context()).splitlines() if VOLATILE_MARKER in line]
    assert len(marked) == 4


def test_the_source_path_does_not_affect_the_report_hash() -> None:
    # The same file processed from two machines must compare equal; its sha256,
    # which stays in the hash, is what actually identifies the input.
    here = render_report(_context(source_path="/home/a/sample.csv"))
    there = render_report(_context(source_path="/srv/data/sample.csv"))
    assert report_hash(here) == report_hash(there)


def test_a_different_source_file_still_changes_the_report_hash() -> None:
    first = render_report(_context())
    second = render_report(_context(source_hash="ffffff"))
    assert report_hash(first) != report_hash(second)


def test_summarise_columns_is_sorted_by_name() -> None:
    frame = pd.DataFrame({"b": [1, None], "a": ["x", "y"]})
    stats = summarise_columns(frame)
    assert [stat.name for stat in stats] == ["a", "b"]
    assert stats[1].non_null == 1
    assert stats[1].null_pct == 50.0


def test_summarise_diff_counts_by_reason_in_a_stable_order() -> None:
    diff = [
        DiffEntry("r", "c", 0, "a", "b", "ly do B"),
        DiffEntry("r", "c", 1, "a", "b", "ly do A"),
        DiffEntry("r", "c", 2, "a", "b", "ly do B"),
    ]
    assert summarise_diff(diff) == (("ly do A", 1), ("ly do B", 2))
