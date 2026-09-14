"""Bang nam ngang (moi chi tieu mot dong, moi ky mot cot) duoc de xuat xoay, va xoay dung.

Mo phong dung hinh dang bao cao tai chinh MBB: hai bang xep chong co cot "Bang",
so viet kieu quoc te "12,990.52", o "-" la trong, dong tieu de muc khong co so.
"""

from __future__ import annotations

import pandas as pd
import pytest

from analysis_system.services.diagnosis import PERIOD_HEADER, examine, period_layout
from analysis_system.services.rulebook import (
    PERIOD_COLUMN,
    RuleError,
    RuleSpec,
    apply_rules,
    cannot_run,
)

QUARTERS = ["Q3-2025", "Q4-2025", "Q1-2026", "Q2-2026"]


def statement() -> pd.DataFrame:
    rows = [
        (
            "Kết quả kinh doanh",
            "Thu nhập lãi thuần",
            "12,990.52",
            "14,555.29",
            "14,913.12",
            "16,893.65",
        ),
        (
            "Kết quả kinh doanh",
            "Lợi nhuận sau thuế",
            "5,800.44",
            "8,902.95",
            "7,702.72",
            "8,445.47",
        ),
        ("Kết quả kinh doanh", "Lãi cơ bản trên cổ phiếu", "-", "-", "-", "-"),
        ("Cân đối kế toán", "Tài sản", None, None, None, None),
        (
            "Cân đối kế toán",
            "Tổng cộng tài sản",
            "1,328,560.31",
            "1,615,763.93",
            "1,611,222.76",
            "1,733,012.66",
        ),
        ("Cân đối kế toán", "Thu nhập lãi thuần", "1.00", "2.00", "3.00", "4.00"),
    ]
    return pd.DataFrame(rows, columns=["Bảng", "Chỉ tiêu", *QUARTERS], dtype=object)


def test_a_sideways_statement_is_proposed_for_pivoting() -> None:
    findings = examine(statement()).findings
    found = [item for item in findings if item.rule_id == "pivot_periods_to_columns"]
    assert len(found) == 1
    assert found[0].params == {"label": "Chỉ tiêu", "periods": QUARTERS}


def test_placeholder_cells_do_not_stop_a_number_column_being_proposed() -> None:
    # Bo MBB: 4/38 o "-" lam cot quy khong duoc de xuat ep so. Luat thay o danh
    # dau chay TRUOC luat ep so, nen dem ty le so thi bo qua chung.
    frame = pd.DataFrame({"so": ["1,000.5", "2,000.5", "1,000.5", "-", "-"]})
    proposed = {item.rule_id for item in examine(frame).findings if item.column == "so"}
    assert {"replace_sentinel_with_null", "cast_numeric_safe"} <= proposed


def test_the_pivot_makes_one_numeric_column_per_item_and_one_row_per_period() -> None:
    frame = statement()
    layout = period_layout(frame)
    assert layout is not None
    outcome = apply_rules(
        frame,
        [
            RuleSpec("replace_sentinel_with_null", tuple(QUARTERS), {"sentinels": ["-"]}),
            RuleSpec("cast_numeric_safe", tuple(QUARTERS)),
            RuleSpec("pivot_periods_to_columns", (), dict(layout.params)),
        ],
    )
    out = outcome.frame
    assert list(out[PERIOD_COLUMN]) == QUARTERS
    assert list(out.columns) == [
        PERIOD_COLUMN,
        "Thu nhập lãi thuần (Kết quả kinh doanh)",
        "Lợi nhuận sau thuế",
        "Tổng cộng tài sản",
        "Thu nhập lãi thuần (Cân đối kế toán)",
    ]
    assert out["Lợi nhuận sau thuế"].tolist() == [5800.44, 8902.95, 7702.72, 8445.47]
    assert pd.api.types.is_float_dtype(out["Tổng cộng tài sản"])
    by_period = out.set_index(PERIOD_COLUMN)["Lợi nhuận sau thuế"]
    assert by_period["Q2-2026"] - by_period["Q1-2026"] == pytest.approx(742.75)
    # Doi hinh bang khong phai bo dong: tran 5% khong duoc chan no.
    assert outcome.rows_dropped_pct == 0.0
    dropped = [entry.before for entry in outcome.diff if "tieu de muc" in entry.reason]
    assert dropped == ["Lãi cơ bản trên cổ phiếu", "Tài sản"]
    assert any("chi dung de phan biet ten trung" in entry.reason for entry in outcome.diff)


def test_an_ordinary_table_is_not_touched() -> None:
    frame = pd.DataFrame(
        {"Tên": ["An", "Bình", "Chi"], "Toán": ["8", "9", "7"], "Lý": ["6", "7", "8"]}
    )
    assert period_layout(frame) is None


def test_period_columns_of_words_are_not_a_statement() -> None:
    frame = pd.DataFrame(
        {"Tên": ["An", "Bình", "Chi"], "Q1-2025": ["tốt", "xấu", "tốt"], "Q2-2025": ["a", "b", "c"]}
    )
    assert period_layout(frame) is None


def test_year_headers_are_proposed_too_and_the_person_decides() -> None:
    frame = pd.DataFrame(
        {"Sản phẩm": ["A", "B", "C"], "2023": ["1", "2", "3"], "2024": ["4", "5", "6"]}
    )
    layout = period_layout(frame)
    assert layout is not None
    assert layout.params == {"label": "Sản phẩm", "periods": ["2023", "2024"]}


@pytest.mark.parametrize(
    "header",
    [
        "Q3-2025",
        "Quý 3/2025",
        "2025-Q3",
        "Q1/25",
        "2024",
        "Năm 2024",
        "FY2024",
        "T1/2025",
        "Tháng 12-2025",
        "01/2025",
        "2025-01",
        "H1-2025",
    ],
)
def test_period_headers_are_recognised(header: str) -> None:
    assert PERIOD_HEADER.match(header)


@pytest.mark.parametrize("header", ["Doanh thu", "Q5-2025", "2025-13", "Toán", "Tên", "12345"])
def test_other_headers_are_not_periods(header: str) -> None:
    assert not PERIOD_HEADER.match(header)


def test_a_pivot_without_its_columns_is_refused_before_it_runs() -> None:
    assert cannot_run(RuleSpec("pivot_periods_to_columns"))
    with pytest.raises(RuleError):
        apply_rules(
            statement(),
            [RuleSpec("pivot_periods_to_columns", (), {"label": "Chỉ tiêu", "periods": ["Q9"]})],
        )
