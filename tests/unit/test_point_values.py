"""Loc & Tinh: gia tri tai moc, chenh lech, ty le A / B - bang code, Viet lan Anh."""

from __future__ import annotations

import pandas as pd
import pytest

from analysis_system.domains.execution_engine.point_values import point_comparison
from analysis_system.services.question_labels import named_values

QUESTION = (
    "So sánh Lợi nhuận sau thuế của MBBank giữa Q2-2026 và Q1-2026. "
    "Chênh lệch là bao nhiêu tỷ đồng?"
)
ROA = "Tính tỷ lệ Lợi nhuận sau thuế trên Tổng cộng tài sản (ROA) của từng quý."
QUARTERS = ["Q3-2025", "Q4-2025", "Q1-2026", "Q2-2026"]
PROFIT = [5800.44, 8902.95, 7702.72, 8445.47]
ASSETS = [1328560.31, 1615763.93, 1611222.76, 1733012.66]
LONG = pd.DataFrame(
    {
        "Bảng": ["Kết quả kinh doanh"] * 8 + ["Cân đối kế toán"] * 4,
        "Chỉ tiêu": ["Lợi nhuận sau thuế"] * 4
        + ["Lợi nhuận sau thuế của cổ đông của Ngân hàng mẹ"] * 4
        + ["Tổng cộng tài sản"] * 4,
        "Kỳ báo cáo": QUARTERS * 3,
        "Giá trị": PROFIT + [5571.02, 8762.57, 7515.51, 8229.06] + ASSETS,
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


def test_roa_for_each_quarter_on_the_long_table() -> None:
    # Bo MBB __q2: loi nhuan va tai san la hai DONG cua cot Chi tieu.
    metrics, notes = point_comparison(LONG, ROA)
    prefix = "Giá trị (Lợi nhuận sau thuế / Tổng cộng tài sản)"
    for quarter, profit, assets in zip(QUARTERS, PROFIT, ASSETS, strict=True):
        assert metrics[f"{prefix}.ratio.by.Kỳ báo cáo.{quarter}"].value == pytest.approx(
            profit / assets, abs=1e-4
        )
        assert metrics[f"{prefix}.ratio_pct.by.Kỳ báo cáo.{quarter}"].unit == "%"
    # "Tung quy" la bon con so, khong phai ba phep tru.
    assert not any(".change." in key for key in metrics)
    assert any("tỷ lệ Lợi nhuận sau thuế / Tổng cộng tài sản" in note for note in notes)


def test_roa_on_the_table_a4_pivoted() -> None:
    wide = pd.DataFrame(
        {
            "Kỳ báo cáo": QUARTERS,
            "Lợi nhuận sau thuế": PROFIT,
            "Tổng cộng tài sản": ASSETS,
            "Lợi nhuận sau thuế / Tổng cộng tài sản": [
                p / a for p, a in zip(PROFIT, ASSETS, strict=True)
            ],
        }
    )
    metrics, _ = point_comparison(wide, ROA)
    key = "Lợi nhuận sau thuế / Tổng cộng tài sản.ratio.by.Kỳ báo cáo.Q2-2026"
    assert metrics[key].value == pytest.approx(8445.47 / 1733012.66, abs=1e-4)
    assert metrics["Lợi nhuận sau thuế.value.by.Kỳ báo cáo.Q3-2025"].value == 5800.44


def test_each_quarter_of_one_item_is_listed_without_differences() -> None:
    metrics, _ = point_comparison(LONG, "Lợi nhuận sau thuế của từng quý")
    assert [metrics[f"{PREFIX}.value.by.Kỳ báo cáo.{q}"].value for q in QUARTERS] == PROFIT
    assert not any(".change." in key for key in metrics)


def test_a_wide_table_answers_the_comparison_too() -> None:
    wide = pd.DataFrame({"Kỳ": QUARTERS, "Lợi nhuận sau thuế": PROFIT, "Tổng cộng tài sản": ASSETS})
    metrics, _ = point_comparison(wide, QUESTION)
    assert metrics["Lợi nhuận sau thuế.change.by.Kỳ.Q2-2026"].value == pytest.approx(742.75)


def test_later_minus_earlier_whatever_order_the_question_uses() -> None:
    metrics, _ = point_comparison(LONG, "Lợi nhuận sau thuế Q1-2026 so với Q3-2025 tăng bao nhiêu?")
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
