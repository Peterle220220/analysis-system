"""Bang chu giai phai lai duoc ca tang chon phep kiem, khong chi tang canh bao.

Cap do 4 hoi bang tieng Viet - "toc do tang truong doanh thu" - tren mot bang co
cot tieng Anh `... Growth Rate`. Khong mot chu nao trung, nen `named_in` khong
khop duoc gi va he thong di do tam cot dau bang chu cai.

O Boi canh sinh ra dung de bac cau cho nay. Nhung tang chon phep kiem chua bao
gio duoc dua no.

Hai cho hong nua lo ra khi thu:

* bo doc chu giai chi nhan ten cot KHONG CO DAU CACH, ma hau het ten cot that
  deu co dau cach, ngoac, hoac dau phan tram;
* `parse_glossary` cat khoang trang hai dau, con ten cot that co the mang mot
  dau cach vo hinh o dau - lech dung mot ky tu khong ai nhin thay.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from analysis_system.domains.execution_engine.statistics import suggest_spec
from analysis_system.services.asked_columns import named_by, parse_glossary

rng = np.random.default_rng(0)

COT_TANG_TRUONG = " Revenue Growth Rate"
CAU_HOI = "cong ty co toc do tang truong doanh thu cao thi khong the pha san, dung khong"
CHU_GIAI = f"{COT_TANG_TRUONG} = toc do tang truong doanh thu"


def _bang(rows: int = 300) -> pd.DataFrame:
    data: dict[str, object] = {f"aa_khac_{index:02d}": rng.normal(size=rows) for index in range(10)}
    data[COT_TANG_TRUONG] = rng.normal(size=rows)
    data["Bankrupt?"] = [1] * 40 + [0] * (rows - 40)
    return pd.DataFrame(data)


# --- bo doc chu giai -----------------------------------------------------------


def test_a_column_name_with_spaces_can_be_glossed() -> None:
    """Hau het ten cot that deu co dau cach."""
    assert parse_glossary("Total Asset Growth Rate = toc do tang truong") == {
        "Total Asset Growth Rate": "toc do tang truong"
    }


def test_a_column_name_with_brackets_and_percent_can_be_glossed() -> None:
    found = parse_glossary("ROA(A) before interest and % after tax = ty suat loi nhuan")
    assert "ROA(A) before interest and % after tax" in found


def test_prose_with_no_equals_sign_is_still_ignored() -> None:
    assert parse_glossary("Ghi chu: du lieu thu thap nam 2020") == {}


def test_an_invisible_leading_space_does_not_break_the_lookup() -> None:
    """Khoa va cot lech dung mot ky tu khong ai nhin thay."""
    found = named_by(CAU_HOI, [COT_TANG_TRUONG], parse_glossary(CHU_GIAI))
    assert COT_TANG_TRUONG in found


# --- chu giai lai duoc tang chon phep kiem -------------------------------------


def test_with_a_glossary_the_growth_column_is_compared_by_the_flag() -> None:
    spec, _ = suggest_spec(_bang(), question=CAU_HOI, context=CHU_GIAI)
    assert any(
        measure == COT_TANG_TRUONG and group == "Bankrupt?"
        for measure, group in spec.group_differences
    )


def test_the_glossary_is_optional() -> None:
    # Khong khai thi he thong van chay y nhu truoc.
    spec, _ = suggest_spec(_bang(), question=CAU_HOI, context="")
    assert spec is not None


def test_a_glossary_naming_no_real_column_changes_nothing() -> None:
    """Mot dong rac chi nam do chu khong tro toi dau."""
    # MOT bang cho ca hai lan so.  rut so ngau nhien moi moi lan goi, va
    # tu khi so sanh nhom xep theo do tach nhom, hai bang khac so thi ra khac thu
    # tu - test se do su khac nhau giua hai bang, khong phai cua dong chu giai rac.
    frame = _bang()
    without, _ = suggest_spec(frame, question=CAU_HOI)
    with_junk, _ = suggest_spec(frame, question=CAU_HOI, context="khong_co_cot_nay = gi do")
    assert without.group_differences == with_junk.group_differences
