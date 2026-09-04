"""Tests for the cleaning rulebook: each rule, plus the guarantees around them."""

from __future__ import annotations

import unicodedata

import pandas as pd
import pytest

from analysis_system.services.rulebook import (
    MISSING_FLAG_COLUMN,
    RULE_ORDER,
    RuleError,
    RuleSpec,
    apply_rules,
    cast_numeric_safe,
    drop_exact_duplicates,
    flag_missing_required,
    normalize_unicode_nfc,
    replace_sentinel_with_null,
    standardize_datetime,
    trim_whitespace,
)


def test_trim_whitespace_records_every_change() -> None:
    frame = pd.DataFrame({"vendor": ["  ACME ", "ok", None]})
    result, diff = trim_whitespace(frame, RuleSpec("trim_whitespace", ("vendor",)))
    assert result.loc[0, "vendor"] == "ACME"
    assert [(entry.row_index, entry.before, entry.after) for entry in diff] == [
        (0, "  ACME ", "ACME")
    ]


def test_normalize_unicode_nfc_makes_equal_strings_equal() -> None:
    composed = unicodedata.normalize("NFC", "Nguyen")
    decomposed = unicodedata.normalize("NFD", "Nguy") + "e" + "̂̃" + "n"
    composed = unicodedata.normalize("NFC", decomposed)
    assert decomposed != composed
    frame = pd.DataFrame({"name": [decomposed]})
    result, diff = normalize_unicode_nfc(frame, RuleSpec("normalize_unicode_nfc", ("name",)))
    assert result.loc[0, "name"] == composed
    assert len(diff) == 1


def test_a_stated_sentinel_becomes_a_real_missing_value() -> None:
    frame = pd.DataFrame({"price": ["300000", "0", "450000"]})
    spec = RuleSpec("replace_sentinel_with_null", ("price",), {"sentinels": ["0"]})
    result, diff = replace_sentinel_with_null(frame, spec)
    assert result["price"].isna().sum() == 1
    assert len(diff) == 1
    assert diff[0].before == "0"
    assert diff[0].reason == "gia tri canh chung -> rong"


def test_it_refuses_to_guess_which_values_are_sentinels() -> None:
    frame = pd.DataFrame({"price": ["0"]})
    with pytest.raises(RuleError, match="sentinels"):
        replace_sentinel_with_null(frame, RuleSpec("replace_sentinel_with_null", ("price",)))


def test_it_refuses_to_run_across_a_whole_table() -> None:
    # The reason this matters: in the Seattle house data, 0 is a sentinel in
    # yr_renovated and a legitimate level in waterfront. Applied blindly this
    # rule would blank out 4,567 real values.
    frame = pd.DataFrame({"price": ["0"], "waterfront": ["0"]})
    spec = RuleSpec("replace_sentinel_with_null", (), {"sentinels": ["0"]})
    with pytest.raises(RuleError, match="chi ro cot"):
        replace_sentinel_with_null(frame, spec)


def test_a_column_not_named_is_left_completely_alone() -> None:
    frame = pd.DataFrame({"price": ["0", "1"], "waterfront": ["0", "1"]})
    spec = RuleSpec("replace_sentinel_with_null", ("price",), {"sentinels": ["0"]})
    result, _ = replace_sentinel_with_null(frame, spec)
    assert result["price"].isna().sum() == 1
    assert result["waterfront"].tolist() == ["0", "1"]


def test_several_sentinel_spellings_are_accepted() -> None:
    frame = pd.DataFrame({"price": ["0", "0.0", "N/A", "500"]})
    spec = RuleSpec("replace_sentinel_with_null", ("price",), {"sentinels": ["0", "0.0", "N/A"]})
    result, diff = replace_sentinel_with_null(frame, spec)
    assert result["price"].isna().sum() == 3
    assert len(diff) == 3


def test_the_sentinel_rule_runs_before_casting() -> None:
    # Order matters: a sentinel has to become missing while it is still text,
    # so the cast never sees it and never reports it as a value that failed.
    frame = pd.DataFrame({"price": ["300000", "0"]})
    plan = [
        RuleSpec("cast_numeric_safe", ("price",)),
        RuleSpec("replace_sentinel_with_null", ("price",), {"sentinels": ["0"]}),
    ]
    outcome = apply_rules(frame, plan)
    assert outcome.rules_applied == ("replace_sentinel_with_null", "cast_numeric_safe")
    assert outcome.frame["price"].isna().sum() == 1
    assert outcome.frame["price"].max() == 300000


def test_a_sentinel_turned_null_is_then_seen_by_the_missing_flag() -> None:
    # The two rules compose: one makes the absence real, the other reports it.
    frame = pd.DataFrame({"price": ["300000", "0"]})
    plan = [
        RuleSpec("replace_sentinel_with_null", ("price",), {"sentinels": ["0"]}),
        RuleSpec("flag_missing_required", ("price",)),
    ]
    outcome = apply_rules(frame, plan)
    assert outcome.frame[MISSING_FLAG_COLUMN].tolist() == [False, True]


def test_the_rulebook_now_holds_seven_rules() -> None:
    assert len(RULE_ORDER) == 7
    assert "replace_sentinel_with_null" in RULE_ORDER


def test_standardize_datetime_refuses_to_guess_the_timezone() -> None:
    frame = pd.DataFrame({"timestamp": ["2018-01-02T12:53:00.000Z"]})
    with pytest.raises(RuleError) as error:
        standardize_datetime(frame, RuleSpec("standardize_datetime", ("timestamp",)))
    assert "assume_timezone" in str(error.value)


def test_standardize_datetime_converts_to_utc() -> None:
    frame = pd.DataFrame({"timestamp": ["2018-01-02T12:53:00.000Z", "khong phai ngay"]})
    spec = RuleSpec("standardize_datetime", ("timestamp",), {"assume_timezone": "UTC"})
    result, diff = standardize_datetime(frame, spec)
    assert str(result.loc[0, "timestamp"]) == "2018-01-02 12:53:00+00:00"
    # The unparseable value is reported, not silently turned into null.
    assert [(entry.row_index, entry.before) for entry in diff] == [(1, "khong phai ngay")]


def test_cast_numeric_safe_logs_failures_with_the_row_index() -> None:
    """A stray value inside a number column is cast away and written down.

    Nineteen numbers and one word: a number column with a bad cell in it, which
    is what this rule is for. The old fixture had one bad value in three - not a
    number column with a stray value but a text column, and casting it is the
    failure below.
    """
    values = [str(index) for index in range(19)]
    values.insert(1, "khong phai so")
    frame = pd.DataFrame({"amount": values})

    result, diff = cast_numeric_safe(frame, RuleSpec("cast_numeric_safe", ("amount",)))
    assert result.loc[0, "amount"] == 0.0
    assert len(diff) == 1
    assert diff[0].row_index == 1
    assert diff[0].before == "khong phai so"
    assert diff[0].reason == "khong ep duoc ve so"


def test_cast_numeric_safe_leaves_a_text_column_alone() -> None:
    """The failure the name promised would not happen.

    Named no columns, the rule sees every column. Casting a date column with
    `errors="coerce"` turns it into NaN from top to bottom, and on a real sales
    table it did exactly that to two columns at once - the dates and the
    channel. Every loss went into the diff log as promised, and recording the
    destruction of a column is not the same as not destroying it.
    """
    frame = pd.DataFrame(
        {
            "ngay_ban": ["2026-01-05", "2026-01-15", "2026-02-05"],
            "kenh": ["ban le", "dai ly", "buu dien"],
            "doanh_thu": ["100.5", "220", "310.25"],
        }
    )
    result, diff = cast_numeric_safe(frame, RuleSpec("cast_numeric_safe"))

    assert list(result["ngay_ban"]) == ["2026-01-05", "2026-01-15", "2026-02-05"]
    assert list(result["kenh"]) == ["ban le", "dai ly", "buu dien"]
    assert result.loc[0, "doanh_thu"] == 100.5, "cot so that van phai duoc ep"


def test_a_column_left_alone_says_it_was_left_alone() -> None:
    """Silence reads exactly like a column nobody considered."""
    frame = pd.DataFrame({"kenh": ["ban le", "dai ly", "buu dien"]})
    _, diff = cast_numeric_safe(frame, RuleSpec("cast_numeric_safe"))
    assert len(diff) == 1
    assert diff[0].column == "kenh"
    assert "khong phai cot so" in diff[0].reason


def test_drop_exact_duplicates_keeps_the_first_occurrence() -> None:
    frame = pd.DataFrame({"case_id": ["c1", "c1", "c2"], "activity": ["A", "A", "A"]})
    result, diff = drop_exact_duplicates(frame, RuleSpec("drop_exact_duplicates"))
    assert len(result) == 2
    assert len(diff) == 1


def test_flag_missing_required_marks_rows_instead_of_dropping_them() -> None:
    frame = pd.DataFrame({"case_id": ["c1", None], "activity": ["A", "B"]})
    result, diff = flag_missing_required(frame, RuleSpec("flag_missing_required", ("case_id",)))
    assert len(result) == 2
    assert result[MISSING_FLAG_COLUMN].tolist() == [False, True]
    assert len(diff) == 1


def test_rules_run_in_the_declared_order_not_the_caller_order() -> None:
    frame = pd.DataFrame({"amount": ["  10.5  ", "  10.5  "]})
    plan = [
        # Deliberately reversed: casting is listed before trimming.
        RuleSpec("cast_numeric_safe", ("amount",)),
        RuleSpec("trim_whitespace", ("amount",)),
    ]
    outcome = apply_rules(frame, plan)
    assert outcome.rules_applied == ("trim_whitespace", "cast_numeric_safe")
    # Trimming first is what lets the cast succeed at all.
    assert outcome.frame["amount"].tolist() == [10.5, 10.5]


def test_rule_order_covers_exactly_the_registered_rules() -> None:
    # Two rules refuse to run on defaults, and that refusal is the point: one
    # will not guess a timezone, the other will not guess what counts as a
    # sentinel or which columns to touch.
    columns: dict[str, tuple[str, ...]] = {"replace_sentinel_with_null": ("note",)}
    params: dict[str, dict[str, object]] = {
        "standardize_datetime": {"assume_timezone": "UTC"},
        "replace_sentinel_with_null": {"sentinels": ["__khong_co__"]},
    }
    plan = [
        RuleSpec(rule_id, columns.get(rule_id, ()), params.get(rule_id, {}))
        for rule_id in RULE_ORDER
    ]
    frame = pd.DataFrame({"note": ["a", "b"]})
    outcome = apply_rules(frame, plan)
    assert outcome.rules_applied == RULE_ORDER


def test_apply_rules_rejects_a_rule_outside_the_rulebook() -> None:
    with pytest.raises(RuleError) as error:
        apply_rules(pd.DataFrame({"x": [1]}), [RuleSpec("tu_che_rule")])
    assert "tu_che_rule" in str(error.value)


def test_one_rule_may_be_approved_twice_for_different_columns() -> None:
    # Casting a sequence to an integer and a currency to a float are two
    # intents, not a conflict. Both run, in the order they were approved.
    frame = pd.DataFrame({"seq": ["1", "2"], "amount": ["3.5", "4.5"]})
    plan = [
        RuleSpec("cast_numeric_safe", ("seq",)),
        RuleSpec("cast_numeric_safe", ("amount",)),
    ]
    outcome = apply_rules(frame, plan)
    assert outcome.rules_applied == ("cast_numeric_safe", "cast_numeric_safe")
    assert outcome.frame["seq"].tolist() == [1, 2]
    assert outcome.frame["amount"].tolist() == [3.5, 4.5]


def test_a_parameter_no_rule_reads_is_refused_by_name() -> None:
    # The real proposal invented target_type, on_error and decimal_separator.
    # Dropping them in silence would let a proposal promise behaviour the code
    # has not got, and the person at the gate would approve it believing it.
    with pytest.raises(RuleError, match="target_type"):
        apply_rules(
            pd.DataFrame({"x": ["1"]}),
            [RuleSpec("cast_numeric_safe", ("x",), {"target_type": "int64"})],
        )


def test_the_parameter_a_rule_does_read_is_accepted() -> None:
    frame = pd.DataFrame({"t": ["2018-01-01T00:00:00Z"]})
    outcome = apply_rules(
        frame, [RuleSpec("standardize_datetime", ("t",), {"assume_timezone": "UTC"})]
    )
    assert outcome.rules_applied == ("standardize_datetime",)


def test_rules_still_run_in_the_declared_order_when_repeated() -> None:
    frame = pd.DataFrame({"a": ["  1  "], "b": ["  2  "]})
    plan = [
        RuleSpec("cast_numeric_safe", ("a",)),
        RuleSpec("trim_whitespace", ("a",)),
        RuleSpec("cast_numeric_safe", ("b",)),
        RuleSpec("trim_whitespace", ("b",)),
    ]
    outcome = apply_rules(frame, plan)
    # Trimming comes first for both, whatever order the caller listed things in.
    assert outcome.rules_applied == (
        "trim_whitespace",
        "trim_whitespace",
        "cast_numeric_safe",
        "cast_numeric_safe",
    )
    assert outcome.frame["a"].tolist() == [1]


def test_rules_reject_a_column_that_does_not_exist() -> None:
    with pytest.raises(RuleError):
        trim_whitespace(pd.DataFrame({"x": ["a"]}), RuleSpec("trim_whitespace", ("khong_co",)))


def test_rows_dropped_pct_reports_what_deduplication_removed() -> None:
    frame = pd.DataFrame({"x": ["a", "a", "b", "c"]})
    outcome = apply_rules(frame, [RuleSpec("drop_exact_duplicates")])
    assert outcome.rows_in == 4
    assert outcome.rows_out == 3
    assert outcome.rows_dropped_pct == pytest.approx(25.0)
