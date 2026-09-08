"""Ban nhap bang chu giai: model de xuat, code doi chieu, nguoi duyet.

Phan quan trong nhat la CODE DOI CHIEU. Mot dong tro toi cot khong ton tai la
mot dong se khong bao gio khop duoc gi - va no nam im trong o Boi canh, trong
y het mot dong dung.
"""

from __future__ import annotations

from analysis_system.services.glossary_draft import (
    MAX_MEANING,
    GlossaryEntry,
    GlossaryProposal,
    as_lines,
    build_request,
    verified,
)

COT = [
    " ROA(C) before interest and depreciation before interest",
    " Debt ratio %",
    "Bankrupt?",
]


def _nhap(*pairs: tuple[str, str]) -> GlossaryProposal:
    return GlossaryProposal(
        entries=[GlossaryEntry(column=column, meaning=meaning) for column, meaning in pairs]
    )


# --- code doi chieu ------------------------------------------------------------


def test_a_real_column_is_kept() -> None:
    table, dropped = verified(_nhap((" Debt ratio %", "tỷ lệ nợ")), COT)
    assert table == {" Debt ratio %": "tỷ lệ nợ"}
    assert dropped == []


def test_a_column_that_does_not_exist_is_dropped() -> None:
    """Mot dong tro toi cot khong ton tai nam im trong o Boi canh, trong y het
    mot dong dung."""
    table, dropped = verified(_nhap(("Khong co cot nay", "gì đó")), COT)
    assert table == {}
    assert dropped


def test_a_key_whose_spacing_drifted_still_matches_the_real_column() -> None:
    """Model chep thua mot dau cach thi khong duoc mat ca dong."""
    table, _ = verified(_nhap(("Debt ratio %", "tỷ lệ nợ")), COT)
    assert table == {" Debt ratio %": "tỷ lệ nợ"}


def test_the_real_column_name_is_what_comes_back() -> None:
    """Khoa tra ve phai la ten cot THAT, khong phai ban model go lai."""
    table, _ = verified(_nhap(("Debt ratio %", "tỷ lệ nợ")), COT)
    assert list(table) == [" Debt ratio %"]


def test_an_empty_meaning_is_dropped() -> None:
    table, dropped = verified(_nhap((" Debt ratio %", "   ")), COT)
    assert table == {}
    assert dropped


def test_a_meaning_that_is_a_paragraph_is_dropped() -> None:
    # Mot doan mo ta khong phai mot cai ten, va no lam nhieu phep khop.
    table, dropped = verified(_nhap((" Debt ratio %", "x" * (MAX_MEANING + 1))), COT)
    assert table == {}
    assert dropped


def test_every_key_that_survives_is_a_real_column() -> None:
    table, _ = verified(
        _nhap(
            (" Debt ratio %", "tỷ lệ nợ"),
            ("khong_co", "gì đó"),
            ("Bankrupt?", "tình trạng phá sản"),
        ),
        COT,
    )
    assert set(table) <= set(COT)


def test_nothing_in_means_nothing_out() -> None:
    table, dropped = verified(GlossaryProposal(), COT)
    assert table == {}
    assert dropped == []


# --- cau hoi gui cho model -----------------------------------------------------


def test_the_request_carries_the_column_names() -> None:
    request = build_request(COT)
    assert "Debt ratio %" in request.prompt
    assert "Bankrupt?" in request.prompt


def test_the_request_shows_no_data() -> None:
    """Dat ten cho mot cot khong can nhin gia tri cua no, va khong nhin thi
    khong co gi de lo."""
    request = build_request(COT)
    assert "6819" not in request.prompt
    assert request.prompt.count("\\n") <= len(COT) + 2


def test_it_is_told_to_skip_what_it_does_not_know() -> None:
    assert "BO QUA" in build_request(COT).system


# --- viet ra dang o Boi canh ---------------------------------------------------


def test_the_lines_are_written_the_way_the_box_reads_them() -> None:
    assert as_lines({"Bankrupt?": "tình trạng phá sản"}) == "Bankrupt? = tình trạng phá sản"


def test_the_lines_come_back_readable_by_the_parser() -> None:
    from analysis_system.services.asked_columns import parse_glossary

    table = {" Debt ratio %": "tỷ lệ nợ", "Bankrupt?": "tình trạng phá sản"}
    assert set(parse_glossary(as_lines(table))) == {"Debt ratio %", "Bankrupt?"}
