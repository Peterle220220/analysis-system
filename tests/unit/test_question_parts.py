"""Mot cau hoi go lien mot dong thuong la hai cau hoi.

Chu he thong hoi hai y trong mot dong, va he thong doi xu voi no nhu mot - nen
no tra loi duoc y nay thi bo y kia, va nguoi doc khong co cach nao biet y nao
da duoc tra loi.
"""

from __future__ import annotations

import pytest

from analysis_system.services.question_parts import is_multi, parts

# Nguyen van cau hoi cua chu he thong.
HAI_Y = (
    "Trong tập dữ liệu, có bao nhiêu công ty bị phá sản (Bankrupt? = 1) và bao "
    "nhiêu công ty không phá sản? Tỷ lệ công ty phá sản chiếm bao nhiêu phần "
    "trăm tổng số mẫu?"
)


def test_the_owners_question_splits_into_two() -> None:
    found = parts(HAI_Y)
    assert len(found) == 2
    assert "bao nhiêu công ty" in found[0]
    assert "phần trăm" in found[1]


def test_each_part_keeps_its_question_mark() -> None:
    assert all(part.rstrip().endswith("?") for part in parts(HAI_Y))


def test_a_single_question_stays_whole() -> None:
    """Truong hop thuong gap nhat, va khong tach gi la dung."""
    one = "Nhóm khách hàng nào có tỷ lệ đồng ý cao nhất?"
    assert parts(one) == (one,)
    assert not is_multi(one)


def test_a_question_with_no_mark_is_still_one_question() -> None:
    said = "Hãy phân tích sự khác biệt giữa hai nhóm giới tính"
    assert parts(said) == (said,)


def test_three_parts_come_back_as_three() -> None:
    said = "Có bao nhiêu công ty? Tỷ lệ là bao nhiêu? Nhóm nào cao nhất?"
    assert len(parts(said)) == 3


def test_a_short_tail_belongs_to_the_question_before_it() -> None:
    """ "dung khong?" khong phai mot cau hoi rieng."""
    said = "Gọi càng ngắn thì tỷ lệ chốt càng cao, đúng không?"
    assert len(parts(said)) == 1


def test_a_question_mark_inside_a_column_name_does_not_split_it() -> None:
    """Bo du lieu nay co cot ten `Bankrupt?`, va no nam giua cau."""
    said = "Cột Bankrupt? có bao nhiêu giá trị khác nhau trong bảng dữ liệu này?"
    found = parts(said)
    assert len(found) == 1 or all(len(piece) >= 12 for piece in found)


def test_nothing_in_means_nothing_out() -> None:
    assert parts("") == ()
    assert parts("   ") == ()


def test_a_very_long_list_is_capped() -> None:
    # Mot danh sach muoi y doc len van la mot danh sach muoi y.
    said = " ".join(f"Câu hỏi số {index} là gì?" for index in range(12))
    assert len(parts(said)) <= 6


# --- moi y hoi mot loai khac nhau ---------------------------------------------

# Ba cau hai y, va phan loai CA CAU lam mat mot y o ca ba.  lay
# loai dau tien khop roi dung, nen y thu hai khong bao gio duoc xet - va moi
# lop kiem dua vao loai cau hoi deu mu voi y bi bo do.
HAI_LOAI = [
    ("Nhom nao co ty le cao nhat? Co bao nhieu cong ty trong nhom do?", {"xep hang", "so luong"}),
    ("Vi sao nhom nay cao hon? Ty le chenh lech bao nhieu phan tram?", {"nguyen nhan", "so sanh"}),
    ("Xu huong theo thang the nao? Thang nao cao nhat?", {"xu huong", "xep hang"}),
]


@pytest.mark.parametrize(("cau", "mong_doi"), HAI_LOAI)
def test_each_part_is_classified_on_its_own(cau: str, mong_doi: set[str]) -> None:
    from analysis_system.services.question_parts import demands

    assert demands(cau) == mong_doi


@pytest.mark.parametrize(("cau", "mong_doi"), HAI_LOAI)
def test_classifying_the_whole_question_would_have_lost_a_part(
    cau: str, mong_doi: set[str]
) -> None:
    """Day chinh la cho hong: mot loai duy nhat cho ca cau, va y kia bien mat.

    read_question lay loai dau tien khop roi dung."""
    from analysis_system.services.answer_shape import read_question

    assert {read_question(cau).value} != mong_doi


def test_a_single_question_still_has_one_demand() -> None:
    from analysis_system.services.question_parts import demands

    assert len(demands("Nhom nao co ty le cao nhat?")) == 1


def test_each_part_carries_its_own_text_and_kind() -> None:
    from analysis_system.services.question_parts import asked

    found = asked("Nhom nao cao nhat? Co bao nhieu cong ty?")
    assert found[0].demand == "xep hang"
    assert found[1].demand == "so luong"
    assert "bao nhieu" in found[1].text


def test_the_payload_shape_is_readable() -> None:
    from analysis_system.services.question_parts import asked

    one = asked("Co bao nhieu cong ty pha san?")[0]
    assert set(one.as_payload()) == {"y", "can"}


def test_nothing_in_means_no_demands() -> None:
    from analysis_system.services.question_parts import demands

    assert demands("") == frozenset()
