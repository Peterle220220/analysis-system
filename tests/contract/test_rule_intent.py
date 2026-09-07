"""Khoang cach giua LOI HUA cua mot luat va viec no THAT SU lam.

A person reads the reason at the gate and approves it. The system runs the
`rule_id`. Where those two describe different things, what was approved is not
what happens - and until now nothing looked.
"""

from __future__ import annotations

from typing import Any

from analysis_system.manager.gates import rule_options
from analysis_system.services.rule_intent import describes_instead, mismatches


def test_the_case_that_cost_a_column() -> None:
    # L78 in this project's own notes: cast_numeric_safe ran over a date column
    # and emptied it. A reason saying "chuan hoa dinh dang ngay thang" reads
    # perfectly and gets approved - and the rule underneath does something else
    # entirely.
    assert (
        describes_instead("cast_numeric_safe", "chuan hoa dinh dang ngay thang cho cot ngay_mo")
        == "standardize_datetime"
    )


def test_a_reason_that_matches_its_own_rule_is_silent() -> None:
    assert describes_instead("drop_exact_duplicates", "bo cac dong trung lap hoan toan") == ""


def test_vietnamese_with_and_without_accents_read_the_same() -> None:
    # The reason is written by a model and arrives either way.
    assert describes_instead("cast_numeric_safe", "chuẩn hoá định dạng ngày tháng") == (
        "standardize_datetime"
    )


def test_a_reason_that_sounds_like_two_other_rules_is_left_alone() -> None:
    # Loose wording is not a wrong rule, and flagging it at every gate would be
    # noise that trains people to skip the warning that matters.
    assert describes_instead("trim_whitespace", "xu ly gia tri thieu va ngay thang") == ""


def test_an_empty_reason_is_not_a_mismatch() -> None:
    # It has its own message at the gate, and a rule cannot both have no reason
    # and have the wrong one.
    assert describes_instead("cast_numeric_safe", "") == ""
    assert describes_instead("cast_numeric_safe", "   ") == ""


def test_a_reason_about_nothing_in_the_book_is_left_alone() -> None:
    assert describes_instead("trim_whitespace", "vi khach hang yeu cau nhu vay") == ""


def test_every_mismatch_is_found_by_position() -> None:
    # The gate names options by position, and a person needs to know which one
    # to go and look at.
    rules: list[dict[str, Any]] = [
        {"rule_id": "trim_whitespace", "reason": "bo khoang trang thua"},
        {"rule_id": "cast_numeric_safe", "reason": "chuan hoa ngay thang"},
    ]
    assert mismatches(rules) == {1: "standardize_datetime"}


# --- what a person actually sees ---------------------------------------------------


def test_the_warning_comes_before_the_reason_at_the_gate() -> None:
    # Before, so it cannot be read past. Somebody skimming the gate reads the
    # first words of each option and nothing else.
    rules = [{"rule_id": "cast_numeric_safe", "reason": "chuan hoa dinh dang ngay thang"}]
    detail = rule_options(rules)[0].detail
    assert detail.startswith("[LUAT VA LY DO KHONG KHOP]")
    assert "chuan hoa dinh dang ngay thang" in detail


def test_a_matching_rule_shows_only_its_reason() -> None:
    rules = [{"rule_id": "drop_exact_duplicates", "reason": "bo dong trung lap"}]
    detail = rule_options(rules)[0].detail
    assert "bo dong trung lap" in detail
    assert "KHONG KHOP" not in detail


def test_a_rule_with_no_reason_still_says_so() -> None:
    # The older check, kept working alongside the new one.
    rules = [{"rule_id": "trim_whitespace", "reason": ""}]
    assert "KHONG CO LY DO" in rule_options(rules)[0].detail
