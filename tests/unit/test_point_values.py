"""Loc & Tinh: gia tri tai moc cau hoi goi ten va chenh lech, bang code, Viet lan Anh."""

from __future__ import annotations

import pandas as pd
import pytest

from analysis_system.services.point_values import named_values, period_key, point_comparison

QUESTION = (
    "So sánh Lợi nhuận sau thuế của MBBank giữa Q2-2026 và Q1-2026. "
    "Chênh lệch là bao nhiêu tỷ đồng?"
)
LONG = pd.DataFrame(
    {
        "Bảng": ["Kết quả kinh doanh"] * 8,
        "Chỉ tiêu": ["Lợi nhuận sau thuế"] * 4
        + ["Lợi nhuận sau thuế của cổ đông của Ngân hàng mẹ"] * 4,
        "Kỳ báo cáo": ["Q3-2025", "Q4-2025", "Q1-2026", "Q2-2026"] * 2,
        "Giá trị": [5800.44, 8902.95, 7702.72, 8445.47, 5571.02, 8762.57, 7515.51, 8229.06],
    }
)
PREFIX = "Giá trị (Lợi nhuận sau thuế)"


def test_the_mbb_question_gets_both_values_and_the_difference() -> None:
    metrics, notes = point_comparison(LONG, QUESTION)
    values = {key: metric.value for key, metric in metrics.items()}
    assert values[f"{PREFIX}.value.by.Kỳ báo cáo.Q1-2026"] == 7702.72
    assert values[f"{PREFIX}.value.by.Kỳ báo cáo.Q2-2026"] == 8445.47
    assert values[f"{PREFIX}.change.by.Kỳ báo cáo.Q2-2026"] == pytest.approx(742.75)
    assert values[f"{PREFIX}.pct_change.by.Kỳ báo cáo.Q2-2026"] == pytest.approx(9.6428, abs=1e-3)
    # Chi tieu dai hon ("... cua co dong ...") khong duoc goi ten nen khong bi tinh.
    assert not any("cổ đông" in key for key in values)
    assert "Q2-2026 trừ tại Q1-2026" in metrics[f"{PREFIX}.change.by.Kỳ báo cáo.Q2-2026"].source
    assert any("không qua model" in note for note in notes)


def test_a_wide_table_answers_the_same_question() -> None:
    wide = pd.DataFrame(
        {
            "Kỳ": ["Q3-2025", "Q4-2025", "Q1-2026", "Q2-2026"],
            "Lợi nhuận sau thuế": [5800.44, 8902.95, 7702.72, 8445.47],
            "Tổng cộng tài sản": [1.0, 2.0, 3.0, 4.0],
        }
    )
    metrics, _ = point_comparison(wide, QUESTION)
    assert metrics["Lợi nhuận sau thuế.change.by.Kỳ.Q2-2026"].value == pytest.approx(742.75)


def test_later_minus_earlier_whatever_order_the_question_uses() -> None:
    metrics, _ = point_comparison(LONG, "Lợi nhuận sau thuế Q1-2026 so với Q3-2025 tăng bao nhiêu?")
    # Q3-2025 -> Q1-2026 khong lien nhau trong bang, nhung la hai moc duoc hoi.
    assert metrics[f"{PREFIX}.change.by.Kỳ báo cáo.Q1-2026"].value == pytest.approx(1902.28)


def test_an_english_question_on_many_rows_adds_them_up() -> None:
    sales = pd.DataFrame(
        {"Region": ["North", "North", "South", "South", "South"], "Revenue": [10, 20, 5, 5, 5]}
    )
    metrics, _ = point_comparison(sales, "Compare revenue between North and South")
    assert metrics["Revenue.sum.by.Region.North"].value == 30
    assert metrics["Revenue.sum.by.Region.South"].value == 15
    # Khong phai moc thoi gian: theo thu tu trong cau, moc sau tru moc truoc.
    assert metrics["Revenue.change.by.Region.South"].value == -15


def test_an_average_is_taken_only_when_asked_for() -> None:
    sales = pd.DataFrame({"Khu vực": ["Bắc", "Bắc", "Nam"], "Giá": [10.0, 20.0, 30.0]})
    metrics, _ = point_comparison(sales, "Giá trung bình ở Bắc và Nam chênh lệch bao nhiêu?")
    assert metrics["Giá.mean.by.Khu vực.Bắc"].value == 15


def test_an_accented_question_does_not_match_an_unaccented_group() -> None:
    # "năm 2024" khong duoc bien thanh bo loc Gioi tinh = Nam.
    frame = pd.DataFrame(
        {
            "Giới tính": ["Nam", "Nữ", "Nam", "Nữ"],
            "Năm": [2023, 2023, 2024, 2024],
            "Doanh thu": [1.0, 2.0, 3.0, 4.0],
        }
    )
    metrics, _ = point_comparison(frame, "So sánh doanh thu năm 2024 và 2023")
    assert metrics["Doanh thu.sum.by.Năm.2024"].value == 7
    assert metrics["Doanh thu.change.by.Năm.2024"].value == 4
    assert not any("Nam)" in key for key in metrics)


def test_a_question_naming_nothing_in_the_table_adds_nothing() -> None:
    assert point_comparison(LONG, "Dữ liệu này có gì đáng chú ý?") == ({}, [])
    assert named_values(LONG, "") == {}


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
