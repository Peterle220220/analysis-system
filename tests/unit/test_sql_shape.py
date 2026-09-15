"""SQL gom nhom truoc tang thong ke.

Loi that, do tren luot chay cua chu he thong:

    SELECT poutcome, y, COUNT(*) AS num_customers
    FROM bank_additional_full GROUP BY poutcome, y

41.176 dong vao, 6 dong ra. Roi 6 dong do di vao tang thong ke va moi phep kiem
chet voi "duoi 5 quan sat".
"""

from __future__ import annotations

import pytest

from analysis_system.domains.execution_engine.sql_shape import aggregates_in, collapses_rows

# Nguyen van cau da lam hong lan chay.
DA_HONG = "SELECT poutcome, y, COUNT(*) AS num_customers FROM bank WHERE 1=1 GROUP BY poutcome, y"

# Nguyen van cac cau da chay DUNG trong cung dot test do.
DA_DUNG = [
    "SELECT *, CASE WHEN y = 'yes' THEN 1 ELSE 0 END AS is_yes FROM bank "
    "WHERE job = 'student' AND previous > 0",
    "SELECT poutcome, campaign, y FROM bank",
    "SELECT age, CAST(duration AS BIGINT) AS duration_num, "
    "CASE WHEN CAST(duration AS BIGINT) < 100 THEN 'short' ELSE 'long' END AS bucket FROM bank",
]


# --- phai bat -----------------------------------------------------------------


def test_the_statement_that_broke_the_run_is_caught() -> None:
    found = aggregates_in(DA_HONG)
    assert "GROUP BY" in found
    assert "COUNT" in found


def test_it_says_why_rather_than_just_refusing() -> None:
    said = collapses_rows(DA_HONG)
    assert "thong ke" in said
    assert "WHERE" in said


@pytest.mark.parametrize("name", ["COUNT", "SUM", "AVG", "MIN", "MAX", "MEDIAN", "STDDEV"])
def test_every_aggregate_function_is_known(name: str) -> None:
    assert name in aggregates_in(f"SELECT {name}(x) FROM t")


def test_group_by_alone_is_enough() -> None:
    assert aggregates_in("SELECT a, b FROM t GROUP BY a") == ("GROUP BY",)


def test_spacing_and_case_do_not_hide_it() -> None:
    assert "GROUP BY" in aggregates_in("select a from t GROUP   BY a")
    assert "SUM" in aggregates_in("select sum ( x ) from t")


# --- phai im lang -------------------------------------------------------------


@pytest.mark.parametrize("sql", DA_DUNG)
def test_a_statement_that_keeps_every_row_is_left_alone(sql: str) -> None:
    assert aggregates_in(sql) == ()
    assert collapses_rows(sql) == ""


def test_a_column_named_like_an_aggregate_is_not_an_aggregate() -> None:
    """`max_duration` la mot cai ten, khong phai mot phep gom."""
    assert aggregates_in("SELECT max_duration, sum_total, counted FROM t") == ()


def test_an_aggregate_word_inside_a_string_is_not_an_aggregate() -> None:
    """Go chuoi hang ra truoc, de `WHERE job = 'count'` khong bi doc nham."""
    assert aggregates_in("SELECT a FROM t WHERE job = 'count(x)'") == ()


def test_row_level_functions_are_not_aggregates() -> None:
    # CAST, CASE, ROUND bien doi tung dong va giu nguyen so dong.
    assert aggregates_in("SELECT CAST(a AS INT), ROUND(b, 2) FROM t") == ()


def test_nothing_in_means_nothing_out() -> None:
    assert aggregates_in("") == ()
    assert collapses_rows("") == ""
