"""Tinh cheo dong tren bang dai: code xoay ngang tam thoi, tu khai nguon goc, roi moi chia.

Bo MBB __q2: "ROA tung quy" tren bang Chi tieu | Ky bao cao | Gia tri. Model viet SQL
hong ba kieu trong ba luot; phep xoay nay la viec code lam duoc.
"""

from __future__ import annotations

import pandas as pd
import pytest

from analysis_system.services.cross_row import (
    PIVOT_REASON,
    pivot_proposal,
    ratio_name,
    read_cross_row,
)
from analysis_system.services.sql_runner import run_query

ROA = "Tính tỷ lệ Lợi nhuận sau thuế trên Tổng cộng tài sản (ROA) của từng quý."
QUARTERS = ["Q3-2025", "Q4-2025", "Q1-2026", "Q2-2026"]
PROFIT = [5800.44, 8902.95, 7702.72, 8445.47]
ASSETS = [1328560.31, 1615763.93, 1611222.76, 1733012.66]
LONG = pd.DataFrame(
    {
        "Bảng": ["Kết quả kinh doanh"] * 4 + ["Cân đối kế toán"] * 4,
        "Chỉ tiêu": ["Lợi nhuận sau thuế"] * 4 + ["Tổng cộng tài sản"] * 4,
        "Kỳ báo cáo": QUARTERS * 2,
        "Giá trị": PROFIT + ASSETS,
    }
)


def test_a_ratio_of_two_rows_is_read_off_the_question() -> None:
    cross = read_cross_row(LONG, ROA)
    assert cross is not None
    assert (cross.label, cross.value) == ("Chỉ tiêu", "Giá trị")
    assert cross.items == ("Lợi nhuận sau thuế", "Tổng cộng tài sản")
    assert cross.ratio == ("Lợi nhuận sau thuế", "Tổng cộng tài sản")
    # "Bang" chi mo ta chi tieu; gom theo no thi hai chi tieu nam hai dong va phep chia rong.
    assert cross.group_by == ("Kỳ báo cáo",)


def test_the_code_built_pivot_runs_and_declares_every_column() -> None:
    proposal = pivot_proposal({"bctc": LONG}, ROA)
    assert proposal is not None
    assert proposal.reason == PIVOT_REASON
    frame = run_query(proposal.sql, {"bctc": LONG}).frame.set_index("Kỳ báo cáo")
    ratio = "Lợi nhuận sau thuế / Tổng cộng tài sản"
    assert list(frame.columns) == ["Lợi nhuận sau thuế", "Tổng cộng tài sản", ratio]
    assert frame.loc["Q2-2026", ratio] == pytest.approx(8445.47 / 1733012.66)
    assert frame.loc["Q3-2025", "Lợi nhuận sau thuế"] == pytest.approx(5800.44)
    declared = {entry.output for entry in proposal.lineage}
    assert declared == {"Lợi nhuận sau thuế", "Tổng cộng tài sản", ratio}


def test_two_named_rows_without_a_division_are_still_pivoted_side_by_side() -> None:
    proposal = pivot_proposal(
        {"bctc": LONG}, "So sánh Lợi nhuận sau thuế và Tổng cộng tài sản từng quý"
    )
    assert proposal is not None
    frame = run_query(proposal.sql, {"bctc": LONG}).frame
    assert list(frame.columns) == ["Kỳ báo cáo", "Lợi nhuận sau thuế", "Tổng cộng tài sản"]


def test_one_named_row_is_left_to_the_model() -> None:
    # Loc mot chi tieu roi so hai quy: khong co gi cheo dong.
    question = "So sánh Lợi nhuận sau thuế giữa Q2-2026 và Q1-2026"
    assert pivot_proposal({"bctc": LONG}, question) is None


def test_a_wide_table_is_not_a_long_one() -> None:
    wide = pd.DataFrame({"Kỳ": QUARTERS, "Lợi nhuận sau thuế": PROFIT, "Tổng cộng tài sản": ASSETS})
    assert read_cross_row(wide, ROA) is None


def test_the_instruction_is_read_when_the_question_is_not_enough() -> None:
    instruction = "Lấy giá trị chỉ tiêu 'Lợi nhuận sau thuế' chia cho 'Tổng cộng tài sản' theo kỳ"
    proposal = pivot_proposal({"bctc": LONG}, "ROA từng quý?", instruction)
    assert proposal is not None
    cross = read_cross_row(LONG, instruction)
    assert cross is not None and ratio_name(cross) == "Lợi nhuận sau thuế / Tổng cộng tài sản"
