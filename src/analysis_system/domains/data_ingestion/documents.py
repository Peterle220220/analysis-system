"""E4: doc tai lieu - Word, email, HTML - thanh cung mot hinh dang nhu ba reader kia.

The fourth reader, and the one that needed no new machinery: a `.docx`, an
`.eml` and an `.html` file are all text somebody wrote, and the shape that
carries a PDF page carries them too.

Confidence is 1.0 throughout, and that is a statement rather than a default. A
PDF scan and a photograph are *read*, so how sure the reader was is a real
measurement. A Word document and an email are *parsed*: the bytes say what the
text is, and there is nothing to be unsure about. Where a file cannot be parsed
it fails loudly instead of coming back with a low score.

Structure is kept where it carries meaning and dropped where it does not.
Headings and list markers survive because a reader uses them to find their way;
fonts and colours do not, because nothing downstream can use them.

`.msg` - Outlook's own format - is not here. It needs `extract-msg`, and an
`.eml` export of the same mail reads perfectly with the standard library, so
the dependency buys one export step somebody does once.
"""

from __future__ import annotations

import io
import zipfile
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from html.parser import HTMLParser
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from docx.document import Document as WordDocument
    from docx.table import Table as WordTable
    from docx.text.paragraph import Paragraph as WordParagraph

from analysis_system.domains.data_ingestion.extraction import ExtractionError
from analysis_system.domains.data_ingestion.readers import MIN_SPAN_CHARS, RawSpan

# Parsed, not recognised: the bytes say what the text is.
CERTAIN: Final[float] = 1.0

# Header fields worth carrying into the text. Who wrote it, to whom, when and
# about what are part of what an email says; the routing headers are not.
MAIL_HEADERS: Final[tuple[str, ...]] = ("from", "to", "cc", "date", "subject")


def read_docx(content: bytes) -> tuple[list[RawSpan], list[str]]:
    """Every paragraph and table cell of a Word document, in reading order.

    Headings keep their level as a marker, because a reader uses them to place
    a paragraph in the document and a flat list of sentences loses that.

    Raises:
        ExtractionError: the bytes are not a readable .docx.
    """
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        document = Document(io.BytesIO(content))
    except (ValueError, KeyError, zipfile.BadZipFile) as error:
        raise ExtractionError(f"Khong doc duoc file Word: {error}") from error

    spans: list[RawSpan] = []
    notes: list[str] = []
    for block in _blocks(document):
        if isinstance(block, Paragraph):
            text = block.text.strip()
            if len(text) < MIN_SPAN_CHARS:
                continue
            spans.append(RawSpan(text=_marked(block, text), confidence=CERTAIN))
        elif isinstance(block, Table):
            rows, table_notes = _table_rows(block)
            spans.extend(rows)
            notes.extend(table_notes)

    if not spans:
        notes.append("file Word khong co doan van ban nao doc duoc.")
    return spans, notes


def _blocks(document: WordDocument) -> list[WordParagraph | WordTable]:
    """Paragraphs and tables in the order they appear in the document.

    python-docx exposes the two as separate lists, so reading them one after the
    other puts every table at the end - and a table torn out of the paragraph
    that introduces it has lost what it was for.
    """
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    body = document.element.body
    found: list[WordParagraph | WordTable] = []
    for child in body.iterchildren():
        if child.tag.endswith("}p"):
            found.append(Paragraph(child, document))
        elif child.tag.endswith("}tbl"):
            found.append(Table(child, document))
    return found


def _marked(paragraph: WordParagraph, text: str) -> str:
    """A heading carries its level; a list item carries a bullet."""
    style = str(getattr(getattr(paragraph, "style", None), "name", "") or "")
    if style.startswith("Heading"):
        level = style.removeprefix("Heading").strip() or "1"
        return f"{'#' * min(int(level) if level.isdigit() else 1, 6)} {text}"
    if "List" in style:
        return f"- {text}"
    return text


def _table_rows(table: WordTable) -> tuple[list[RawSpan], list[str]]:
    """One span per row, cells separated the way a person would read them out."""
    spans: list[RawSpan] = []
    for row in table.rows:
        cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
        line = " | ".join(cell for cell in cells if cell)
        if len(line) >= MIN_SPAN_CHARS:
            spans.append(RawSpan(text=line, confidence=CERTAIN))
    return spans, []


class _TextFromHtml(HTMLParser):
    """Text with the tags removed and the block structure kept as line breaks."""

    # Everything inside these is instruction to a machine, not text to a reader.
    SILENT: Final[frozenset[str]] = frozenset({"script", "style", "head"})
    # Tags after which a line ends, so paragraphs do not run into each other.
    BREAKS: Final[frozenset[str]] = frozenset(
        {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table"}
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self._current: list[str] = []
        self._muted = 0

    def handle_starttag(self, tag: str, _attrs: object) -> None:
        if tag in self.SILENT:
            self._muted += 1
        elif tag in self.BREAKS:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SILENT:
            self._muted = max(0, self._muted - 1)
        elif tag in self.BREAKS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if not self._muted and data.strip():
            self._current.append(data.strip())

    def _flush(self) -> None:
        line = " ".join(self._current).strip()
        self._current = []
        if len(line) >= MIN_SPAN_CHARS:
            self.lines.append(line)

    def finish(self) -> list[str]:
        """Everything read, including whatever was still being built."""
        self._flush()
        return self.lines


def read_html(content: bytes) -> tuple[list[RawSpan], list[str]]:
    """The text of an HTML document, with scripts and styling left out.

    The standard library rather than a parsing package: what is wanted here is
    the words, and `HTMLParser` gives them. A dependency would buy tolerance of
    badly broken markup, which is not what arrives from a mail client or an
    export.
    """
    parser = _TextFromHtml()
    parser.feed(content.decode("utf-8", errors="replace"))
    lines = parser.finish()
    if not lines:
        return [], ["file HTML khong co van ban nao ngoai the va script."]
    return [RawSpan(text=line, confidence=CERTAIN) for line in lines], []


def read_email(content: bytes) -> tuple[list[RawSpan], list[str]]:
    """An email: who, to whom, when, about what, and then what it said.

    The headers come first and as text, because a mail read without them is a
    paragraph with no author and no date - and both are usually the reason
    somebody is reading it.

    Attachments are named but not opened. Opening them means routing each one
    back through whichever reader fits, and that is A0's job, not this one's.

    Raises:
        ExtractionError: the bytes are not a readable message.
    """
    try:
        message = BytesParser(policy=policy.default).parsebytes(content)
    except Exception as error:  # noqa: BLE001 - any parse failure is the same answer
        raise ExtractionError(f"Khong doc duoc email: {error}") from error

    spans: list[RawSpan] = []
    for field in MAIL_HEADERS:
        value = str(message.get(field, "") or "").strip()
        if value:
            spans.append(RawSpan(text=f"{field.capitalize()}: {value}", confidence=CERTAIN))

    body, notes = _mail_body(message)
    spans.extend(body)

    attachments = [
        part.get_filename() for part in message.iter_attachments() if part.get_filename()
    ]
    if attachments:
        # Named rather than opened, and said out loud: a mail whose content is
        # in its attachment would otherwise read as an empty mail.
        notes.append(
            "email co tep dinh kem chua duoc doc: "
            + ", ".join(str(name) for name in attachments[:5])
        )
    if not body:
        notes.append("email khong co phan noi dung doc duoc.")
    return spans, notes


def _mail_body(message: EmailMessage) -> tuple[list[RawSpan], list[str]]:
    """The body, preferring the plain text part over the HTML one."""
    part = message.get_body(preferencelist=("plain", "html"))
    if part is None:
        return [], []
    payload = part.get_content()
    if part.get_content_subtype() == "html":
        spans, notes = read_html(str(payload).encode("utf-8"))
        return spans, notes
    lines = [line.strip() for line in str(payload).splitlines()]
    return [
        RawSpan(text=line, confidence=CERTAIN) for line in lines if len(line) >= MIN_SPAN_CHARS
    ], []


def read_document(content: bytes) -> tuple[list[RawSpan], list[str]]:
    """Whichever of the three this is, read into the same shape as the rest.

    The format is decided by the bytes, never by the file name. A name is
    something somebody typed; a zip either holds `word/document.xml` or it does
    not, and an email either begins with headers or it does not.

    Raises:
        ExtractionError: the bytes are none of the three, or are damaged.
    """
    if _is_docx(content):
        return read_docx(content)
    if _is_email(content):
        return read_email(content)
    if _is_html(content):
        return read_html(content)
    raise ExtractionError(
        "E4 doc duoc .docx, email (.eml) va HTML. File nay khong phai loai nao trong "
        "ba - neu la .msg cua Outlook thi xuat sang .eml roi thu lai."
    )


def _is_docx(content: bytes) -> bool:
    """True for a Word document, read from the zip rather than from a name."""
    if not content.startswith(b"PK"):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            return "word/document.xml" in archive.namelist()
    except zipfile.BadZipFile:
        return False


def _is_email(content: bytes) -> bool:
    """True when the file begins the way a mail message begins.

    Only the first few lines are looked at, and a header line is a name, a
    colon and a value. A prose file whose first line happens to contain a colon
    fails the test because the name would have to be a header field, and that
    list is short.
    """
    head = content[:2048].decode("utf-8", errors="replace").splitlines()
    known = {"from", "to", "subject", "date", "received", "message-id", "return-path"}
    for line in head[:12]:
        if not line.strip():
            break
        name, separator, _ = line.partition(":")
        if separator and name.strip().lower() in known:
            return True
    return False


def _is_html(content: bytes) -> bool:
    """True when the text carries markup rather than merely angle brackets."""
    head = content[:2048].decode("utf-8", errors="replace").lower()
    return "<html" in head or "<!doctype html" in head or "<body" in head
