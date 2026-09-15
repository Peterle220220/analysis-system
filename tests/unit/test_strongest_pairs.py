"""Tam phep kiem chay tren tam cap DANG NHIN NHAT, khong phai tam cap dau bang
chu cai.

Chu he thong tu quet ca ma tran 95x95 bang Python va tim ra cap nghich manh
nhat that su la `Net worth/Assets` voi `Debt ratio %`, gan -1.0. He thong bao
cap manh nhat la -0.117 - va noi ro no chi quet mot mau nho.

Trung thuc, va dung. Nhung mau nho ay khong can phai la mau dau bang chu cai.

Xep hang theo do lon KHONG phai mot phep kiem - no la mot phep quet mo ta, va
tren bang 96 cot no chay het 0,14 giay. Cai bi gioi han van la SO PHEP KIEM.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from analysis_system.domains.execution_engine.statistics import MAX_SUGGESTED, suggest_spec

rng = np.random.default_rng(0)


def _bang(cols: int = 20, rows: int = 400) -> pd.DataFrame:
    """Mot bang co dung MOT cap that su lien quan, dat o cuoi bang chu cai."""
    data = {f"aa_nhieu_{index:02d}": rng.normal(size=rows) for index in range(cols)}
    goc = rng.normal(size=rows)
    data["zz_no"] = goc
    data["zz_von"] = -goc + rng.normal(scale=0.01, size=rows)
    return pd.DataFrame(data)


def test_the_strongest_pair_is_among_those_tested() -> None:
    """Cap manh nhat nam cuoi bang chu cai, nen thu tu cu se bo qua no."""
    spec, _ = suggest_spec(_bang(), question="cap nao lien quan manh nhat")
    assert any({left, right} == {"zz_no", "zz_von"} for left, right in spec.correlations)


def test_it_is_tested_first() -> None:
    spec, _ = suggest_spec(_bang(), question="cap nao lien quan manh nhat")
    assert {spec.correlations[0][0], spec.correlations[0][1]} == {"zz_no", "zz_von"}


def test_the_number_of_tests_is_unchanged() -> None:
    """Cai bi gioi han la SO PHEP KIEM, va no khong duoc noi ra."""
    spec, _ = suggest_spec(_bang(), question="phan tich")
    assert len(spec.correlations) <= MAX_SUGGESTED


def test_the_columns_the_question_names_still_come_first() -> None:
    """Y nguoi hoi thang do lon.

    Cau hoi phai hoi ve moi quan he thi moi co tuong quan de xep (chu he thong chot,
    2026-09-15); "lien quan" hoi quan he ma khong goi dich danh mot cap.
    """
    spec, _ = suggest_spec(_bang(), question="aa_nhieu_03 lien quan the nao voi cac cot khac")
    assert any("aa_nhieu_03" in pair for pair in spec.correlations[:2])


def test_the_note_says_the_pairs_were_chosen_for_being_strong() -> None:
    """Chon vi manh nhat thi p_value lac quan hon thuc te, va nguoi doc phai
    biet dieu do."""
    _, notes = suggest_spec(_bang(), question="cac cot lien quan voi nhau the nao")
    assert any("lạc quan" in note for note in notes)


def test_a_question_that_asks_no_relationship_tests_no_pairs() -> None:
    """Khong hoi ve moi quan he thi khong do tuong quan (chu he thong chot, 2026-09-15)."""
    spec, _ = suggest_spec(_bang(), question="phan tich")
    assert spec.correlations == ()


def test_a_table_with_nothing_to_correlate_does_not_crash() -> None:
    frame = pd.DataFrame({"a": [1.0] * 50, "b": ["x"] * 50})
    spec, _ = suggest_spec(frame, question="phan tich")
    assert spec is not None


def test_a_table_of_two_columns_still_works() -> None:
    frame = pd.DataFrame({"a": rng.normal(size=50), "b": rng.normal(size=50)})
    spec, _ = suggest_spec(frame, question="phan tich")
    assert len(spec.correlations) <= 1
