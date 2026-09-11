"""Hai cot cung khop mot cho trong cau hoi thi cum CU THE HON thang.

Do tren mot ban nhap chu giai that cua bo pha san: hoi bang dung cach goi cua
mot cot thi 59/96 cot keo theo cot khac. Nhung cap dung duoi day lay tu chinh
ban nhap do.
"""

from __future__ import annotations

from analysis_system.services.asked_columns import named_by, parse_glossary

NL = "\n"


def _hoi(question: str, *lines: str) -> set[str]:
    glossary = parse_glossary(NL.join(lines))
    columns = [line.split(" = ")[0] for line in lines]
    return set(named_by(question, columns, glossary))


# --- cum nay nam tron trong cum kia ---------------------------------------------

NGAN_HAN = (
    "Current Liability to Assets = nợ ngắn hạn/tài sản",
    "Current Liability to Current Assets = nợ ngắn hạn/tài sản ngắn hạn",
)


def test_the_longer_phrase_wins_when_it_is_asked() -> None:
    found = _hoi("nợ ngắn hạn/tài sản ngắn hạn thế nào", *NGAN_HAN)
    assert found == {"Current Liability to Current Assets"}


def test_the_shorter_phrase_wins_when_only_it_is_asked() -> None:
    """Hai cot khop cung mot doan; cot duoc phu tron thang cot chi khop mot phan."""
    found = _hoi("nợ ngắn hạn/tài sản của công ty thế nào", *NGAN_HAN)
    assert found == {"Current Liability to Assets"}


def test_a_shared_tail_does_not_drag_the_other_column() -> None:
    lines = (
        "Cash Flow Per Share = dòng tiền trên mỗi cổ phần",
        "Net Value Per Share = giá trị ròng trên mỗi cổ phần",
    )
    assert _hoi("dòng tiền trên mỗi cổ phần ra sao", *lines) == {"Cash Flow Per Share"}


def test_after_tax_does_not_drag_pre_tax() -> None:
    lines = (
        "After-tax net Interest Rate = tỷ lệ lãi ròng sau thuế",
        "Pre-tax net Interest Rate = tỷ lệ lãi ròng trước thuế",
    )
    assert _hoi("tỷ lệ lãi ròng sau thuế thế nào", *lines) == {"After-tax net Interest Rate"}


# --- cho khong duoc bo --------------------------------------------------------------


def test_two_columns_asked_in_two_places_are_both_kept() -> None:
    """Chi bo khi hai doan CHONG len nhau trong cau hoi."""
    lines = (
        "Debt ratio % = tỷ lệ nợ",
        "Operating Gross Margin = biên lợi nhuận gộp",
    )
    found = _hoi("so sánh tỷ lệ nợ và biên lợi nhuận gộp", *lines)
    assert found == {"Debt ratio %", "Operating Gross Margin"}


def test_a_genuinely_ambiguous_question_keeps_both() -> None:
    """Hoi chung chung "ty le lai rong" - khong noi sau hay truoc thue - thi mo ho
    that, va doan ho la vut mat mot cot nguoi ta co the dang hoi."""
    lines = (
        "After-tax net Interest Rate = tỷ lệ lãi ròng sau thuế",
        "Pre-tax net Interest Rate = tỷ lệ lãi ròng trước thuế",
    )
    assert _hoi("tỷ lệ lãi ròng thế nào", *lines) == {
        "After-tax net Interest Rate",
        "Pre-tax net Interest Rate",
    }


def test_two_columns_with_the_same_words_are_both_kept() -> None:
    """Trung het cach goi thi khong may nao phan xu duoc - bao ra luc duyet."""
    lines = (
        "Current Liabilities/Equity = nợ ngắn hạn/vốn chủ sở hữu",
        "Current Liability to Equity = nợ ngắn hạn/vốn chủ sở hữu",
    )
    assert len(_hoi("nợ ngắn hạn/vốn chủ sở hữu thế nào", *lines)) == 2


def test_a_literal_column_name_still_counts() -> None:
    assert _hoi("Debt ratio % của nhóm phá sản", "Debt ratio % = tỷ lệ nợ") == {"Debt ratio %"}
