"""Ban nhap chu giai ngan, sach, va noi ra cho trung.

Do tren mot ban nhap that cua bo pha san (96 dong): trung binh 6,6 chu moi cach
goi, 87 dong qua 4 chu, 19 dong mo dau bang tu dem, 6 dong co don vi trong
ngoac, 2 cap cot trung het cach goi. Viec code lam duoc thi khong giao model.
"""

from __future__ import annotations

from analysis_system.domains.data_ingestion.glossary_draft import (
    GlossaryEntry,
    GlossaryProposal,
    build_request,
    duplicate_meanings,
    tidy_meaning,
    verified,
)

# --- don bang code ----------------------------------------------------------------


def test_a_leading_filler_word_is_removed() -> None:
    """ "tinh trang pha san" khong khop cau hoi "cong ty pha san"."""
    assert tidy_meaning("tình trạng phá sản") == "phá sản"


def test_every_filler_is_removed() -> None:
    assert tidy_meaning("Tốc độ tăng trưởng tổng tài sản") == "tăng trưởng tổng tài sản"
    assert tidy_meaning("mức độ đòn bẩy tài chính") == "đòn bẩy tài chính"
    assert tidy_meaning("tần suất quay vòng vốn") == "quay vòng vốn"


def test_a_filler_is_not_removed_when_nothing_would_be_left() -> None:
    # "toc do" dung mot minh la mot cach goi, khong phai tu dem.
    assert tidy_meaning("tốc độ") == "tốc độ"


def test_a_unit_in_brackets_is_removed() -> None:
    assert (
        tidy_meaning("doanh thu trên mỗi cổ phiếu (nhân dân tệ)") == "doanh thu trên mỗi cổ phiếu"
    )
    assert tidy_meaning("vòng quay tài sản (lần)") == "vòng quay tài sản"


def test_a_one_letter_qualifier_is_kept() -> None:
    """Bo "(A)" thi "roa (a)" va "roa (b)" trung nhau."""
    assert tidy_meaning("roa (a)") == "roa a"
    assert tidy_meaning("roa (b)") == "roa b"


def test_a_trailing_full_stop_is_removed() -> None:
    assert tidy_meaning("tỷ lệ nợ.") == "tỷ lệ nợ"


def test_the_draft_goes_through_the_same_tidying() -> None:
    proposal = GlossaryProposal(
        entries=[GlossaryEntry(column="Bankrupt?", meaning="Tình trạng phá sản")]
    )
    table, _ = verified(proposal, ["Bankrupt?"])
    assert table == {"Bankrupt?": "phá sản"}


# --- noi ra cho trung ------------------------------------------------------------


def test_two_columns_with_the_same_meaning_are_reported() -> None:
    lines = "A = nợ ngắn hạn/vốn chủ sở hữu\nB = nợ ngắn hạn/vốn chủ sở hữu\nC = tỷ lệ nợ"
    found = duplicate_meanings(lines)
    assert len(found) == 1
    assert "A" in found[0] and "B" in found[0]


def test_the_same_meaning_with_and_without_diacritics_is_reported() -> None:
    assert duplicate_meanings("A = tỷ lệ nợ\nB = ty le no")


def test_distinct_meanings_report_nothing() -> None:
    assert duplicate_meanings("A = tỷ lệ nợ\nB = biên lợi nhuận gộp") == []


# --- loi dan model ----------------------------------------------------------------


def test_the_model_is_told_this_is_a_search_keyword_not_a_translation() -> None:
    assert "TU KHOA TIM KIEM" in build_request(["a"]).system


def test_the_model_is_told_two_to_four_words() -> None:
    assert "2 den 4 chu" in build_request(["a"]).system


def test_the_model_is_told_one_keyword_per_column() -> None:
    assert "MOI COT MOT TU KHOA RIENG" in build_request(["a"]).system


def test_the_model_is_told_to_drop_fillers_and_units() -> None:
    system = build_request(["a"]).system
    assert "tu dem" in system
    assert "don vi tinh" in system


def test_the_model_is_told_not_to_abbreviate_vietnamese() -> None:
    """Bi ep ngan 2-4 chu, model tu che "lo ng/ts" - khong ai doc duoc."""
    assert "khong viet tat" in build_request(["a"]).system.lower()


def test_the_examples_are_written_with_diacritics() -> None:
    """Loi dan viet khong dau thi model tra loi khong dau."""
    assert "biên lợi nhuận gộp" in build_request(["a"]).system


def test_the_model_is_told_meaning_beats_brevity() -> None:
    assert "DUNG NGHIA quan trong hon" in build_request(["a"]).system
