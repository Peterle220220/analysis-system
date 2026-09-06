"""Cai gi hien ra cho nguoi doc thi phai la tieng Viet CO DAU.

Chu he thong vach dung ranh gioi:

    "viec cac AI worker lam viec giao tiep voi nhau bang tieng viet khong co dau
     thi toi khong noi vi no se chay ngam trong he thong tuy nhien viec xuat ra
     thong tin phai co tieng viet co dau. hien tai thi co cai co co cai khong"

Nen o day khong quet ca ma nguon - phan lon chuoi trong du an la chu noi bo:
ma loi, ten khoa, prompt gui cho model, thong bao cho lap trinh vien. Chi quet
NHUNG DUONG THUC SU CHAY RA MAN HINH:

  * chan doan du lieu -> khoi "He thong da xem du lieu"
  * ly do tu choi cua phan thong ke -> khoi "Khong ket luan duoc"
  * tieu de va cau hoi cua gate -> man duyet
  * don vi cua chi so -> dan thang vao giua cau tra loi

Mot bai kiem tra bang mat da bo sot dung nhung cho nay hai lan, nen no thanh
mot test.
"""

from __future__ import annotations

import re

import pandas as pd
import pytest

from analysis_system.services.diagnosis import examine
from analysis_system.services.statistics import (
    StatisticsSpec,
    compute_statistics,
    suggest_spec,
)

# Tu chi ton tai trong tieng Viet BO DAU. Mot cau nguoi doc ma chua nhung tu nay
# la mot cau chua bo dau.
KHONG_DAU = re.compile(
    r"\b(khong|duoc|nhung|nguoi|nhieu|mot|chay|dong|luan|diem|tren|duoi|kiem"
    r"|tuong|sach|thich|cot|lieu|giua|nen|ket|viet|tieng|cach|truoc|hoi|nhom"
    r"|khoang|trang|thua|chuan|trung|lap|hoan|toan)\b"
)

CO_DAU = re.compile(
    r"[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]",
    re.I,
)


def khong_dau(text: str) -> list[str]:
    """Nhung tu bo dau con sot lai trong mot cau danh cho nguoi doc."""
    return KHONG_DAU.findall(text.lower())


def ban_ban() -> pd.DataFrame:
    """Mot bang du ban de moi phep kiem cua chan doan deu co viec de lam."""
    return pd.DataFrame(
        {
            "ten": ["An ", " Binh", "Chi", "Chi"],
            "tuoi": ["25", "30", "35", "35"],
            "ghi_chu": ["ok", "N/A", "-", "ok"],
        }
    )


def test_the_cleaning_verdict_is_written_with_diacritics() -> None:
    found = examine(ban_ban())
    assert not khong_dau(found.verdict), found.verdict


def test_every_thing_the_examination_says_is_written_with_diacritics() -> None:
    for finding in examine(ban_ban()).findings:
        assert not khong_dau(finding.as_reason()), finding.as_reason()


def test_the_clean_verdict_is_written_with_diacritics() -> None:
    # Duong sach: khac han duong ban, va cung hien ra cho nguoi doc.
    found = examine(pd.DataFrame({"ma": ["A1", "A2", "A3"]}))
    assert not found.needs_cleaning
    assert not khong_dau(found.verdict), found.verdict


def test_an_empty_table_is_reported_with_diacritics() -> None:
    found = examine(pd.DataFrame({"a": []}))
    assert not khong_dau(found.verdict), found.verdict


def test_the_reasons_a_test_was_refused_are_written_with_diacritics() -> None:
    # Day la khoi dai nhat tren man hinh cua nguoi dung: "Khong ket luan duoc".
    frame = pd.DataFrame(
        {
            "so": [1.0, 2.0, 3.0, 4.0],
            "hang": ["x", "x", "y", "y"],
            "ma": ["a", "b", "c", "d"],
        }
    )
    spec = StatisticsSpec(
        correlations=(("so", "ma"),),
        group_differences=(("so", "ma"),),
    )

    _, refused = compute_statistics(frame, spec)

    assert refused, "phai co it nhat mot ly do tu choi de kiem"
    for reason in refused:
        assert not khong_dau(reason), reason


def test_the_notes_about_tests_nobody_asked_for_are_written_with_diacritics() -> None:
    frame = pd.DataFrame(
        {
            "a": [1.0, 2.0, 3.0, 4.0],
            "b": [2.0, 4.0, 6.0, 9.0],
            "nhom": ["x", "x", "y", "y"],
        }
    )
    _, notes = suggest_spec(frame)

    assert notes, "phai co ghi chu de kiem"
    for note in notes:
        assert not khong_dau(note), note


@pytest.mark.parametrize(
    "unit",
    ["dòng", "nhóm", "giờ", "từ", "lần"],
)
def test_the_units_are_written_with_diacritics(unit: str) -> None:
    # Don vi bi dan thang vao giua cau tra loi: "{rows.total} nguoi tham gia"
    # ra thanh "40 dong nguoi tham gia". No la chu nguoi doc, khong phai khoa.
    assert not khong_dau(unit), unit


# --- kiem chinh cai thuoc do ------------------------------------------------------


def test_the_detector_catches_a_sentence_written_without_diacritics() -> None:
    """Mot cai luoi khong bat duoc gi thi khong phai luoi.

    Day dung la cau ma he thong in ra truoc khi sua, nguyen van.
    """
    cu = "Da xem 40 dong tren 24 cot. Tim thay 8 cho can lam sach, o cac cot: age"
    assert khong_dau(cu), "thuoc do bo sot mot cau ro rang la khong dau"


def test_the_detector_lets_proper_vietnamese_through() -> None:
    # "khai", "quan", "so" deu la tieng Viet viet dung ma khong can dau. Mot
    # thuoc do bat nham chung se bat ca he thong viet sai di de chieu no.
    moi = "Không ai khai 'tests' nên hệ thống tự chọn phép kiểm: 0 tương quan, 1 so sánh nhóm."
    assert not khong_dau(moi), khong_dau(moi)


def test_every_user_facing_sentence_carries_at_least_one_diacritic() -> None:
    """Vang mat tu sai chua du - cau phai thuc su duoc viet bang tieng Viet.

    Mot cau chi toan ky hieu va so se qua duoc phep kiem tren ma khong noi len
    dieu gi, nen o day doi them mot dau bat ky.
    """
    verdicts = [
        examine(ban_ban()).verdict,
        examine(pd.DataFrame({"ma": ["A1", "A2", "A3"]})).verdict,
        examine(pd.DataFrame({"a": []})).verdict,
    ]
    for line in verdicts:
        assert CO_DAU.search(line), line
