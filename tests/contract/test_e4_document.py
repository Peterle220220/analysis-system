"""E4: file Word, email va HTML - phan tich cu phap, khong phai nhan dang.

The distinction runs through every test here. E1 and E2 *read* something that
may be blurred, so confidence is a measurement. This one parses: the bytes
either are a Word document or they are not, and where they are not it fails
loudly rather than returning something it is unsure about.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from docx import Document

from analysis_system.agents.extractors import DocumentExtractor
from analysis_system.contracts.agents import ExtractionResult
from analysis_system.contracts.base import DataRef, ScopeToken, TaskRequest, TaskResult
from analysis_system.core.scoped_storage import ScopedStorage
from analysis_system.core.settings import LAYER_NAMES, LayerPaths, Settings, load_settings
from analysis_system.services.documents import read_docx, read_email, read_html
from analysis_system.services.extraction import ExtractionError

MANIFEST_DIR = Path("config/manifests")
NOW = datetime.now(UTC)

EMAIL = b"""From: an@congty.vn
To: binh@congty.vn
Subject: Bao cao thang muoi
Date: Mon, 1 Sep 2026 09:00:00 +0700
Content-Type: text/plain; charset="utf-8"

Doanh thu thang muoi dat 4880 ty dong.
Kenh buu dien dong gop 620 ty dong.
"""

HTML = b"""<!doctype html><html><head><title>Bo qua</title>
<style>body { color: red }</style><script>alert(1)</script></head>
<body><h1>Bao cao quy ba</h1><p>Doanh thu dat 4880 ty dong.</p>
<p>Ty le hoan la 9,4%.</p></body></html>"""


def word_file() -> bytes:
    """Mot file .docx that, co tieu de, doan van va mot bang."""
    document = Document()
    document.add_heading("Bao cao quy ba", level=1)
    document.add_paragraph("Doanh thu dat 4880 ty dong.")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Kenh"
    table.cell(0, 1).text = "Doanh thu"
    table.cell(1, 0).text = "Buu dien"
    table.cell(1, 1).text = "620 ty"
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Mot khong gian rieng, va lan nay thi rieng that.

    Ban dau fixture nay loc cac truong bang `isinstance(..., str)`, ma cac
    truong cua LayerPaths la Path - nen dieu kien khong bao gio dung, dict
    luon rong, va model_copy khong doi gi. Hai file test chay thang vao tang
    du lieu that cua nguoi dung, va chi lo ra khi don sach raw/ roi thay mot
    lan chay test sinh lai dung nhung file chung tao.
    """
    roots = {name: tmp_path / name for name in LAYER_NAMES}
    for root in roots.values():
        root.mkdir(parents=True, exist_ok=True)
    return load_settings().model_copy(update={"layers": LayerPaths(**roots)})


def token() -> ScopeToken:
    """A token matching the shipped e4_document manifest."""
    return ScopeToken(
        run_id="r_doc",
        task_id="t_doc",
        agent_id="e4_document",
        allow_read=("raw://**",),
        allow_write=("extracted://**",),
        allow_tools=(),
        params={},
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
    )


def run(settings: Settings, content: bytes, name: str) -> TaskResult:
    scope = token()
    writable = scope.model_copy(update={"allow_write": ("raw://**", "extracted://**")})
    ScopedStorage(writable, settings).save_bytes(content, f"raw://{name}")
    files = ScopedStorage(scope, settings)
    ref = DataRef(path=f"raw://{name}", format="blob", content_hash="a" * 64)
    return DocumentExtractor(settings, MANIFEST_DIR).execute(
        TaskRequest(scope=scope, input_refs=(ref,), instruction="doc"), files
    )


# --- Word ---------------------------------------------------------------------


def test_a_word_document_is_read_paragraph_by_paragraph() -> None:
    spans, notes = read_docx(word_file())
    text = " ".join(span.text for span in spans)
    assert "Doanh thu dat 4880 ty dong." in text
    assert not notes


def test_a_heading_keeps_its_level() -> None:
    # A reader uses headings to place a paragraph in the document. A flat list
    # of sentences has lost that.
    spans, _ = read_docx(word_file())
    assert any(span.text.startswith("# Bao cao quy ba") for span in spans)


def test_a_table_keeps_its_rows_together() -> None:
    # Read cell by cell, a table becomes a pile of words with the columns gone.
    spans, _ = read_docx(word_file())
    assert any("Buu dien | 620 ty" in span.text for span in spans)


def test_a_table_is_not_left_until_the_end() -> None:
    # python-docx lists paragraphs and tables separately, so reading one list
    # then the other puts every table after all the prose - and a table torn
    # from the paragraph that introduces it has lost what it was for.
    spans, _ = read_docx(word_file())
    order = [span.text for span in spans]
    assert order.index("Doanh thu dat 4880 ty dong.") < order.index("Kenh | Doanh thu")


def test_bytes_that_are_not_a_word_file_fail_loudly() -> None:
    # Parsing, not reading: there is no "unsure" answer available here.
    with pytest.raises(ExtractionError):
        read_docx(b"khong phai file word")


# --- email --------------------------------------------------------------------


def test_an_email_carries_who_wrote_it_and_when() -> None:
    # A mail read without its headers is a paragraph with no author and no
    # date, and both are usually why somebody is reading it.
    spans, _ = read_email(EMAIL)
    text = " ".join(span.text for span in spans)
    assert "From: an@congty.vn" in text
    assert "Subject: Bao cao thang muoi" in text
    assert "Doanh thu thang muoi dat 4880 ty dong." in text


def test_an_attachment_is_named_but_not_opened() -> None:
    # Opening one means routing it back through whichever reader fits, which
    # is A0's job. Saying nothing would make a mail whose content is in its
    # attachment read as an empty mail.
    with_file = EMAIL.replace(
        b'Content-Type: text/plain; charset="utf-8"',
        b'Content-Type: multipart/mixed; boundary="BOUND"\n'
        b"\n--BOUND\nContent-Type: text/plain\n\nNoi dung chinh.\n"
        b"\n--BOUND\nContent-Type: application/pdf\n"
        b'Content-Disposition: attachment; filename="phu_luc.pdf"\n\nPDFBYTES\n--BOUND--',
    )
    _, notes = read_email(with_file)
    assert any("phu_luc.pdf" in note for note in notes)


# --- HTML ---------------------------------------------------------------------


def test_html_gives_the_words_and_not_the_markup() -> None:
    spans, _ = read_html(HTML)
    text = " ".join(span.text for span in spans)
    assert "Bao cao quy ba" in text
    assert "Ty le hoan la 9,4%." in text
    assert "<p>" not in text


def test_script_and_style_are_not_text() -> None:
    # They are instructions to a machine. Read as prose they would appear in
    # the term counts as though somebody had written them.
    spans, _ = read_html(HTML)
    text = " ".join(span.text for span in spans)
    assert "alert" not in text
    assert "color: red" not in text


def test_blocks_do_not_run_into_one_another() -> None:
    spans, _ = read_html(HTML)
    assert any(span.text == "Ty le hoan la 9,4%." for span in spans)


# --- the agent ------------------------------------------------------------------


def test_the_format_is_decided_by_the_bytes_not_the_name(settings: Settings) -> None:
    # A name is something somebody typed. The zip either holds a
    # word/document.xml or it does not.
    result = run(settings, word_file(), "ten_sai.txt")
    assert result.status == "OK", result.error
    assert ExtractionResult.model_validate(result.payload).kind == "document"


def test_each_of_the_three_formats_reaches_the_agent(settings: Settings) -> None:
    for content, name in ((word_file(), "a.docx"), (EMAIL, "b.eml"), (HTML, "c.html")):
        result = run(settings, content, name)
        assert result.status == "OK", (name, result.error)
        assert result.metrics["spans"] > 0


def test_a_format_none_of_the_three_covers_is_refused_with_advice(
    settings: Settings,
) -> None:
    # Including the one somebody will actually hit: Outlook's .msg.
    result = run(settings, b"\xd0\xcf\x11\xe0 khong phai loai nao", "thu.msg")
    assert result.status == "FAILED"
    assert result.error is not None
    assert ".eml" in result.error.message


def test_a_parsed_document_is_certain_rather_than_merely_confident(
    settings: Settings,
) -> None:
    # E1 and E2 measure how sure the reading was, because a scan can be
    # blurred. Nothing here is unsure: it parsed or it failed.
    result = run(settings, word_file(), "a.docx")
    assert result.metrics["mean_confidence"] == 1.0
    assert result.metrics["low_confidence_spans"] == 0.0


def test_it_says_when_what_it_read_is_prose_rather_than_data(settings: Settings) -> None:
    # The difference between "here is your data" and "here is some text that
    # mentions numbers".
    result = run(settings, EMAIL, "b.eml")
    assert any("chua phai du lieu co cau truc" in note for note in result.declined)
