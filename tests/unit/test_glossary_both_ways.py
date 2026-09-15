"""Chu giai phai doc duoc cach nguoi ta viet that, khong chi cach he thong doi.

Chu he thong viet nam dong chu giai cho bo du lieu pha san - thuat ngu truoc,
ten cot sau, va dung " / " de tach cac cach goi:

    tỷ suất lợi nhuận gộp / biên lợi nhuận gộp = Operating Gross Margin

He thong chi doc chieu `cot = nghia`, nen ca nam dong bi bo qua, KHONG BAO GI.
Do tren chinh bang do: 0/3 cau hoi nhan ra cot. Doc ca hai chieu thi 3/3.

Kem theo hai cai bay da do truoc do: hai dong cung mot cot thi dong sau de dong
truoc; va nhieu cach goi tren mot dong thi cum ngan khong khop duoc.
"""

from __future__ import annotations

from analysis_system.core.vietnamese_text import fold
from analysis_system.domains.ai_planner.asked_columns import (
    _meaning_appears,
    named_by,
    parse_glossary,
    unmatched_lines,
    untouched,
)

# Ten cot that cua bo pha san - ke ca dau cach vo hinh o dau cua bang cu.
COT = [
    "Bankrupt?",
    " Operating Gross Margin",
    " Debt ratio %",
    " Total Asset Turnover",
    " Cash Flow Per Share",
    " Net worth/Assets",
]

# Nguyen van nam dong chu he thong da luu.
CUA_SEP = """công ty phá sản / nhóm phá sản = Bankrupt?
tỷ suất lợi nhuận gộp / biên lợi nhuận gộp = Operating Gross Margin
tỷ lệ nợ = Debt ratio %
dòng tiền trên mỗi cổ phiếu = Cash Flow Per Share
vòng quay tổng tài sản = Total Asset Turnover"""


def _hoi(question: str, context: str = CUA_SEP) -> set[str]:
    return {name.strip() for name in named_by(question, COT, parse_glossary(context))}


# --- dung nam dong chu he thong da viet --------------------------------------------


def test_the_owner_glossary_finds_operating_gross_margin() -> None:
    assert "Operating Gross Margin" in _hoi("So sánh tỷ suất lợi nhuận gộp giữa hai nhóm")


def test_the_second_way_of_saying_it_works_too() -> None:
    """Cach goi thu hai sau dau " / " - dung cai chu he thong hoi ma bi truot."""
    assert "Operating Gross Margin" in _hoi("Biên lợi nhuận gộp của nhóm phá sản thế nào?")


def test_the_owner_glossary_finds_the_debt_ratio() -> None:
    assert "Debt ratio %" in _hoi("Tỷ lệ nợ của công ty phá sản thế nào?")


def test_the_owner_glossary_finds_the_bankrupt_flag() -> None:
    assert "Bankrupt?" in _hoi("Nhóm phá sản có gì khác?")


def test_the_owner_glossary_finds_asset_turnover() -> None:
    assert "Total Asset Turnover" in _hoi("Vòng quay tổng tài sản có khác nhau không?")


def test_none_of_the_owner_lines_is_reported_as_unmatched() -> None:
    assert unmatched_lines(CUA_SEP, COT) == []


# --- chieu cu van chay ------------------------------------------------------------


def test_the_column_first_direction_still_works() -> None:
    assert "Debt ratio %" in _hoi("tỷ lệ nợ thế nào", "Debt ratio % = tỷ lệ nợ")


def test_it_reads_without_diacritics_too() -> None:
    assert "Debt ratio %" in _hoi("ty le no the nao")


# --- nhieu cach goi cho mot cot ---------------------------------------------------


def test_several_ways_of_saying_it_on_one_line_each_match() -> None:
    line = "Operating Gross Margin = tỷ suất lợi nhuận gộp; biên lợi nhuận; khả năng sinh lời"
    assert "Operating Gross Margin" in _hoi("biên lợi nhuận là bao nhiêu", line)
    assert "Operating Gross Margin" in _hoi("khả năng sinh lời thế nào", line)


def test_a_short_way_of_saying_it_now_matches() -> None:
    """Truoc day "bien loi nhuan" (3 chu) truot vi nam trong mot dong dai."""
    line = "Operating Gross Margin = tỷ suất lợi nhuận gộp hoạt động kinh doanh; biên lợi nhuận"
    assert "Operating Gross Margin" in _hoi("biên lợi nhuận là bao nhiêu", line)


def test_two_lines_for_one_column_are_merged_not_overwritten() -> None:
    """Truoc day dong sau de dong truoc, khong bao gi."""
    context = "Debt ratio % = tỷ lệ nợ\nDebt ratio % = đòn bẩy tài chính"
    assert "Debt ratio %" in _hoi("tỷ lệ nợ ra sao", context)
    assert "Debt ratio %" in _hoi("đòn bẩy tài chính ra sao", context)


def test_a_slash_inside_a_column_name_is_not_split() -> None:
    """`Net worth/Assets` tu co dau gach cheo - khong duoc cat nham."""
    assert "Net worth/Assets" in _hoi("tỷ lệ vốn chủ thế nào", "Net worth/Assets = tỷ lệ vốn chủ")


def test_a_slash_without_spaces_inside_a_meaning_is_not_split() -> None:
    # "(yes/no)" trong chu giai cua bo ngan hang phai giu nguyen.
    table = parse_glossary("Bankrupt? = kết quả (yes/no) của công ty")
    assert "Bankrupt?" in named_by("kết quả (yes/no) của công ty ra sao", COT, table)


# --- khop nguyen chu ------------------------------------------------------------


def test_a_phrase_does_not_match_inside_a_longer_word() -> None:
    """Truoc day so bang chuoi con: "ky han" khop vao "ky hanh"."""
    assert _meaning_appears(fold("hỏi về kỳ hạnh"), "kỳ hạn") is False


def test_a_phrase_matches_as_whole_words() -> None:
    assert _meaning_appears(fold("hỏi về kỳ hạn gửi"), "kỳ hạn") is True


# --- dong khong tro toi cot nao thi phai noi ra ---------------------------------


def test_a_line_naming_no_real_column_is_reported() -> None:
    context = "tỷ lệ nợ = Debt ratio\nDebt ratio % = tỷ lệ nợ"
    assert unmatched_lines(context, COT) == ["tỷ lệ nợ = Debt ratio"]


def test_prose_without_an_equals_sign_is_not_reported() -> None:
    assert unmatched_lines("Dữ liệu các công ty Đài Loan 1999-2009.", COT) == []


def test_a_line_with_nothing_after_the_sign_is_not_reported() -> None:
    assert unmatched_lines("Debt ratio % =   ", COT) == []


# --- canh bao "khong ket luan nao cham toi cot duoc hoi" -------------------------


def test_the_warning_never_names_a_way_of_saying_it_as_a_column() -> None:
    """Dong viet nguoc co khoa la mot CACH GOI - no khong phai mot cot."""
    warning = untouched(
        "tỷ lệ nợ của nhóm phá sản thế nào",
        [("Bankrupt?.corr.with.Debt ratio %",)],
        ["Bankrupt?.corr.with.Debt ratio %", "Debt ratio %.mean"],
        "tỷ lệ nợ = Debt ratio %",
    )
    assert "cột tỷ lệ nợ" not in warning
