"""Doc cau hoi: gia tri duoc goi ten, moc thoi gian, "tung" ky, phep chia - Viet lan Anh."""

from __future__ import annotations

import pandas as pd
import pytest

from analysis_system.services.question_labels import (
    asks_each,
    is_ratio_gap,
    named_values,
    names_in_order,
    period_columns,
    period_key,
)


@pytest.mark.parametrize(
    ("label", "key"),
    [
        ("Q2-2026", (2026, 6)),
        ("Quý 3/2025", (2025, 9)),
        ("2025-Q4", (2025, 12)),
        ("Q1/25", (2025, 3)),
        ("Tháng 12-2025", (2025, 12)),
        ("01/2026", (2026, 1)),
        ("2026-02", (2026, 2)),
        ("H1-2025", (2025, 6)),
        ("Năm 2024", (2024, 12)),
        ("FY2023", (2023, 12)),
        ("North", None),
        ("2025-13", None),
    ],
)
def test_period_labels_sort_in_time(label: str, key: tuple[int, int] | None) -> None:
    assert period_key(label) == key


@pytest.mark.parametrize(
    ("question", "each"),
    [
        ("Tính ROA của từng quý", True),
        ("Doanh thu mỗi tháng là bao nhiêu?", True),
        ("doanh thu tung quy", True),
        ("Revenue for each quarter", True),
        ("Mối quan hệ giữa doanh thu và chi phí", False),
        ("Tổng doanh thu là bao nhiêu?", False),
    ],
)
def test_each_is_read_and_not_confused_with_a_similar_word(question: str, each: bool) -> None:
    assert asks_each(question) is each


@pytest.mark.parametrize(
    ("question", "names", "ratio"),
    [
        (
            "Tỷ lệ Lợi nhuận sau thuế trên Tổng cộng tài sản",
            ["Lợi nhuận sau thuế", "Tổng cộng tài sản"],
            True,
        ),
        (
            "lay loi nhuan sau thue chia cho tong cong tai san",
            ["Lợi nhuận sau thuế", "Tổng cộng tài sản"],
            True,
        ),
        ("profit/assets by quarter", ["profit", "assets"], True),
        ("What is the ratio of profit to assets?", ["profit", "assets"], True),
        (
            "So sánh Lợi nhuận sau thuế và Tổng cộng tài sản",
            ["Lợi nhuận sau thuế", "Tổng cộng tài sản"],
            False,
        ),
    ],
)
def test_a_division_between_two_names_is_recognised(
    question: str, names: list[str], ratio: bool
) -> None:
    hits = names_in_order(question, names)
    assert len(hits) == 2
    assert is_ratio_gap(question, hits[0], hits[1]) is ratio


def test_the_longer_name_wins_when_the_question_says_it() -> None:
    frame = pd.DataFrame({"Chỉ tiêu": ["Lợi nhuận sau thuế", "Lợi nhuận sau thuế của cổ đông"]})
    assert named_values(frame, "Lợi nhuận sau thuế của cổ đông quý 2") == {
        "Chỉ tiêu": ["Lợi nhuận sau thuế của cổ đông"]
    }
    assert named_values(frame, "Lợi nhuận sau thuế quý 2") == {"Chỉ tiêu": ["Lợi nhuận sau thuế"]}


def test_period_columns_are_found_by_their_values() -> None:
    frame = pd.DataFrame(
        {
            "Kỳ": ["Q1-2026", "Q2-2026"],
            "Năm": [2025, 2026],
            "Khu vực": ["Bắc", "Nam"],
            "x": [1.5, 2.5],
        }
    )
    assert period_columns(frame) == ["Kỳ", "Năm"]
