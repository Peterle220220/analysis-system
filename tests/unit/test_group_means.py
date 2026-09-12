"""Ket luan so sanh nhom phai neu trung binh cua TUNG nhom, voi moi bo du lieu.

Loi goc (cap do 3): "Khac biet trung binh giua hai nhom la 0.07" ma khong noi nhom
nao bao nhieu, du ca hai trung binh da duoc do. Code noi them cau theo khung mau,
bang dung con so da do, cho moi ket luan con thieu.
"""

from __future__ import annotations

from analysis_system.agents.a7_analyst import build_analysis_request
from analysis_system.agents.a9_manager import build_answer_request
from analysis_system.contracts.agents import ClaimEvidence, ManagerAnswer
from analysis_system.services.group_means import (
    GROUP_MEANS_RULE,
    compared_pairs,
    group_means,
    with_group_means,
)
from analysis_system.web.view import _charts

MEASURED = {
    "loi_nhuan.mean.by.trang_thai.dong": 0.7201,
    "loi_nhuan.mean.by.trang_thai.mo": 0.7853,
    "loi_nhuan.diff.by.trang_thai": -0.0652,
    "loi_nhuan.ttest.by.trang_thai.p_value": 0.0,
}
LABELS = {"trang_thai": {"mo": "Đang hoạt động", "dong": "Đã đóng cửa"}}


def _answer(*claims: tuple[str, tuple[str, ...]]) -> ManagerAnswer:
    return ManagerAnswer(
        question="So sánh hai nhóm?",
        claims=tuple(
            ClaimEvidence(claim=text, metric_keys=keys, evidence_ref="mart://bang.parquet")
            for text, keys in claims
        ),
    )


# --- nhan ra ket luan so sanh nhom ----------------------------------------------


def test_every_comparison_statistic_names_its_pair() -> None:
    keys = [
        "loi_nhuan.diff.by.trang_thai",
        "loi_nhuan.ttest.by.trang_thai.p_value",
        "loi_nhuan.effect_size.by.trang_thai",
        "gia.eta_sq.by.vung",
    ]
    assert compared_pairs(keys) == [("loi_nhuan", "trang_thai"), ("gia", "vung")]


def test_a_grouping_column_with_dots_in_its_name_is_kept_whole() -> None:
    assert compared_pairs(["x.diff.by.cons.conf.idx"]) == [("x", "cons.conf.idx")]


def test_a_plain_mean_is_not_a_comparison() -> None:
    assert compared_pairs(["loi_nhuan.mean.by.trang_thai.mo", "loi_nhuan.mean"]) == []


def test_group_means_come_highest_first_with_their_keys() -> None:
    assert group_means(MEASURED, "loi_nhuan", "trang_thai") == [
        ("mo", 0.7853, "loi_nhuan.mean.by.trang_thai.mo"),
        ("dong", 0.7201, "loi_nhuan.mean.by.trang_thai.dong"),
    ]


# --- noi cau theo khung mau -------------------------------------------------------


def test_a_difference_only_claim_gets_both_group_means() -> None:
    answer = _answer(
        ("Khác biệt trung bình giữa hai nhóm là 0.07", ("loi_nhuan.diff.by.trang_thai",))
    )
    claim = with_group_means(answer, MEASURED, LABELS).claims[0]
    assert claim.claim == (
        "Khác biệt trung bình giữa hai nhóm là 0.07. Trung bình loi_nhuan của nhóm Đang hoạt "
        "động là 0.79, cao hơn so với nhóm Đã đóng cửa là 0.72 (mức chênh lệch 0.07)."
    )
    # Con so moi lan nguoc duoc: khoa cua no vao dan chung.
    assert "loi_nhuan.mean.by.trang_thai.mo" in claim.metric_keys
    assert "loi_nhuan.mean.by.trang_thai.dong" in claim.metric_keys


def test_an_effect_size_or_t_test_claim_is_completed_too() -> None:
    answer = _answer(("Effect size lớn.", ("loi_nhuan.ttest.by.trang_thai.p_value",)))
    assert "cao hơn so với nhóm" in with_group_means(answer, MEASURED, LABELS).claims[0].claim


def test_a_claim_that_already_gives_the_means_is_left_alone() -> None:
    keys = ("loi_nhuan.mean.by.trang_thai.mo", "loi_nhuan.mean.by.trang_thai.dong")
    answer = _answer(("Nhóm A 0.79, nhóm B 0.72.", keys))
    assert with_group_means(answer, MEASURED, LABELS) == answer


def test_no_measured_means_means_nothing_is_invented() -> None:
    answer = _answer(("Khác biệt là 0.07.", ("loi_nhuan.diff.by.trang_thai",)))
    assert with_group_means(answer, {"loi_nhuan.diff.by.trang_thai": 0.07}) == answer


def test_a_small_gap_keeps_its_digits() -> None:
    measured = {"m.mean.by.g.a": 0.6083, "m.mean.by.g.b": 0.5987}
    claim = with_group_means(_answer(("Chênh nhỏ.", ("m.diff.by.g",))), measured).claims[0]
    assert "(mức chênh lệch 0.0096)" in claim.claim


def test_without_value_labels_the_group_is_named_like_the_chart() -> None:
    measured = {"doanh_thu.mean.by.vung.Bac": 12.0, "doanh_thu.mean.by.vung.Nam": 18.0}
    answer = _answer(("Khác nhau.", ("doanh_thu.diff.by.vung",)))
    claim = with_group_means(answer, measured, names={"vung": "Vùng"}).claims[0]
    assert "nhóm Vùng: Nam là 18, cao hơn so với nhóm Vùng: Bac là 12 (mức chênh lệch 6)" in (
        claim.claim
    )


def test_many_groups_are_listed_highest_first() -> None:
    measured = {"gia.mean.by.vung.A": 3.0, "gia.mean.by.vung.B": 1.0, "gia.mean.by.vung.C": 2.0}
    claim = with_group_means(_answer(("Khác nhau.", ("gia.anova.by.vung.p_value",))), measured)
    assert claim.claims[0].claim.endswith(
        "Trung bình gia theo từng nhóm: nhóm vung: A là 3, nhóm vung: C là 2, nhóm vung: B là 1."
    )


def test_a_claim_about_something_else_is_untouched() -> None:
    answer = _answer(("Tổng số dòng là 381.", ("rows.total",)))
    assert with_group_means(answer, MEASURED, LABELS) == answer


def test_the_completed_claim_now_gets_a_chart_of_the_two_means() -> None:
    answer = with_group_means(
        _answer(("Khác biệt là 0.07.", ("loi_nhuan.diff.by.trang_thai",))), MEASURED, LABELS
    )
    drawn = _charts(answer, MEASURED, LABELS)
    assert "chart bars" in drawn[0]
    assert "Đang hoạt động" in drawn[0]


# --- luat trong prompt cho ca hai nguoi viet ---------------------------------------


def test_the_analyst_is_told_to_give_both_means() -> None:
    assert GROUP_MEANS_RULE in build_analysis_request([], "câu hỏi", 5).prompt


def test_the_manager_is_told_to_give_both_means() -> None:
    assert GROUP_MEANS_RULE in build_answer_request("câu hỏi", [], [], []).system
