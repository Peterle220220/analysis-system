"""Cau hoi doi thu hep du lieu - SQL co thu hep that khong.

Loi that: chu he thong hoi "tim nhung nguoi ky vong loi nhuan cao nhat", va SQL
them mot cot co roi de nguyen ca 40 dong. Moi con so sau do la cua ca tep, va no
duoc trinh bay nhu cau tra loi ve nhom duoc hoi.

Ca "khong duoc bao oan" duoc viet truoc va nhieu hon ca "bat dung": mot canh bao
sai bat model viet lai mot truy van dung la dot tien va lam hong mot ket qua tot.
"""

from __future__ import annotations

import pytest

from analysis_system.domains.ai_planner.narrowing import (
    asks_for_a_subset,
    missed_the_filter,
    narrows,
)

# Nguyen van cau SQL da gay ra loi.
FLAG_SQL = (
    "SELECT gender, age, Expect, "
    "CASE WHEN Expect IN ('20%-30%','30%-40%') THEN TRUE ELSE FALSE END "
    "AS high_expect_flag FROM finance_data"
)
ASKED = (
    "Loc nhung nguoi ky vong loi nhuan cao nhat ('20%-30%' hoac '30%-40%') "
    "roi phan tich thoi gian dau tu cua ho"
)


# --- bat dung ca da hong -----------------------------------------------------------


def test_the_real_failure_is_caught() -> None:
    warning = missed_the_filter(ASKED, FLAG_SQL, rows_in=40, rows_out=40)
    assert warning
    assert "WHERE" in warning
    assert "40" in warning


def test_the_warning_says_what_the_damage_is() -> None:
    # Khong phai "SQL sai cu phap" - no chay duoc. Cai hong la moi con so sau do
    # thuoc ve ca tep chu khong phai nhom duoc hoi.
    warning = missed_the_filter(ASKED, FLAG_SQL, rows_in=40, rows_out=40)
    assert "ca tep" in warning


# --- KHONG duoc bao oan ------------------------------------------------------------


def test_a_query_that_really_filters_is_left_alone() -> None:
    sql = "SELECT * FROM finance_data WHERE Expect IN ('20%-30%','30%-40%')"
    assert missed_the_filter(ASKED, sql, rows_in=40, rows_out=28) == ""


def test_a_filter_that_happens_to_keep_everything_is_left_alone() -> None:
    # WHERE co that nhung khong loai dong nao - do la du lieu, khong phai loi.
    sql = "SELECT * FROM t WHERE age > 0"
    assert missed_the_filter(ASKED, sql, rows_in=40, rows_out=40) == ""


def test_a_question_that_never_asked_to_narrow_is_left_alone() -> None:
    plain = "Them cot age_numeric bang cach chuyen cot age sang kieu so"
    assert missed_the_filter(plain, FLAG_SQL, rows_in=40, rows_out=40) == ""


def test_a_grouped_query_is_already_narrower() -> None:
    sql = "SELECT Expect, count(*) FROM t GROUP BY Expect"
    assert missed_the_filter(ASKED, sql, rows_in=40, rows_out=40) == ""


def test_rows_that_did_change_mean_something_narrowed() -> None:
    # Khong co WHERE nhung so dong giam - co the la JOIN hay DISTINCT. Im lang.
    assert missed_the_filter(ASKED, "SELECT DISTINCT gender FROM t", 40, 2) == ""


def test_an_empty_source_is_not_a_missed_filter() -> None:
    assert missed_the_filter(ASKED, FLAG_SQL, rows_in=0, rows_out=0) == ""


# --- tung manh ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "instruction",
    [
        "Loc theo nhom duoi 30 tuoi",
        "Lọc những người kỳ vọng cao",
        "chi lay nhung dong co Avenue la Equity",
        "Filter rows where age < 30",
    ],
)
def test_words_that_ask_for_a_subset(instruction: str) -> None:
    assert asks_for_a_subset(instruction)


@pytest.mark.parametrize(
    "instruction",
    [
        "Them cot so cho age",
        "Tinh trung binh moi cot",
        "Chuyen cot age sang kieu so, giu nguyen moi dong",
    ],
)
def test_words_that_do_not(instruction: str) -> None:
    assert not asks_for_a_subset(instruction)


@pytest.mark.parametrize("sql", ["SELECT * FROM t WHERE a = 1", "select * from t having x > 1"])
def test_sql_that_narrows(sql: str) -> None:
    assert narrows(sql)


def test_sql_that_does_not_narrow() -> None:
    assert not narrows("SELECT a, b FROM t")


def test_a_column_named_where_something_does_not_count_as_a_filter() -> None:
    # `\\b` chan duoc `wherever`; mot cot ten `where_from` thi khong, va do la
    # nham an toan - bo sot mot canh bao con hon bat model viet lai cai dung.
    assert not narrows("SELECT wherever FROM t")
