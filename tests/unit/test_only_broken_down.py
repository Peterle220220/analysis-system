"""Hoi mot con so cho ca nhom, ma chi nhan duoc so cua cac nhom con.

Loi that, tren bo du lieu tiep thi ngan hang. Chu he thong hoi:

    Ty le khach hang dong y mo so (y = 'yes') trong nhom sinh vien
    (job = 'student') la bao nhieu? Chi tinh nhung nguoi da tung duoc lien he
    trong chien dich truoc (previous > 0).

Code loc dung 281 dong va DA DO `is_yes.mean = 0.452`. Cau tra loi lai la "phan
nhom co chien dich truoc thanh cong dat 0.71, cao hon nhom that bai" - dung, dan
nguon duoc, va tra loi mot cau khong ai hoi.

Lop kiem dang cau tra loi cho qua, vi `is_yes.mean.by.poutcome.success` co chu
`.mean` nen tinh la mot con so. Nhung `.by.` la CHIA NHO.

Nua tren cua bai nay la cac cho phai im lang.
"""

from __future__ import annotations

from analysis_system.domains.ai_planner.answer_shape import only_broken_down
from analysis_system.domains.ai_planner.risk_notes import is_risk

CAU_HOI = (
    "Tỷ lệ khách hàng đồng ý mở sổ (y = 'yes') trong nhóm sinh viên "
    "(job = 'student') là bao nhiêu? Chỉ tính những người đã từng được liên hệ "
    "trong chiến dịch trước (previous > 0)."
)

CHIA_NHO = ["is_yes.mean.by.poutcome.success", "is_yes.mean.by.poutcome.failure"]
DA_DO = ["is_yes.mean", "is_yes.sum", *CHIA_NHO]


# --- phai im lang -------------------------------------------------------------


def test_an_answer_that_gives_the_headline_number_is_left_alone() -> None:
    assert only_broken_down(CAU_HOI, ["is_yes.mean"], DA_DO) == ""


def test_one_headline_number_among_the_breakdowns_is_enough() -> None:
    assert only_broken_down(CAU_HOI, ["is_yes.mean", *CHIA_NHO], DA_DO) == ""


def test_a_question_that_asks_for_a_breakdown_is_left_alone() -> None:
    """Co "theo tung" thi mot chi so `.by.` chinh la cau tra loi."""
    assert only_broken_down("tỷ lệ đồng ý theo từng nhóm nghề là bao nhiêu", CHIA_NHO, DA_DO) == ""


def test_a_question_that_asks_to_compare_is_left_alone() -> None:
    assert only_broken_down("tỷ lệ nhóm A so với nhóm B là bao nhiêu", CHIA_NHO, DA_DO) == ""


def test_a_question_not_asking_for_a_number_is_left_alone() -> None:
    assert only_broken_down("vì sao khách hàng từ chối", CHIA_NHO, DA_DO) == ""


def test_it_stays_quiet_when_the_headline_was_never_measured() -> None:
    """Khong co cai de noi thi khong noi. Bao thieu mot con so chua tung do
    duoc chi lam nguoi doc di tim mot thu khong ton tai."""
    assert only_broken_down(CAU_HOI, CHIA_NHO, CHIA_NHO) == ""


def test_nothing_cited_means_nothing_said() -> None:
    assert only_broken_down(CAU_HOI, [], DA_DO) == ""


# --- phai len tieng -----------------------------------------------------------


def test_the_real_case_is_caught() -> None:
    said = only_broken_down(CAU_HOI, CHIA_NHO, DA_DO)
    assert "is_yes.mean" in said
    assert "chia nhỏ" in said


def test_it_names_the_measured_number_the_reader_should_have_been_given() -> None:
    """Noi thieu ma khong noi thieu CAI GI thi nguoi doc khong lam gi duoc."""
    assert "is_yes.mean" in only_broken_down(CAU_HOI, CHIA_NHO, DA_DO)


def test_the_warning_reaches_the_top_of_the_page() -> None:
    assert is_risk(only_broken_down(CAU_HOI, CHIA_NHO, DA_DO))


def test_it_never_removes_a_claim() -> None:
    # Mot chuoi de doc, khong phai mot quyet dinh loai bo.
    assert isinstance(only_broken_down(CAU_HOI, CHIA_NHO, DA_DO), str)
