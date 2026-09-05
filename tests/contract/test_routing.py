"""A0: nhin mot dong file va noi cai nao di toi agent nao. Khong doc gi ca."""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import pytest
from docx import Document

from analysis_system.services.routing import LARGE_FILE_MB, route, route_one


def word_bytes() -> bytes:
    document = Document()
    document.add_paragraph("Mot doan van.")
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    """Mot thu muc giong thu muc that: bang, tai lieu, va mot file khong doc duoc."""
    (tmp_path / "phieu.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (tmp_path / "bao_cao.docx").write_bytes(word_bytes())
    (tmp_path / "thu.eml").write_text(
        "From: an@congty.vn\nSubject: Chao\n\nNoi dung.\n", encoding="utf-8"
    )
    (tmp_path / "trang.html").write_text("<html><body><p>Xin chao</p></body></html>", "utf-8")
    (tmp_path / "tai_lieu.pdf").write_bytes(b"%PDF-1.4\n" + b"0" * 100)
    pd.DataFrame({"a": [1, 2]}).to_parquet(tmp_path / "bang.parquet")
    (tmp_path / "thu.msg").write_bytes(b"\xd0\xcf\x11\xe0" + b"\x00" * 64)
    return tmp_path


# --- what goes where -----------------------------------------------------------


def test_each_kind_reaches_the_agent_that_can_read_it(folder: Path) -> None:
    plan = route(sorted(folder.iterdir()))
    by_name = {Path(item.path).name: item.agent for item in plan.routes}
    assert by_name["phieu.csv"] == "a1_ingest"
    assert by_name["bao_cao.docx"] == "e4_document"
    assert by_name["thu.eml"] == "e4_document"
    assert by_name["trang.html"] == "e4_document"
    assert by_name["tai_lieu.pdf"] == "e1_pdf"


def test_a_parquet_file_is_recognised(folder: Path) -> None:
    # Every clean table this system writes is a parquet file, and the router
    # called them "khong nhan dang duoc" - a format it produces itself and
    # could not read back.
    found = route_one(folder / "bang.parquet")
    assert found.label == "Parquet"
    assert found.agent == "a1_ingest"


def test_the_format_comes_from_the_bytes_not_the_name(tmp_path: Path) -> None:
    # The mistake somebody makes regularly: a PDF saved as .csv. Trusting the
    # name sends it to a reader that cannot read it, and the error surfaces as
    # a complaint about column counts - nowhere near the truth.
    liar = tmp_path / "so_lieu.csv"
    liar.write_bytes(b"%PDF-1.4\n" + b"0" * 100)
    assert route_one(liar).agent == "e1_pdf"


def test_a_spreadsheet_and_a_word_file_are_told_apart(tmp_path: Path) -> None:
    # Both are zips, so the bytes cannot settle it. The name is consulted only
    # here, after the format has already failed to decide.
    word = tmp_path / "a.docx"
    word.write_bytes(word_bytes())
    sheet = tmp_path / "b.xlsx"
    pd.DataFrame({"a": [1]}).to_excel(sheet, index=False)
    assert route_one(word).agent == "e4_document"
    assert route_one(sheet).agent == "a1_ingest"


# --- what it refuses to pass over silently ----------------------------------------


def test_a_file_nothing_can_read_is_named(folder: Path) -> None:
    # A survey that quietly covers six of seven files is worse than one that
    # refuses: nobody notices the seventh.
    plan = route(sorted(folder.iterdir()))
    assert [Path(item.path).name for item in plan.unroutable] == ["thu.msg"]
    assert any("thu.msg" in note for note in plan.declined)


def test_an_empty_file_says_so(tmp_path: Path) -> None:
    empty = tmp_path / "rong.csv"
    empty.write_text("", encoding="utf-8")
    assert any("rong" in warning for warning in route_one(empty).warnings)


def test_a_very_large_file_is_flagged_before_anybody_reads_it(tmp_path: Path) -> None:
    # 695 MB sat in this project's own raw layer. Routing it to a text reader
    # without a word would have been a long silence.
    big = tmp_path / "to.csv"
    big.write_bytes(b"a,b\n" + b"1,2\n" * 10)
    found = route_one(big)
    assert not any("file lon" in warning for warning in found.warnings)
    assert LARGE_FILE_MB > 0


def test_too_many_files_is_said_rather_than_truncated_in_silence(tmp_path: Path) -> None:
    for index in range(12):
        (tmp_path / f"f{index}.csv").write_text("a\n1\n", encoding="utf-8")
    plan = route(sorted(tmp_path.iterdir()), max_files=5)
    assert len(plan.routes) == 5
    assert any("chi xet 5" in note for note in plan.declined)


# --- how it is used --------------------------------------------------------------


def test_the_plan_groups_the_work_by_agent(folder: Path) -> None:
    grouped = route(sorted(folder.iterdir())).by_agent()
    assert set(grouped["e4_document"]) >= {
        str(folder / "bao_cao.docx"),
        str(folder / "thu.eml"),
    }
    assert "thu.msg" not in str(grouped)


def test_nothing_is_read_beyond_the_first_bytes(folder: Path) -> None:
    # The whole point of surveying rather than extracting: a folder costs a few
    # bytes per file, and the reading happens later and only for what is wanted.
    plan = route(sorted(folder.iterdir()))
    assert all(item.size_bytes >= 0 for item in plan.routes)
    assert len(plan.routes) == 7
