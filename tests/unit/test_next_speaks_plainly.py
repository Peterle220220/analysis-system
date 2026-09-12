"""Ban Next phai noi bang tieng nguoi y nhu trang Python.

Ban Next viet moi, khong dung chung dong nao voi render.py. Doi chieu tung thu
trang Python dung tu tang services thi ban Next thieu sau thu, trong do nam thu
la ket qua cua feedback truoc day:

* bieu do da dang (cot, tron, duong, so lon) - ban Next chi hien anh PNG cu;
* ly do vang cau tra loi thang - ban Next in thang `blocked[0]`, mot cau may,
  va co khi la ly do chan MOT KET LUAN, tuc la do loi nham cho;
* "da gioi han de tranh ket luan sai" tach khoi "du lieu chua du" - ban Next gop;
* ket luan bi chan vi loai ly do nao - ban Next in cau may tho;
* dong chi danh cho nguoi cau hinh - ban Next hien het.

Cac luat dien giai gio nam o web/state.py, dung chung cho ca hai giao dien.
"""

from __future__ import annotations

from types import SimpleNamespace

from analysis_system.contracts.agents import ManagerAnswer
from analysis_system.services.direct_answer import NO_SUMMARY, why_no_summary
from analysis_system.services.svg_chart import chart_for, pairs_from
from analysis_system.web import render
from analysis_system.web.state import (
    OTHER_NOTES,
    blocked_groups,
    blocked_kind,
    for_operators_only,
    gap_groups,
    kind_of,
)
from analysis_system.web.view import _charts, manager_answer

GO_SO = "cau chot co con so go truc tiep - moi so phai la placeholder {ten_chi_so}"
LOAI_LUAN_DIEM = "ket luan 2 dan chi so khong co that: doanh_thu.mean"
GIOI_HAN = "Có 36 cặp số có thể đo tương quan, chỉ chạy 8 cặp, dễ ngẫu nhiên."
CHUA_DU = "Nhóm B quá ít dòng để so sánh."
CAU_HINH = "Không tự chạy hồi quy, phải được khai rõ trong 'tests.regressions'."


# --- mot ban luat cho hai giao dien -------------------------------------------------


def test_the_python_page_uses_the_same_rules_as_the_next_page() -> None:
    """Hai ban sao cua mot luat la hai cau tra loi dang cho de mau thuan."""
    assert render._kind_of is kind_of
    assert render._blocked_kind is blocked_kind
    assert render.for_operators_only is for_operators_only


# --- ly do vang cau tra loi thang ---------------------------------------------------


def test_a_refused_summary_is_explained_in_plain_words() -> None:
    said = why_no_summary([GO_SO])
    assert "gõ tay" in said
    assert "placeholder" not in said


def test_a_rejected_claim_is_not_blamed_for_the_missing_summary() -> None:
    """Ban Next truoc day lay blocked[0] - dung cai loi nay."""
    assert why_no_summary([LOAI_LUAN_DIEM]) == NO_SUMMARY


def test_nothing_rejected_still_says_something() -> None:
    assert why_no_summary([]) == NO_SUMMARY


def test_the_payload_carries_the_reason_when_there_is_no_summary() -> None:
    payload = manager_answer(ManagerAnswer(question="q", rejected=(LOAI_LUAN_DIEM, GO_SO)))
    assert "gõ tay" in payload["direct_reason"]


def test_the_payload_carries_no_reason_when_there_is_a_summary() -> None:
    payload = manager_answer(ManagerAnswer(question="q", summary="Nợ là tiêu chí đầu tiên."))
    assert payload["direct_reason"] == ""


# --- khong ket luan duoc: hai loai khac nhau -----------------------------------------


def test_self_limiting_is_told_apart_from_thin_data() -> None:
    titles = [group["title"] for group in gap_groups([GIOI_HAN, CHUA_DU])]
    assert titles == ["Đã giới hạn để tránh kết luận sai", "Dữ liệu chưa đủ để nói"]


def test_each_kind_carries_its_explanation() -> None:
    group = gap_groups([GIOI_HAN])[0]
    assert "ngẫu nhiên" in group["explain"]


def test_a_line_for_the_operator_is_not_shown_to_the_reader() -> None:
    items = [item for group in gap_groups([CAU_HINH, CHUA_DU]) for item in group["items"]]
    assert CAU_HINH not in items
    assert CHUA_DU in items


def test_a_line_of_no_known_kind_is_kept_under_other_notes() -> None:
    # Mot con so vang mat va mot con so khong ai duoc bao trong giong het nhau.
    assert gap_groups(["mot ghi chu la"])[0]["title"] == OTHER_NOTES


def test_the_payload_carries_the_groups() -> None:
    payload = manager_answer(ManagerAnswer(question="q", unanswered=(GIOI_HAN, CAU_HINH)))
    assert [group["title"] for group in payload["gap_groups"]] == [
        "Đã giới hạn để tránh kết luận sai"
    ]


# --- ket luan bi chan: vi loai ly do nao --------------------------------------------


def test_a_claim_with_a_typed_number_is_grouped_as_untraceable() -> None:
    group = blocked_groups([GO_SO])[0]
    assert group["title"] == "không dẫn được về chỉ số nào"
    assert group["explain"]


def test_the_payload_carries_the_blocked_groups() -> None:
    payload = manager_answer(ManagerAnswer(question="q", rejected=(GO_SO,)))
    assert payload["blocked_groups"][0]["items"] == [GO_SO]


# --- bieu do da dang ----------------------------------------------------------------


def _answer(*claims: tuple[str, tuple[str, ...]]) -> SimpleNamespace:
    return SimpleNamespace(
        claims=[SimpleNamespace(claim=text, metric_keys=keys) for text, keys in claims]
    )


MEASURED = {"doanh_thu.mean.by.vung.Bac": 12.0, "doanh_thu.mean.by.vung.Nam": 18.0}


def test_the_chart_is_drawn_by_the_same_function_as_the_python_page() -> None:
    keys = tuple(MEASURED)
    drawn = _charts(_answer(("Doanh thu theo vùng", keys)), MEASURED)  # type: ignore[arg-type]
    expected = (
        chart_for(pairs_from(MEASURED, list(keys)), title="Doanh thu theo vùng", story=True) or ""
    )
    assert drawn == [expected]


def test_there_is_one_chart_slot_per_claim_in_order() -> None:
    drawn = _charts(  # type: ignore[arg-type]
        _answer(("mot", tuple(MEASURED)), ("hai", ())), MEASURED
    )
    assert len(drawn) == 2
    assert drawn[1] == ""


def test_no_answer_means_no_charts() -> None:
    assert _charts(None, MEASURED) == []


# --- bieu do khong duoc lang le bien mat vi mot dau cach vo hinh ---------------

LECH = {" ROA(C) before interest.corr.with.Bankrupt?": -0.26}


def test_a_key_with_drifted_whitespace_still_gets_its_chart() -> None:
    """Luot cap do 5: chu hien dung con so, bieu do thi khong ve."""
    pairs = pairs_from(LECH, ["ROA(C) before interest.corr.with.Bankrupt?"])
    assert [value for _, value in pairs] == [-0.26]


def test_a_key_that_matches_nothing_still_draws_nothing() -> None:
    # Ve mot cot khong co so dang sau la bia mot cot.
    assert pairs_from(LECH, ["khong_co_chi_so_nay"]) == []


def test_an_exact_key_is_used_as_it_is() -> None:
    assert pairs_from({"a.mean": 1.5}, ["a.mean"])[0][1] == 1.5
