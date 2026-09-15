"""Ke hoach duoc lap tren mo ta cua BANG SACH, khong phai cua tep goc da doi hinh.

Bo MBB: A2 mo ta bang truoc khi lam sach (Bang, Chi tieu, Q3-2025...), bang sach da
xoay thanh Ky + moi chi tieu mot cot so, va ke hoach ra lenh tren nhung cot khong con.
"""

from __future__ import annotations

import pandas as pd

from analysis_system.agents.a2_profiler import (
    RESHAPED_NOTE,
    guess_roles,
    merge_profile,
    profile_columns,
    refreshed_profile,
)
from analysis_system.models.agents import ProfileReport


def stored_for(frame: pd.DataFrame, meanings: dict[str, str]) -> ProfileReport:
    columns = tuple(
        column.model_copy(update={"meaning": meanings.get(column.name, "")})
        for column in profile_columns(frame)
    )
    return merge_profile(frame, columns, guess_roles(columns), None)


SIDEWAYS = pd.DataFrame(
    {
        "Bảng": ["Kết quả kinh doanh", "Kết quả kinh doanh"],
        "Chỉ tiêu": ["Thu nhập lãi thuần", "Lợi nhuận sau thuế"],
        "Q1-2026": ["14,913.12", "7,702.72"],
        "Q2-2026": ["16,893.65", "8,445.47"],
    }
)
PIVOTED = pd.DataFrame(
    {
        "Kỳ": ["Q1-2026", "Q2-2026"],
        "Thu nhập lãi thuần": [14913.12, 16893.65],
        "Lợi nhuận sau thuế": [7702.72, 8445.47],
    }
)


def test_a_reshaped_clean_table_is_described_as_it_now_is() -> None:
    stored = stored_for(SIDEWAYS, {"Chỉ tiêu": "tên chỉ tiêu"})
    fresh = refreshed_profile(stored, PIVOTED)
    assert [column.name for column in fresh.columns] == sorted(PIVOTED.columns)
    assert fresh.row_count == 2
    profit = next(column for column in fresh.columns if column.name == "Lợi nhuận sau thuế")
    assert profit.numeric_share == 1.0
    assert fresh.observations == (RESHAPED_NOTE,)


def test_the_same_columns_keep_the_stored_profile_and_its_meanings() -> None:
    stored = stored_for(SIDEWAYS, {"Chỉ tiêu": "tên chỉ tiêu"})
    assert refreshed_profile(stored, SIDEWAYS.copy()) is stored


def test_a_column_that_kept_its_name_keeps_what_was_said_about_it() -> None:
    stored = stored_for(SIDEWAYS, {"Chỉ tiêu": "tên chỉ tiêu"})
    widened = SIDEWAYS.assign(Ghi_chu=["a", "b"])
    fresh = refreshed_profile(stored, widened)
    meaning = {column.name: column.meaning for column in fresh.columns}
    assert meaning["Chỉ tiêu"] == "tên chỉ tiêu"
    assert meaning["Ghi_chu"] == ""


def test_without_a_stored_profile_the_table_is_measured_plainly() -> None:
    fresh = refreshed_profile(None, PIVOTED)
    assert fresh.row_count == 2
    assert fresh.observations == ()
