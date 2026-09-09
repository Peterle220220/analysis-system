"""So viet theo kieu Viet Nam: dau CHAM tach hang nghin.

"2.000" la hai nghin. pandas doc no la 2.0. Ca cot deu viet kieu do thi 100%
gia tri ep duoc - ty le thanh cong KHONG bat duoc loi nay - va moi con so bi
chia cho 1000 trong im lang.

Do duoc tren mot cot tien nam dong: tong dung 141.750, he thong bao 141,75.

Day khong phai chuyen lam tron. Do la sai gap 1000 lan, tren mot con so co
nguon dan duoc, trong mot cau tra loi tu tin - dung loai loi ca du an nay dung
len de tranh.

Huong xu ly la DUNG LAI VA NOI, khong phai doan. "1.000" co the la mot nghin,
cung co the la mot phay khong-khong-khong; hai cach hieu lech nhau 1000 lan nen
khong ai duoc doan ho nguoi dung.
"""

from __future__ import annotations

import pandas as pd

from analysis_system.services.rulebook import RuleSpec, apply_rules


def _cast(**columns: list[str]) -> tuple[pd.DataFrame, list[str]]:
    frame = pd.DataFrame(columns)
    outcome = apply_rules(frame, [RuleSpec(rule_id="cast_numeric_safe", columns=())])
    return outcome.frame, [entry.reason for entry in outcome.diff]


def _refused(reasons: list[str]) -> bool:
    return any("kieu Viet Nam" in reason for reason in reasons)


# --- cho phai dung lai ----------------------------------------------------------


def test_a_money_column_written_the_vietnamese_way_is_not_silently_divided() -> None:
    frame, _ = _cast(doanh_thu=["1.000", "2.000", "15.500", "3.250", "120.000"])
    # Giu nguyen chu KHONG thanh 1.0, 2.0, 15.5...
    assert list(frame["doanh_thu"]) == ["1.000", "2.000", "15.500", "3.250", "120.000"]


def test_it_says_why_rather_than_going_quiet() -> None:
    _, reasons = _cast(doanh_thu=["1.000", "2.000", "15.500"])
    assert _refused(reasons)


def test_the_reason_names_the_two_readings() -> None:
    # Nguoi doc phai hieu duoc minh dang duoc hoi gi.
    _, reasons = _cast(doanh_thu=["1.000", "2.000"])
    said = next(reason for reason in reasons if "kieu Viet Nam" in reason)
    assert "1000 lan" in said


def test_two_dots_leave_no_room_for_argument() -> None:
    """ "1.234.567" khong the la mot so thap phan."""
    _, reasons = _cast(doanh_thu=["1.234.567", "890", "12"])
    assert _refused(reasons)


# --- cho KHONG duoc dung lai ------------------------------------------------------


def test_ordinary_decimals_still_cast() -> None:
    """Chan ca du lieu binh thuong thi phep kiem khong an toan, chi vo dung."""
    frame, reasons = _cast(ty_le=["0.370594257300249", "0.464290937454297"])
    assert not _refused(reasons)
    assert pd.api.types.is_numeric_dtype(frame["ty_le"])


def test_a_rounded_ratio_starting_with_zero_still_casts() -> None:
    # "0.370" co ba chu so sau dau cham, nhung "0370" khong phai mot cach viet
    # so nao ca - nen no khong mo ho.
    frame, reasons = _cast(ty_le=["0.370", "0.464", "0.426"])
    assert not _refused(reasons)
    assert pd.api.types.is_numeric_dtype(frame["ty_le"])


def test_plain_integers_still_cast() -> None:
    frame, reasons = _cast(so_luong=["1", "2", "3"])
    assert not _refused(reasons)
    assert pd.api.types.is_numeric_dtype(frame["so_luong"])


def test_a_column_of_text_is_untouched_as_before() -> None:
    frame, _ = _cast(ghi_chu=["a", "b", "c"])
    assert list(frame["ghi_chu"]) == ["a", "b", "c"]


def test_an_empty_column_does_not_crash() -> None:
    frame, reasons = _cast(trong=["", "", ""])
    assert not _refused(reasons)
    assert frame is not None


def test_a_mixed_column_is_judged_on_the_values_it_has() -> None:
    """Mot gia tri dang `n.000` lan giua so binh thuong khong du de ket luan."""
    _, reasons = _cast(so=["1.000", "5", "7", "9", "11", "13"])
    assert not _refused(reasons)
