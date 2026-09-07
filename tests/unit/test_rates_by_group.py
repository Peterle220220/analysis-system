"""Ty le cua mot ket qua hai gia tri, trong tung nhom.

Cho trong nay lam hong mot cau tra loi that. Chu he thong hoi:

    Giua ket qua chien dich truoc (poutcome) va so lan goi hien tai (campaign),
    yeu to nao anh huong manh hon den ty le mo so (y)? Nhom khach hang nao co
    ty le 'yes' cao nhat?

Sau ket luan tra ve deu noi `campaign` thay doi the nao THEO `y` - nguoc chieu
cau hoi. Khong phai model chon sai: con so tra loi cau hoi CHUA TUNG DUOC DO.

He thong biet do trung binh mot cot SO theo nhom, va ty le tung gia tri cua mot
cot CHU dung mot minh. No khong biet bat cheo hai cot chu - ma "nhom nao chot
duoc nhieu nhat" chinh la phep do.
"""

from __future__ import annotations

import pandas as pd

from analysis_system.services.findings import rankings
from analysis_system.services.metrics import MIN_GROUP_ROWS, compute_metrics


def _bank(rows_per_group: int = 10) -> pd.DataFrame:
    """Bang nho mang dung hinh dang cua du lieu that: hai cot chu, mot cot so."""
    records = []
    for group, yes_count in (("success", 7), ("failure", 2), ("nonexistent", 1)):
        for index in range(rows_per_group):
            records.append(
                {
                    "poutcome": group,
                    "y": "yes" if index < yes_count else "no",
                    "campaign": index + 1,
                }
            )
    return pd.DataFrame(records)


# --- con so tra loi cau hoi phai co that --------------------------------------


def test_the_rate_of_a_two_valued_outcome_is_measured_per_group() -> None:
    found = compute_metrics(_bank(), dimensions=("poutcome", "y"))
    assert found["y.yes.share_pct.by.poutcome.success"].value == 70.0
    assert found["y.yes.share_pct.by.poutcome.failure"].value == 20.0


def test_both_values_of_the_outcome_are_measured() -> None:
    found = compute_metrics(_bank(), dimensions=("poutcome", "y"))
    assert found["y.no.share_pct.by.poutcome.success"].value == 30.0


def test_the_shares_of_a_group_add_up_to_a_hundred() -> None:
    found = compute_metrics(_bank(), dimensions=("poutcome", "y"))
    total = (
        found["y.yes.share_pct.by.poutcome.success"].value
        + found["y.no.share_pct.by.poutcome.success"].value
    )
    assert round(total, 6) == 100.0


def test_it_carries_a_percent_unit() -> None:
    found = compute_metrics(_bank(), dimensions=("poutcome", "y"))
    assert found["y.yes.share_pct.by.poutcome.success"].unit == "%"


# --- code tu tra loi duoc "nhom nao cao nhat" ---------------------------------


def test_the_ranking_answers_which_group_converts_best() -> None:
    """Day la nua thu hai cua cau hoi cap do 2, va code tra loi duoc mot minh."""
    found = compute_metrics(_bank(), dimensions=("poutcome", "y"))
    tops = [
        row["khoa"]
        for row in rankings(found)
        if row["xep_hang"] == "cao nhat" and row["khoa"].startswith("y.yes.share_pct.by.poutcome")
    ]
    assert tops == ["y.yes.share_pct.by.poutcome.success"]


# --- cac cho phai im lang -----------------------------------------------------


def test_a_group_too_small_to_mean_anything_is_skipped() -> None:
    """Bon nguoi ma ba nguoi dong y thi ra 75 %, va con so do khong noi gi ca."""
    frame = pd.DataFrame(
        {
            "poutcome": ["success"] * (MIN_GROUP_ROWS - 1) + ["failure"] * 10,
            "y": ["yes"] * (MIN_GROUP_ROWS - 1) + ["no"] * 10,
        }
    )
    found = compute_metrics(frame, dimensions=("poutcome", "y"))
    assert "y.yes.share_pct.by.poutcome.success" not in found
    assert "y.no.share_pct.by.poutcome.failure" in found


def test_an_outcome_with_many_values_is_not_crossed() -> None:
    """ "Nhom nao co ty le cao nhat" la cau hoi ve mot ket qua co/khong.

    Voi mot cot muoi gia tri thi no khong con la mot cau hoi, va so chi so sinh
    ra bung len theo cap so nhan.
    """
    frame = pd.DataFrame(
        {
            "nhom": ["a"] * 10 + ["b"] * 10,
            "nhieu_gia_tri": [f"v{index % 5}" for index in range(20)],
        }
    )
    found = compute_metrics(frame, dimensions=("nhom", "nhieu_gia_tri"))
    assert not any("nhieu_gia_tri." in key and ".share_pct.by." in key for key in found)


def test_a_column_is_never_crossed_with_itself() -> None:
    found = compute_metrics(_bank(), dimensions=("poutcome", "y"))
    assert not any(".by.y." in key and key.startswith("y.") for key in found)


def test_a_table_with_one_dimension_produces_no_cross_tab() -> None:
    frame = pd.DataFrame({"y": ["yes"] * 10 + ["no"] * 10})
    found = compute_metrics(frame, dimensions=("y",))
    assert not any(".share_pct.by." in key for key in found)


def test_the_ordinary_metrics_are_still_there() -> None:
    # Them mot phep do khong duoc lam mat cac phep do cu.
    found = compute_metrics(_bank(), dimensions=("poutcome", "y"))
    assert "y.yes.share_pct" in found
    assert "campaign.mean.by.poutcome.success" in found
