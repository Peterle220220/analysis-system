"""Tam phep so sanh nhom chay tren tam cap TACH NHOM RO NHAT, khong phai tam cap
dau bang chu cai.

Chu he thong da chi ra loi nay o cap do 3 cho tuong quan ("loi nguyen boc tam
bien"), va no duoc sua - nhung chi cho tuong quan. So sanh nhom van xep theo ten
cot. Do tren bang pha san, hoi "hai nhom khac nhau o chi so nao":

    he thong chon     Accounts Receivable Turnover   hang 81/94
                      After-tax net Interest Rate    hang 73/94
                      Average Collection Days        hang 77/94
                      Borrowing dependency           hang 14/94
    tach ro nhat      Net Income to Total Assets, ROA(A), ROA(B), ROA(C), Debt ratio %

Cai bi gioi han van la SO PHEP KIEM. Chi doi phep nao duoc chay.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from analysis_system.services.statistics import MAX_SUGGESTED, _separation, suggest_spec

rng = np.random.default_rng(0)


def _bang(rows: int = 400) -> pd.DataFrame:
    """Hai muoi cot nhieu dat dau bang chu cai, va MOT cot tach nhom that dat cuoi."""
    nhom = np.array([1] * 60 + [0] * (rows - 60))
    data = {f"aa_nhieu_{index:02d}": rng.normal(size=rows) for index in range(20)}
    data["zz_tach_nhom"] = nhom * 3.0 + rng.normal(scale=0.3, size=rows)
    data["pha_san"] = nhom
    return pd.DataFrame(data)


def _so_sanh(frame: pd.DataFrame, question: str = "hai nhóm khác nhau ở chỉ số nào") -> list[str]:
    spec, _ = suggest_spec(frame, question=question)
    return [measure for measure, group in spec.group_differences if group == "pha_san"]


def test_the_column_that_really_separates_the_groups_is_compared() -> None:
    """Cot tach nhom nam cuoi bang chu cai, nen thu tu cu bo qua no."""
    assert "zz_tach_nhom" in _so_sanh(_bang())


def test_it_is_compared_first() -> None:
    assert _so_sanh(_bang())[0] == "zz_tach_nhom"


def test_a_column_the_question_names_still_comes_first() -> None:
    """Y nguoi hoi thang do tach nhom."""
    assert _so_sanh(_bang(), "aa_nhieu_07 có khác giữa hai nhóm không")[0] == "aa_nhieu_07"


def test_the_number_of_comparisons_is_unchanged() -> None:
    spec, _ = suggest_spec(_bang(), question="phân tích")
    assert len(spec.group_differences) <= MAX_SUGGESTED


def test_the_note_says_they_were_chosen_for_separating_best() -> None:
    """Chon vi tach ro nhat thi p_value lac quan hon thuc te - nguoi doc phai biet."""
    _, notes = suggest_spec(_bang(), question="phân tích")
    assert any("tách nhóm rõ nhất" in note and "lạc quan" in note for note in notes)


# --- chinh thuoc do ------------------------------------------------------------


def test_a_column_that_separates_well_scores_high() -> None:
    assert _separation(_bang(), "zz_tach_nhom", "pha_san") > 0.5


def test_noise_scores_low() -> None:
    assert _separation(_bang(), "aa_nhieu_00", "pha_san") < 0.1


def test_a_constant_column_scores_zero_not_an_error() -> None:
    frame = pd.DataFrame({"hang_so": [1.0] * 10, "nhom": [0, 1] * 5})
    assert _separation(frame, "hang_so", "nhom") == 0.0


def test_missing_values_do_not_break_it() -> None:
    frame = pd.DataFrame({"so": [1.0, None, 3.0, 4.0, None, 6.0], "nhom": [0, 0, 0, 1, 1, 1]})
    assert 0.0 <= _separation(frame, "so", "nhom") <= 1.0


def test_a_missing_column_scores_zero() -> None:
    frame = pd.DataFrame({"so": [1.0, 2.0], "nhom": [0, 1]})
    assert _separation(frame, "khong_co", "nhom") == 0.0


def test_text_groups_work_too() -> None:
    """Khong rieng cot 0/1 - mot cot nhom dang chu cung phai dung duoc."""
    frame = pd.DataFrame(
        {"so": [1.0, 1.1, 0.9, 5.0, 5.1, 4.9], "vung": ["Bắc", "Bắc", "Bắc", "Nam", "Nam", "Nam"]}
    )
    assert _separation(frame, "so", "vung") > 0.9
