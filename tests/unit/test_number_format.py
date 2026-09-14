"""Cach viet so quyet cho ca cot: chac chan thi doc, hai cach hieu thi dung lai va noi."""

from __future__ import annotations

import pandas as pd
import pytest

from analysis_system.services.number_format import (
    INTERNATIONAL,
    VIETNAMESE,
    convention_of,
    number_share,
    to_numbers,
)


def test_a_financial_report_written_the_international_way_is_read() -> None:
    # Bo MBB: bon cot quy bi coi la "khong phai cot so" vi dau phay tach nghin.
    column = pd.Series(["12,990.52", "1,328,560.31", "424.61", "-31.71", None])
    found = convention_of(column)
    assert (found.name, found.refusal) == (INTERNATIONAL, "")
    assert found.example == "12,990.52"
    assert to_numbers(column, found.name).tolist()[:4] == [12990.52, 1328560.31, 424.61, -31.71]


def test_two_dots_or_a_decimal_comma_can_only_be_vietnamese() -> None:
    column = pd.Series(["1.234.567", "12,5", "890"])
    found = convention_of(column)
    assert (found.name, found.refusal) == (VIETNAMESE, "")
    assert to_numbers(column, found.name).tolist() == [1234567, 12.5, 890]


def test_one_certain_cell_decides_the_ambiguous_ones_in_the_same_column() -> None:
    # "1,234" mot minh thi mo ho; cung cot voi "12.5" thi dau cham la thap phan.
    column = pd.Series(["1,234", "12.5"])
    assert to_numbers(column, convention_of(column).name).tolist() == [1234, 12.5]


@pytest.mark.parametrize(
    ("values", "said"),
    [
        (["1,234", "5,678"], "dau phay tach hang nghin"),
        (["1.000", "2.000"], "kieu Viet Nam"),
        (["12,990.52", "1.234,5"], "tron hai cach"),
    ],
)
def test_a_column_that_reads_two_ways_is_not_guessed(values: list[str], said: str) -> None:
    found = convention_of(values)
    assert found.name == ""
    assert said in found.refusal
    assert "1000 lan" in found.refusal


def test_ordinary_numbers_stay_what_they_were() -> None:
    for values in (["0.370", "0.464"], ["1", "2", "3"], ["1e5", "2.5"], ["1.000", "5", "7"]):
        found = convention_of(values)
        assert (found.name, found.refusal, found.example) == (INTERNATIONAL, "", "")


def test_share_counts_cells_readable_either_way() -> None:
    assert number_share(["1,5", "12,990.52", "abc", None, ""]) == pytest.approx(2 / 3)
    assert number_share([]) == 0.0
