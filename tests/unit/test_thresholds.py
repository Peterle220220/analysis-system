"""Nguong trong cau hoi phai nam nguyen van trong SQL loc.

Bao cao cap do 3 nghi Planner doi "lon hon 0.2" thanh "lon hon trung binh". Do
tren luot chay that thi SQL dung dung 0.2 - nhung day la loai sai dat nhat neu
xay ra, nen code kiem lai sau moi buoc loc thay vi tin mot loi dan trong prompt.
"""

from __future__ import annotations

from analysis_system.domains.execution_engine.thresholds import (
    asked_thresholds,
    filters,
    missing_thresholds,
    threshold_warning,
)

QUESTION = "Trong nhóm các công ty có tỷ lệ nợ lớn hơn 0.2, so sánh trung bình lợi nhuận."


def _values(question: str) -> list[frozenset[float]]:
    return [threshold.values for threshold in asked_thresholds(question)]


# --- doc nguong trong cau hoi ---------------------------------------------------


def test_the_threshold_in_the_question_is_found() -> None:
    assert _values(QUESTION) == [frozenset({0.2})]


def test_a_vietnamese_decimal_comma_is_read() -> None:
    assert 0.2 in _values("tỷ lệ nợ lớn hơn 0,2")[0]


def test_comparison_symbols_are_read_even_without_spaces() -> None:
    assert _values("Debt > 0.2") == [frozenset({0.2})]
    assert _values("ratio>=0.5") == [frozenset({0.5})]


def test_a_percent_may_be_written_as_a_ratio_in_sql() -> None:
    assert {20.0, 0.2} <= _values("tỷ lệ nợ trên 20%")[0]


def test_units_are_multiplied_out() -> None:
    assert 1.5e6 in _values("doanh thu trên 1,5 triệu")[0]


def test_an_ambiguous_thousands_mark_accepts_both_readings() -> None:
    assert {6.819, 6819.0} <= _values("nhiều hơn 6.819 dòng")[0]


def test_no_threshold_means_nothing_to_check() -> None:
    assert asked_thresholds("So sánh trung bình giữa hai nhóm") == []


# --- doi chieu voi SQL ------------------------------------------------------------


def test_the_exact_number_in_the_filter_passes() -> None:
    assert missing_thresholds(QUESTION, 'SELECT * FROM t WHERE "Debt ratio %" > 0.2') == []


def test_a_trailing_zero_is_the_same_number() -> None:
    assert missing_thresholds(QUESTION, "SELECT * FROM t WHERE ratio > 0.20") == []


def test_a_mean_in_place_of_the_number_is_caught() -> None:
    sql = "SELECT * FROM t WHERE ratio > (SELECT AVG(ratio) FROM t)"
    assert missing_thresholds(QUESTION, sql) == ["lon hon 0.2"]


def test_a_rounded_number_is_caught() -> None:
    assert missing_thresholds(QUESTION, "SELECT * FROM t WHERE ratio > 0.25") == ["lon hon 0.2"]


def test_a_number_inside_a_column_name_does_not_count() -> None:
    sql = 'SELECT * FROM t WHERE "muc 0.2" > AVG(x)'
    assert missing_thresholds(QUESTION, sql) == ["lon hon 0.2"]


def test_the_warning_names_the_threshold_and_what_to_do() -> None:
    warning = threshold_warning(QUESTION, "SELECT * FROM t WHERE ratio > 0.25")
    assert "lon hon 0.2" in warning
    assert "WHERE" in warning


def test_no_warning_when_the_number_is_kept() -> None:
    assert threshold_warning(QUESTION, "SELECT * FROM t WHERE ratio > 0.2") == ""


def test_only_a_where_clause_counts_as_a_filter() -> None:
    assert filters("SELECT a FROM t WHERE b > 1")
    assert not filters("SELECT a, AVG(b) FROM t GROUP BY a")
    assert not filters('SELECT "where" FROM t')
