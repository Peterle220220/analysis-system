"""Tests for canonical hashing, the definition behind criterion S1."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analysis_system.services.hashing import (
    canonical_frame,
    canonical_hash,
    canonical_hash_text,
    strip_volatile_lines,
)


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "case_id": ["c1", "c2", "c3"],
            "activity": ["Create", "Approve", "Pay"],
            "amount": [10.5, 20.0, 30.25],
        }
    )


def test_row_order_does_not_change_the_hash() -> None:
    original = _frame()
    shuffled = original.iloc[[2, 0, 1]].reset_index(drop=True)
    assert canonical_hash(shuffled) == canonical_hash(original)


def test_column_order_does_not_change_the_hash() -> None:
    original = _frame()
    reordered = original[["amount", "case_id", "activity"]]
    assert canonical_hash(reordered) == canonical_hash(original)


def test_changing_one_value_changes_the_hash() -> None:
    original = _frame()
    edited = original.copy()
    edited.loc[0, "activity"] = "Created"
    assert canonical_hash(edited) != canonical_hash(original)


def test_equal_floats_written_differently_hash_the_same() -> None:
    left = pd.DataFrame({"amount": [1.10, 2.0]})
    right = pd.DataFrame({"amount": [1.1, 2.00]})
    assert canonical_hash(left) == canonical_hash(right)


def test_every_flavour_of_missing_value_is_the_same() -> None:
    left = pd.DataFrame({"note": [None, "x"]})
    right = pd.DataFrame({"note": [np.nan, "x"]})
    assert canonical_hash(left) == canonical_hash(right)


def test_sort_keys_must_name_real_columns() -> None:
    with pytest.raises(KeyError):
        canonical_frame(_frame(), sort_keys=["khong_co_cot_nay"])


def test_canonical_form_starts_with_sorted_header() -> None:
    header = canonical_frame(_frame()).splitlines()[0]
    assert header.split("\t") == ["activity", "amount", "case_id"]


def test_volatile_lines_are_dropped_before_hashing_a_report() -> None:
    first = "# Bao cao\nrun_id: r_0001\nduration_s: 4.2\nrows_out: 981\n"
    second = "# Bao cao\nrun_id: r_9999\nduration_s: 7.9\nrows_out: 981\n"
    assert canonical_hash_text(first) == canonical_hash_text(second)
    assert "rows_out: 981" in strip_volatile_lines(first)


def test_a_real_content_change_still_changes_the_report_hash() -> None:
    first = "# Bao cao\nrun_id: r_0001\nrows_out: 981\n"
    second = "# Bao cao\nrun_id: r_0001\nrows_out: 980\n"
    assert canonical_hash_text(first) != canonical_hash_text(second)
