"""Canh bao do tin cay: code loc ra, khong nho model nho.

Truoc day chung nam lan trong `khong_xac_lap_duoc` kem mot loi dan trong prompt
- "neu no cham toi cau hoi thi PHAI noi ro". Loi dan trong prompt la thu du an
nay da do la khong an thua: cung mot prompt ghi "tuyet doi khong go so truc
tiep" va model van go, nam lan trong bon luot chay.
"""

from __future__ import annotations

import pytest

from analysis_system.services.risk_notes import is_risk, risks

# Nguyen van cac dong da hien ra tren man hinh cua chu he thong.
THAT = [
    "Debentures theo Avenue: bỏ qua 1 nhóm có dưới 5 dòng, quá ít để nói gì",
    "Mutual_Funds theo Investment_Avenues: còn dưới hai nhóm đủ lớn, không so sánh được",
    "so ~ ma: chỉ có 3 cặp dữ liệu, cần ít nhất 8",
]

# Cung nam trong `khong_xac_lap_duoc`, nhung la chuyen KHAC: he thong tu gioi
# han de tranh p-hacking, hay dang cho nguoi dung khai cau hinh.
KHONG_PHAI = [
    "Có 28 cặp số có thể đo tương quan, chỉ chạy 8 cặp, càng nhiều phép kiểm "
    "thì càng dễ có p_value nhỏ ra do ngẫu nhiên.",
    "Không tự chạy hồi quy, chọn biến giải thích là một nhận định.",
    "Bảng có 633 chỉ số, chỉ đưa 351 cái liên quan nhất vào phân tích.",
]


@pytest.mark.parametrize("line", THAT)
def test_a_line_about_thin_data_is_a_risk(line: str) -> None:
    assert is_risk(line)


@pytest.mark.parametrize("line", KHONG_PHAI)
def test_a_line_about_scope_is_not_a_risk(line: str) -> None:
    """Gop chung lai thi nguoi doc thoi doc ca cum.

    "He thong tu gioi han de tranh ket luan sai" la he thong lam dung viec; no
    khong noi gi ve do tin cay cua con so dang duoc doc.
    """
    assert not is_risk(line)


def test_only_the_risks_come_back() -> None:
    found = risks([*THAT, *KHONG_PHAI])
    assert len(found) == len(THAT)
    assert all(line in THAT for line in found)


def test_the_same_warning_twice_is_kept_once() -> None:
    # Cung mot canh bao hay di ra tu nhieu phep kiem. Doc lai lan thu nam khong
    # them duoc gi va lam nguoi ta thoi doc ca cum.
    line = "bỏ qua 1 nhóm có dưới 5 dòng, quá ít để nói gì"
    assert risks([line, line, line]) == (line,)


def test_the_order_is_kept() -> None:
    assert risks(THAT) == tuple(THAT)


def test_a_line_written_without_diacritics_is_still_caught() -> None:
    # Cac dong nay den tu nhieu tang, va khong phai tang nao cung giu dau.
    assert is_risk("bo qua 2 nhom co duoi 5 dong - qua it de noi gi")


def test_nothing_in_means_nothing_out() -> None:
    assert risks([]) == ()
    assert risks(["", "   "]) == ()
