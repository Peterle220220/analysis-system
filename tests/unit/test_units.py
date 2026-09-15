"""Don vi he thong chen vao - va luc nao thi khong nen chen.

Cau that da hien ra tren man hinh cua chu he thong:

    40 % so nguoi tra loi (16 dong nguoi tham gia)

`rows.total` mang don vi `dong`, model viet mau cau `"{rows.total} nguoi tham
gia`". Hai danh tu dinh vao nhau.

Nua duoi cua bai nay quan trong hon nua tren: cac cho PHAI GIU don vi lai. Bo
nham thi mat nghia, giu nham thi chi thua mot chu - nen luat nay nghieng ve
phia giu.
"""

from __future__ import annotations

import pytest

from analysis_system.core.units import is_counting_noun, keeps_unit

# --- phai bo don vi di --------------------------------------------------------


def test_the_sentence_that_started_this() -> None:
    # "16 dong nguoi tham gia" -> "16 nguoi tham gia"
    assert not keeps_unit("dòng", " người tham gia")


def test_a_model_written_noun_takes_over() -> None:
    assert not keeps_unit("dòng", " khách hàng đã mua")
    assert not keeps_unit("nhóm", " ngành hàng khác nhau")


# --- phai giu don vi lai ------------------------------------------------------


def test_a_number_at_the_end_of_the_sentence_keeps_its_unit() -> None:
    # Con so dang tran. Day dung la ly do don vi ton tai.
    assert keeps_unit("dòng", "")
    assert keeps_unit("dòng", ".")
    assert keeps_unit("dòng", ", va con nhieu nua")


@pytest.mark.parametrize("tail", [" trên tổng số", " trong tháng", " so với năm ngoái"])
def test_a_connective_after_the_number_keeps_the_unit(tail: str) -> None:
    """Bo `lan` di thi "5 tren tong so" mat nghia.

    Chu di sau la tu noi, khong phai danh tu model tu viet.
    """
    assert keeps_unit("lần", tail)


def test_a_measuring_symbol_is_never_dropped() -> None:
    # Khong ai doc "40 %" ma tuong `%` la mot danh tu tranh cho.
    assert keeps_unit("%", " số người trả lời")
    assert not is_counting_noun("%")


def test_no_unit_at_all_is_left_alone() -> None:
    assert keeps_unit("", " người tham gia")


def test_the_model_typing_the_same_unit_is_left_to_the_other_check() -> None:
    """`without_doubled_units` da lo ca nay tu truoc. Hai cho sua mot loi la mot cho thua."""
    assert keeps_unit("dòng", " dòng dữ liệu")


def test_a_digit_right_after_is_not_a_noun() -> None:
    assert keeps_unit("dòng", " 2023")


def test_a_counting_noun_is_told_from_a_symbol() -> None:
    assert is_counting_noun("dòng")
    assert is_counting_noun("nhóm")
    assert not is_counting_noun("%")
    assert not is_counting_noun("")


# --- noi voi cho chen so that ------------------------------------------------


def _rendered(template: str) -> str:
    from analysis_system.models.agents import Finding, MetricValue
    from analysis_system.services.findings import render_all

    metrics = {
        "rows.total": MetricValue(key="rows.total", value=40, unit="dòng", source="volume"),
        "x.pct": MetricValue(key="x.pct", value=40.5, unit="%", source="share"),
    }
    out, bad = render_all(
        [Finding(claim_template=template, evidence_ref="mart://x.parquet")], metrics
    )
    assert out, bad
    return out[0].claim


def test_the_sentence_the_owner_saw_is_fixed_end_to_end() -> None:
    assert _rendered("Khảo sát có {rows.total} người tham gia.") == "Khảo sát có 40 người tham gia."


def test_a_bare_number_still_gets_its_unit() -> None:
    assert _rendered("Bảng có {rows.total}.") == "Bảng có 40 dòng."


def test_the_two_repairs_do_not_cancel_each_other_out() -> None:
    """Bay da sap mot lan trong luc viet bai nay.

    without_doubled_units go bo don vi model tu go, tin rang he thong chen
    lai. Luat moi lai khong chen khi thay danh tu di sau. Ca hai cung doc ban
    da sua thi "{rows.total} dong du lieu" mat chu hai lan, ra "40 du lieu".
    """
    assert _rendered("Bảng có {rows.total} dòng dữ liệu.") == "Bảng có 40 dòng dữ liệu."


def test_a_percent_is_untouched_end_to_end() -> None:
    assert _rendered("Chiếm {x.pct} số người trả lời.") == "Chiếm 40.50 % số người trả lời."
