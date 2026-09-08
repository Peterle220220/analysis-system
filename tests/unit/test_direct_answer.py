"""Cau tra loi thang, dung truoc moi bang chung.

Chu he thong doc mot trang toan so lieu dung va khong thay cau tra loi dau:
"he thong dang hanh xu giong mot co may in bao cao thong ke hon la mot chuyen
gia phan tich". Chan doan di kem cung dung: cac lop chong bia so da ep Manager
lam viec TU DUOI LEN - dich tung phep do thanh mot gach dau dong roi dung.

Bai nay giu dung mot ranh gioi: NOI ve cau chu, KHONG noi ve so.
"""

from __future__ import annotations

from analysis_system.contracts.agents import ClaimEvidence, ManagerAnswer, MetricValue
from analysis_system.services.direct_answer import MAX_LENGTH, problems_with, usable
from analysis_system.services.findings import render_text
from analysis_system.web.render import _direct_answer

DO_DUOC = {
    "y.yes.share_pct.by.poutcome.success": MetricValue(
        key="y.yes.share_pct.by.poutcome.success", value=65.11, unit="%", source="x"
    ),
    "campaign.mean.by.y.yes": MetricValue(
        key="campaign.mean.by.y.yes", value=2.05, unit="", source="x"
    ),
}


# --- noi ve cau chu -----------------------------------------------------------


def test_a_plain_sentence_with_no_metric_key_is_allowed() -> None:
    """Mot cau chot nhu day khong co con so nao de dan, va ep no dan la ep no
    noi vong."""
    assert usable("poutcome ảnh hưởng mạnh hơn campaign tới tỷ lệ mở sổ.", DO_DUOC)


def test_saying_there_is_not_enough_data_is_allowed() -> None:
    assert usable("Chưa đủ dữ liệu để nói yếu tố nào mạnh hơn.", DO_DUOC)


def test_a_sentence_may_still_carry_a_number_through_a_placeholder() -> None:
    said = "Nhóm success dẫn đầu với {y.yes.share_pct.by.poutcome.success}."
    assert usable(said, DO_DUOC)
    assert "65.11 %" in render_text(said, DO_DUOC)


# --- KHONG noi ve so ----------------------------------------------------------


def test_a_typed_number_is_still_refused() -> None:
    """Day la cho duoc doc nhieu nhat trang, nen la cho te nhat de mot con so
    bia lot qua."""
    faults = problems_with("Nhóm success dẫn đầu với 65.11 %.", DO_DUOC)
    assert faults
    assert "go truc tiep" in faults[0]


def test_a_placeholder_naming_a_metric_that_does_not_exist_is_refused() -> None:
    faults = problems_with("Dẫn đầu là {khong.co.that}.", DO_DUOC)
    assert any("khong co that" in fault for fault in faults)


def test_an_empty_summary_is_not_usable() -> None:
    assert not usable("", DO_DUOC)
    assert not usable("   ", DO_DUOC)


def test_a_summary_that_runs_on_is_refused() -> None:
    # Dai hon thi no khong con la mot cau chot, no la mot doan nua - va ca van
    # de o day la nguoi doc co MOT cau de doc truoc khi doc moi thu.
    assert not usable("a" * (MAX_LENGTH + 1), DO_DUOC)


def test_a_group_label_carrying_a_digit_is_not_a_typed_number() -> None:
    """Cung mot phep tru "nhan cua chinh du lieu" nhu moi luan diem khac."""
    metrics = {
        "y.yes.share_pct.by.age.dưới_30": MetricValue(
            key="y.yes.share_pct.by.age.dưới_30", value=10.0, unit="%", source="x"
        )
    }
    assert usable("Nhóm dưới 30 dẫn đầu.", metrics)


# --- hien ra trang ------------------------------------------------------------


def test_it_is_shown_when_there_is_one() -> None:
    answer = ManagerAnswer(
        question="Cau hoi",
        summary="poutcome ảnh hưởng mạnh hơn campaign.",
        claims=(ClaimEvidence(claim="Mot luan diem.", metric_keys=("a.mean",)),),
    )
    shown = _direct_answer(answer)
    assert "poutcome ảnh hưởng mạnh hơn" in shown
    assert "Trả lời" in shown


def test_nothing_is_shown_when_there_is_no_summary() -> None:
    # Mot khoi rong trong y het mot cho he thong quen dien.
    assert _direct_answer(ManagerAnswer(question="Cau hoi")) == ""


# --- cau hoi doi con so thi cau chot phai co con so ---------------------------

CAU_DEM = (
    "Trong tap du lieu, co bao nhieu cong ty bi pha san va bao nhieu cong ty "
    "khong pha san? Ty le pha san chiem bao nhieu phan tram?"
)


def test_a_summary_that_answers_with_the_numbers_is_left_alone() -> None:
    from analysis_system.services.direct_answer import misses_the_number

    said = "Co 220 cong ty pha san va 6.599 cong ty khong pha san, chiem 3.23 %."
    assert misses_the_number(CAU_DEM, said) == ""


def test_a_summary_that_dodges_the_number_is_reported() -> None:
    """Chu he thong phai noi lai hai lan: cau tra loi truoc tien va kien quyet
    phai giai dap duoc cau hoi."""
    from analysis_system.services.direct_answer import misses_the_number

    said = "Ty le pha san la nho, chi tiet o cac ket luan ben duoi."
    assert misses_the_number(CAU_DEM, said)


def test_the_warning_reaches_the_top_of_the_page() -> None:
    from analysis_system.services.direct_answer import misses_the_number
    from analysis_system.services.risk_notes import is_risk

    assert is_risk(misses_the_number(CAU_DEM, "Ty le nho."))


def test_a_question_not_asking_for_a_number_is_left_alone() -> None:
    from analysis_system.services.direct_answer import misses_the_number

    assert misses_the_number("Yeu to nao anh huong manh hon?", "poutcome manh hon.") == ""


def test_an_empty_summary_is_left_to_the_other_check() -> None:
    from analysis_system.services.direct_answer import misses_the_number

    assert misses_the_number(CAU_DEM, "") == ""
