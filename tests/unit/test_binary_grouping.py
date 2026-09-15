"""Cot co 0/1 phai dung duoc lam cot chia nhom, va ten cot nhieu chu phai khop.

Hai cho hong lam cap do 2 khong ra duoc mot phep kiem nao.

1. `_kinds` gap mot cot so thi `continue` ngay, nen no khong bao gio duoc xet
   lam cot nhom. Cot co 0/1 la cach pho bien nhat de danh dau mot nhom, va
   `Bankrupt?` chinh la mot cot nhu the. Hoi "giua hai nhom pha san va khong
   pha san co khac biet khong", he thong tra ve KHONG MOT phep so sanh nao.

2. `named_in` so CA TEN COT nhu mot tu, nen moi ten cot nhieu chu deu vo hinh.
   Bo ngan hang co cot mot tu (`Source`, `Duration`) nen no chay duoc; bo nay
   co ` ROA(C) before interest and depreciation before interest`, va cau hoi
   viet `ROA(C)` thi khong khop gi ca - he thong chon tam cot dau bang chu cai
   va bo dung hai cot duoc hoi.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from analysis_system.domains.ai_planner.shortlist import named_in
from analysis_system.domains.execution_engine.statistics import suggest_spec

rng = np.random.default_rng(0)


def _bang() -> pd.DataFrame:
    rows = 200
    return pd.DataFrame(
        {
            "Bankrupt?": [1] * 40 + [0] * (rows - 40),
            " ROA(C) before interest and depreciation before interest": rng.normal(size=rows),
            " Debt ratio %": rng.normal(size=rows),
            " Operating Gross Margin": rng.normal(size=rows),
            " Cash flow rate": rng.normal(size=rows),
        }
    )


# --- cot co 0/1 lam duoc cot nhom ---------------------------------------------


def test_a_zero_one_column_can_group() -> None:
    spec, _ = suggest_spec(_bang(), question="co khac biet gi giua hai nhom khong")
    assert spec.group_differences


def test_the_flag_column_is_the_one_grouping() -> None:
    spec, _ = suggest_spec(_bang(), question="co khac biet gi giua hai nhom khong")
    assert any(group == "Bankrupt?" for _, group in spec.group_differences)


def test_a_column_is_never_compared_with_itself() -> None:
    """Mot cot vua la so vua la nhom thi no nam ca hai ben, va so no voi chinh
    no la mot phep kiem luon 'co y nghia' ma khong noi gi."""
    spec, _ = suggest_spec(_bang(), question="khac biet giua hai nhom")
    assert all(measure != group for measure, group in spec.group_differences)


def test_a_continuous_column_is_not_treated_as_a_group() -> None:
    # Hai tram gia tri khac nhau thi khong phai hai nhom.
    frame = pd.DataFrame({"gia": rng.normal(size=200), "khac": rng.normal(size=200)})
    spec, _ = suggest_spec(frame, question="khac biet giua cac nhom")
    assert not spec.group_differences


# --- ten cot nhieu chu phai khop ----------------------------------------------


CAU_HOI = (
    "ty suat loi nhuan tren tai san (ROA(C)) va ty le no (Debt ratio %) "
    "co su khac biet co y nghia thong ke khong"
)
COT = [
    " ROA(C) before interest and depreciation before interest",
    " Debt ratio %",
    " Operating Gross Margin",
    " Cash flow rate",
    "Bankrupt?",
]


def test_a_multi_word_column_is_found_by_a_telling_word() -> None:
    found = named_in(CAU_HOI, COT)
    assert " ROA(C) before interest and depreciation before interest" in found
    assert " Debt ratio %" in found


def test_a_column_the_question_never_mentions_is_not_found() -> None:
    found = named_in(CAU_HOI, COT)
    assert " Cash flow rate" not in found


def test_a_word_shared_by_many_columns_does_not_match_them_all() -> None:
    """`interest`, `rate`, `ratio` nam trong hang chuc cot cua cung mot bang -
    khop theo chung thi cau hoi nao cung goi ten moi cot."""
    many = [f" Interest rate of type {index}" for index in range(20)]
    found = named_in("interest rate the nao", [*many, " Debt ratio %"])
    assert len(found) < len(many)


def test_a_single_word_column_still_matches_as_before() -> None:
    # Bo ngan hang chay duoc nho duong nay, va no khong duoc hong.
    assert named_in("kenh thong tin Source nao pho bien", ["Source", "Duration"]) == {"Source"}


def test_nothing_in_means_nothing_out() -> None:
    assert named_in("", COT) == set()
    assert named_in(CAU_HOI, []) == set()


# --- cum dai hon thang cum ngan hon -------------------------------------------

# Nguoi dung go ROA(C), khong go ca cai ten dai. Trong bang chi co MOT cot mang
# dung cum ay, nen he thong phai hieu ho nham toi cot nao.
HO_ROA = [
    " ROA(A) before interest and % after tax",
    " ROA(B) before interest and depreciation after tax",
    " ROA(C) before interest and depreciation before interest",
    " Debt ratio %",
    " Cash flow rate",
    "Bankrupt?",
]


def test_naming_one_of_a_family_picks_only_that_one() -> None:
    found = named_in("ROA(C) va Debt ratio % co khac biet khong", HO_ROA)
    assert " ROA(C) before interest and depreciation before interest" in found
    assert " ROA(A) before interest and % after tax" not in found


def test_the_other_column_asked_about_is_kept_too() -> None:
    found = named_in("ROA(C) va Debt ratio % co khac biet khong", HO_ROA)
    assert " Debt ratio %" in found


def test_naming_the_family_alone_keeps_the_whole_family() -> None:
    """Mo ho thi giu ca ba - luc do cau hoi that su chua chi ro, va chon ho mot
    cai la doan."""
    found = named_in("chi so ROA co khac biet giua hai nhom khong", HO_ROA)
    assert len([name for name in found if "ROA" in name]) == 3


def test_a_stray_percent_sign_does_not_make_two_columns_look_alike() -> None:
    """Ban dau so chuoi tho, va ROA(A) khop voi cau hoi ve ROA(C) chi vi dau phan
    tram cua no cung nam trong cau."""
    found = named_in("Debt ratio % the nao", HO_ROA)
    assert " ROA(A) before interest and % after tax" not in found


def test_a_question_naming_nothing_matches_nothing() -> None:
    assert named_in("phan tich giup toi", HO_ROA) == set()
