"""Canh bao chi no khi ca cau tra loi khong dung toi cot duoc hoi ten.

Phan quan trong nhat cua bai nay la nua tren: cac truong hop PHAI IM LANG. Mot
canh bao no bua thi nguoi ta thoi doc ca cum - va do khong phai lo xa. Ban dau
tien cua chinh module nay hoi TUNG ket luan mot, do tren luot chay that thi no
3/4, toan oan: cau hoi co hai ve, va ba ket luan kia dang tra loi ve thu nhat.
"""

from __future__ import annotations

from analysis_system.services.asked_columns import (
    columns_in,
    named_by,
    parse_glossary,
    untouched,
)

# Nguyen van cac metric key da di ra tu finance_data.
MOI_KEY = (
    "PPF.mean.by.gender.Female",
    "PPF.mean.by.gender.Male",
    "Objective.Capital_Appreciation.share_pct",
    "Source.Internet.share_pct",
    "Source.Financial_Consultants.share_pct",
    "Invest_Monitor.Daily.share_pct",
    "Equity_Market.mean.by.gender.Male",
    "Duration.mean",
    "age.mean",
)


# --- phai im lang -------------------------------------------------------------


def test_a_question_naming_no_column_is_left_alone() -> None:
    # Truong hop thuong gap nhat. Im lang o day la ly do canh bao con dang tin
    # khi no that su no.
    assert untouched("Hãy phân tích dữ liệu này giúp tôi", [MOI_KEY[:1]], MOI_KEY) == ""


def test_an_answer_that_reaches_the_named_column_is_left_alone() -> None:
    assert (
        untouched("kênh thông tin (Source) nào phổ biến", [("Source.Internet.share_pct",)], MOI_KEY)
        == ""
    )


def test_one_claim_covering_it_is_enough_for_the_whole_answer() -> None:
    """Day la ca da lam ban dau tien no 3/4 oan.

    Cau hoi co hai ve. Ba ket luan lo ve thu nhat (gender, PPF, Equity_Market),
    mot ket luan lo ve thu hai (Invest_Monitor). Ca cau tra loi la day du, nen
    khong duoc noi gi.
    """
    question = (
        "phân tích khác biệt hành vi đầu tư giữa hai nhóm giới tính. Những người "
        "chọn Equity có tần suất theo dõi danh mục (Invest_Monitor) khác thế nào?"
    )
    answer = [
        ("PPF.mean.by.gender.Female",),
        ("Equity_Market.mean.by.gender.Male",),
        ("Invest_Monitor.Daily.share_pct",),
    ]
    assert untouched(question, answer, MOI_KEY) == ""


def test_an_answer_with_no_metric_keys_is_left_alone() -> None:
    assert untouched("kênh thông tin (Source) nào phổ biến", [], MOI_KEY) == ""
    assert untouched("kênh thông tin (Source) nào phổ biến", [()], MOI_KEY) == ""


def test_a_column_name_hiding_inside_another_word_does_not_count() -> None:
    """Cot `age` khong duoc khop vao giua "average".

    Bo du lieu nay co that mot cot ten dung ba chu cai, nen day khong phai gia dinh.
    """
    assert named_by("what is the average and the percentage", ["age"]) == frozenset()


def test_a_grouping_column_counts_as_reached() -> None:
    # `PPF.mean.by.gender.Female` dua tren ca PPF lan gender.
    assert untouched("khác biệt theo gender", [("PPF.mean.by.gender.Female",)], MOI_KEY) == ""


# --- phai len tieng -----------------------------------------------------------


def test_the_original_bug_is_caught_once_the_glossary_is_written() -> None:
    """Loi that: hoi ve muc tieu tiet kiem, ca cau tra loi khong he cham Objective.

    Khong co chu giai thi cau hoi tieng Viet khong goi ten duoc cot nao, va he
    thong im lang - dung nhu truoc. Viet mot dong chu giai thi no bat duoc.
    """
    question = "mục tiêu tiết kiệm của họ là gì"
    answer = [("PPF.mean.by.gender.Female",)]
    context = "Objective = mục tiêu tiết kiệm\nDuration = thời gian giữ vốn"

    assert untouched(question, answer, MOI_KEY) == ""

    warning = untouched(question, answer, MOI_KEY, context)
    assert "Objective" in warning


def test_a_named_column_no_claim_reached_is_reported() -> None:
    warning = untouched(
        "tần suất theo dõi danh mục (Invest_Monitor) thế nào",
        [("Duration.mean",), ("age.mean",)],
        MOI_KEY,
    )
    assert "Invest_Monitor" in warning


def test_two_missing_columns_are_named_together() -> None:
    warning = untouched(
        "phân tích Source và Invest_Monitor giúp tôi",
        [("Duration.mean",)],
        MOI_KEY,
    )
    assert "Invest_Monitor" in warning
    assert "Source" in warning


def test_the_warning_never_removes_anything() -> None:
    # No la mot chuoi de doc, khong phai mot quyet dinh loai bo. Ca module nay
    # khong co duong nao dan toi viec vut mot ket luan di.
    assert isinstance(untouched("Source thế nào", [("Duration.mean",)], MOI_KEY), str)


# --- doc bang chu giai --------------------------------------------------------


def test_a_glossary_line_is_read() -> None:
    assert parse_glossary("Objective = mục tiêu tiết kiệm") == {"Objective": "mục tiêu tiết kiệm"}


def test_prose_around_the_glossary_is_ignored() -> None:
    """O Boi canh van la cho viet van xuoi. Chu giai chi la thu di kem."""
    context = (
        "Đây là khảo sát về hành vi đầu tư cá nhân ở Ấn Độ.\n"
        "Objective = mục tiêu tiết kiệm\n"
        "Mỗi dòng là một người trả lời: không phải một giao dịch.\n"
        "Source = kênh thông tin\n"
    )
    assert parse_glossary(context) == {
        "Objective": "mục tiêu tiết kiệm",
        "Source": "kênh thông tin",
    }


def test_a_line_with_no_meaning_after_the_sign_is_skipped() -> None:
    assert parse_glossary("Objective =   ") == {}


def test_an_empty_context_is_an_empty_glossary() -> None:
    assert parse_glossary("") == {}


def test_a_colon_is_not_a_glossary_line() -> None:
    """Dau hai cham day ray trong van xuoi binh thuong.

    Nhan no la tu ruoc dong rac vao bang, roi bang rac lam canh bao no bua.
    """
    assert parse_glossary("Ghi chú: dữ liệu thu thập năm 2020") == {}


# --- doc cot tu metric key ----------------------------------------------------


def test_the_first_segment_is_a_column() -> None:
    assert columns_in(("Source.Internet.share_pct",)) == frozenset({"Source"})


def test_the_segment_after_by_is_also_a_column() -> None:
    assert columns_in(("PPF.mean.by.gender.Female",)) == frozenset({"PPF", "gender"})


def test_nothing_in_means_nothing_out() -> None:
    assert columns_in(()) == frozenset()
    assert columns_in(("",)) == frozenset()
