"""Bang chu giai luu rieng: khong bi cat, luu la thay, ban cu van doc duoc.

Loi goc: chu giai nam trong o Boi canh (toi da 2.000 ky tu) nen nua sau cua mot
bang 96 cot bi cat ngam; soan lai thi ban moi NOI vao ban cu, va hai dong cung
mot cot gop thanh "nghia cu; nghia moi".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from analysis_system.domains.data_ingestion.dataset_context import MAX_LENGTH
from analysis_system.domains.data_ingestion.glossary_store import (
    GLOSSARY_FILE,
    GLOSSARY_PARAM,
    MAX_CHARACTERS,
    GlossaryTooLongError,
    for_prompt,
    glossary_of,
    read_glossary,
    rows_for,
    without_glossary_lines,
    write_glossary,
)
from analysis_system.services.asked_columns import parse_glossary

COLUMNS = ["Debt ratio %", " ROA(C) before interest", "Bankrupt?"]


# --- luu ---------------------------------------------------------------------


def test_a_96_column_glossary_survives_whole(tmp_path: Path) -> None:
    columns = [f"Operating profit ratio variant {index}" for index in range(96)]
    rows = [
        (name, f"biên lợi nhuận hoạt động biến thể {index}") for index, name in enumerate(columns)
    ]
    saved = write_glossary(tmp_path, rows)
    assert len(saved) > MAX_LENGTH  # dai hon han o Boi canh cu
    assert len(read_glossary(tmp_path).splitlines()) == 96


def test_saving_again_replaces_never_appends(tmp_path: Path) -> None:
    write_glossary(tmp_path, [("Debt ratio %", "tỷ lệ nợ")])
    write_glossary(tmp_path, [("Debt ratio %", "hệ số nợ")])
    assert parse_glossary(read_glossary(tmp_path)) == {"Debt ratio %": "hệ số nợ"}


def test_empty_meanings_are_left_out_and_spacing_is_tidied(tmp_path: Path) -> None:
    assert write_glossary(tmp_path, [("A", "   "), ("B", "x   y")]) == "B = x y"


def test_a_column_name_with_stray_spaces_is_written_tidy(tmp_path: Path) -> None:
    assert write_glossary(tmp_path, [(" ROA(C)  before interest", "roa c")]) == (
        "ROA(C) before interest = roa c"
    )


def test_one_line_per_column_even_if_sent_twice(tmp_path: Path) -> None:
    assert write_glossary(tmp_path, [("A", "một"), ("A", "hai")]) == "A = một"


def test_too_long_is_refused_not_cut(tmp_path: Path) -> None:
    with pytest.raises(GlossaryTooLongError):
        write_glossary(tmp_path, [("A", "x" * (MAX_CHARACTERS + 1))])
    assert not (tmp_path / GLOSSARY_FILE).exists()


def test_nothing_saved_reads_as_empty(tmp_path: Path) -> None:
    assert read_glossary(tmp_path) == ""


# --- doc lai cho bang ---------------------------------------------------------


def test_every_column_gets_a_row_in_table_order() -> None:
    rows = rows_for(COLUMNS, "Bankrupt? = phá sản", "")
    assert [column for column, _ in rows] == COLUMNS
    assert dict(rows) == {"Debt ratio %": "", " ROA(C) before interest": "", "Bankrupt?": "phá sản"}


def test_the_saved_file_wins_over_an_old_context_line_per_column() -> None:
    rows = dict(
        rows_for(COLUMNS, "Debt ratio % = hệ số nợ", "Debt ratio % = tỷ lệ nợ\nphá sản = Bankrupt?")
    )
    # Khong gop "tỷ lệ nợ; hệ số nợ": gop nhu the la loi trung tu vung.
    assert rows["Debt ratio %"] == "hệ số nợ"
    # Dong cu trong o Boi canh, viet chieu nguoc, van lap cot tep chua co.
    assert rows["Bankrupt?"] == "phá sản"


def test_a_column_with_stray_spaces_still_finds_its_meaning() -> None:
    rows = dict(rows_for(COLUMNS, "ROA(C) before interest = roa c", ""))
    assert rows[" ROA(C) before interest"] == "roa c"


# --- chuyen dong cu khoi o Boi canh ---------------------------------------------


def test_moving_old_lines_keeps_the_prose_and_the_unmatched_lines() -> None:
    prose, moved = without_glossary_lines(
        "Khảo sát năm 2023.\nDebt ratio % = tỷ lệ nợ\nx = không có cột", COLUMNS
    )
    assert moved == 1
    assert prose == "Khảo sát năm 2023.\nx = không có cột"


def test_a_context_without_glossary_lines_is_untouched() -> None:
    assert without_glossary_lines("Khảo sát năm 2023.", COLUMNS) == ("Khảo sát năm 2023.", 0)


# --- prompt chi nhan dong can thiet ---------------------------------------------

GLOSSARY = "Debt ratio % = tỷ lệ nợ\nBankrupt? = phá sản"


def test_the_prompt_gets_only_the_lines_the_question_names() -> None:
    said = for_prompt("Khảo sát.", GLOSSARY, "Công ty phá sản có gì khác?")
    assert said == "Khảo sát.\nBankrupt? = phá sản"


def test_the_prompt_is_unchanged_without_a_glossary() -> None:
    assert for_prompt("Khảo sát.", "", "Công ty phá sản có gì khác?") == "Khảo sát."


def test_the_prompt_is_unchanged_when_no_column_is_named() -> None:
    assert for_prompt("Khảo sát.", GLOSSARY, "Doanh thu theo tháng?") == "Khảo sát."


def test_a_line_already_in_the_context_is_not_repeated() -> None:
    context = "Khảo sát.\nBankrupt? = phá sản"
    assert for_prompt(context, GLOSSARY, "Công ty phá sản có gì khác?") == context


# --- code doi chieu doc tham so rieng -------------------------------------------


def test_code_reads_the_glossary_param_first() -> None:
    params = {GLOSSARY_PARAM: "A = b", "boi_canh": "C = d"}
    assert glossary_of(params, "boi_canh") == "A = b"


def test_an_old_plan_without_the_param_falls_back_to_the_context() -> None:
    assert glossary_of({"boi_canh": "C = d"}, "boi_canh") == "C = d"
