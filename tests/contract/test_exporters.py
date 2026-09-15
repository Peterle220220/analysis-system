"""Xuat du lieu: dinh dang la lua chon cua nguoi doc, khong dinh gi toi dau vao."""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from analysis_system.domains.visualization.exporters import (
    DOCX_MAX_ROWS,
    ExportError,
    available,
    format_for,
    write,
)


def tickets() -> pd.DataFrame:
    """A small table with the things that break exports: unicode, a pipe, a gap."""
    return pd.DataFrame(
        {
            "ma_phieu": ["P001", "P002", "P003"],
            "nhom_van_de": ["Kỹ thuật", "Thanh toán | gấp", "Vận chuyển"],
            "gio_xu_ly": [24.5, None, 51.75],
        }
    )


# --- the reader chooses, and the input has no say ------------------------------


@pytest.mark.parametrize("name", ["csv", "xlsx", "docx", "md", "html", "json"])
def test_the_same_table_goes_out_in_every_format(tmp_path: Path, name: str) -> None:
    # One table, six destinations. Nothing here consults where the data came
    # from, which is the whole point: a PDF read into a table may leave as a
    # spreadsheet, and a spreadsheet may leave as a Word document.
    target = tmp_path / f"bang.{name}"
    assert write(tickets(), target, name) == name
    assert target.is_file()
    assert target.stat().st_size > 0


def test_the_file_extension_is_enough(tmp_path: Path) -> None:
    # "--out bao_cao.docx" says what it wants. Handing back a CSV would be its
    # own small betrayal.
    assert write(tickets(), tmp_path / "bao_cao.docx") == "docx"
    assert write(tickets(), tmp_path / "bang.xlsx") == "xlsx"


def test_an_explicit_format_beats_the_extension(tmp_path: Path) -> None:
    assert format_for(tmp_path / "bang.csv", "json") == "json"


# --- what comes back out ------------------------------------------------------


def test_a_spreadsheet_reads_back_as_the_same_table(tmp_path: Path) -> None:
    target = tmp_path / "bang.xlsx"
    write(tickets(), target)
    back = pd.read_excel(target)
    assert list(back.columns) == ["ma_phieu", "nhom_van_de", "gio_xu_ly"]
    assert back["nhom_van_de"][0] == "Kỹ thuật"
    assert back["gio_xu_ly"][2] == 51.75


def test_json_comes_out_as_rows_with_the_accents_intact(tmp_path: Path) -> None:
    target = tmp_path / "bang.json"
    write(tickets(), target)
    rows = json.loads(target.read_text(encoding="utf-8"))
    assert rows[0]["nhom_van_de"] == "Kỹ thuật"
    # A missing value is missing, not the string "nan".
    assert rows[1]["gio_xu_ly"] is None


def test_a_pipe_in_a_value_does_not_break_the_markdown_table(tmp_path: Path) -> None:
    # "Thanh toán | gấp" would otherwise open a column that is not there.
    target = tmp_path / "bang.md"
    write(tickets(), target)
    text = target.read_text(encoding="utf-8")
    # Counting "|" would count the escaped one too. Only unescaped pipes divide
    # columns, and every row must be divided the same number of times.
    separators = [len(re.findall(r"(?<!\\)\|", line)) for line in text.splitlines()]
    assert separators == [4, 4, 4, 4, 4]
    assert "Thanh toán \\| gấp" in text


def test_a_word_file_is_a_real_docx(tmp_path: Path) -> None:
    # A .docx is a zip. If it opens as one and carries the document part, Word
    # will open it - which is more than "the file is not empty" proves.
    target = tmp_path / "bao_cao.docx"
    write(tickets(), target)
    with zipfile.ZipFile(target) as archive:
        assert "word/document.xml" in archive.namelist()
        assert "Kỹ thuật" in archive.read("word/document.xml").decode("utf-8")


# --- refusals -----------------------------------------------------------------


def test_pdf_says_it_was_deferred_rather_than_unknown(tmp_path: Path) -> None:
    # "Unknown format" would suggest a typo. It was a decision, and the message
    # points at the decision and at the way round it.
    with pytest.raises(ExportError) as refused:
        format_for(tmp_path / "bao_cao.pdf")
    assert "HOAN" in str(refused.value)
    assert "html" in str(refused.value)


def test_an_unknown_format_lists_what_there_is(tmp_path: Path) -> None:
    with pytest.raises(ExportError) as refused:
        format_for(tmp_path / "bang.txt", "parquetish")
    assert "xlsx" in str(refused.value)


def test_a_file_with_no_extension_and_no_format_is_refused(tmp_path: Path) -> None:
    # Guessing here would mean picking a format on the reader's behalf.
    with pytest.raises(ExportError):
        format_for(tmp_path / "bang")


def test_a_table_too_big_for_word_is_refused_not_truncated(tmp_path: Path) -> None:
    # Losing rows without saying so is worse than not writing the file.
    big = pd.DataFrame({"n": range(DOCX_MAX_ROWS + 1)})
    with pytest.raises(ExportError) as refused:
        write(big, tmp_path / "to.docx")
    assert "xlsx" in str(refused.value)
    assert not (tmp_path / "to.docx").exists()


def test_every_listed_format_can_actually_be_written(tmp_path: Path) -> None:
    # The help text lists these. A name in the list that nothing can write is a
    # promise the command does not keep.
    for name in available().split(", "):
        assert write(tickets(), tmp_path / f"x.{name}", name) == name
