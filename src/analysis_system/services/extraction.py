"""Reading data out of things that are not tables, and saying how sure it is.

A CSV is already what it claims to be. A scanned invoice is a picture of one, a
recording is a person talking about one, and turning either into rows means
*deciding* what the characters and sounds were. Every one of those decisions can
be wrong, and the wrong ones look exactly like the right ones once they are text.

So nothing here reports text without reporting two other things beside it:

* **Where it came from** - which page, which region of it, which second of the
  recording. A figure extracted from a document is worth no more than a figure a
  model invented unless somebody can go and look at the place it came from.
* **How sure the reader was.** OCR and speech recognition both produce a
  confidence, and both are routinely wrong while sounding certain. Criterion S6
  says a poor extraction must not pass in silence, and a confidence nobody
  carried forward is exactly how it would.

The file type is decided by what is *in* the file, never by its extension. A
`.csv` holding a PDF is a mistake somebody made once and will make again, and
following the name would send it to a reader that cannot read it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

# Below this a reader was guessing. Not an error - a scan of a fax really is
# hard to read - but it is the line past which a person should look before the
# text is used for anything.
LOW_CONFIDENCE: Final[float] = 0.75
# When this share of what was read is below the line, the extraction as a whole
# needs somebody's eyes rather than a footnote.
REVIEW_SHARE: Final[float] = 0.15
# How much of a file to read when deciding what it is. Every signature below
# sits in the first few bytes; a longer read would only slow a routing decision.
MAGIC_BYTES: Final[int] = 16


class ExtractionError(RuntimeError):
    """A file cannot be read at all, as opposed to read badly."""


@dataclass(frozen=True)
class Signature:
    """One file type, and the bytes that identify it."""

    kind: str
    label: str
    magic: tuple[bytes, ...] = ()
    # Some formats identify themselves a few bytes in rather than at the start.
    offset: int = 0


# Ordered most specific first: a Matroska file and a WebM file share a
# signature, and whichever is listed first is the one that answers.
SIGNATURES: Final[tuple[Signature, ...]] = (
    # The format every clean table in this system is stored as, and the router
    # called it "khong nhan dang duoc" - a file the system writes itself, that
    # it could not recognise when handed back.
    Signature("table", "Parquet", (b"PAR1",)),
    Signature("pdf", "PDF", (b"%PDF-",)),
    Signature("image", "PNG", (b"\x89PNG\r\n\x1a\n",)),
    Signature("image", "JPEG", (b"\xff\xd8\xff",)),
    Signature("image", "GIF", (b"GIF87a", b"GIF89a")),
    Signature("image", "TIFF", (b"II*\x00", b"MM\x00*")),
    Signature("image", "BMP", (b"BM",)),
    Signature("audio", "WAV", (b"RIFF",)),
    Signature("audio", "MP3", (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")),
    Signature("audio", "FLAC", (b"fLaC",)),
    Signature("audio", "OGG", (b"OggS",)),
    Signature("audio", "MP4/M4A", (b"ftyp",), 4),
    # A zip container: .docx and .xlsx both live inside one, so this says only
    # that much and leaves the rest to whoever opens it.
    Signature("zip", "ZIP container", (b"PK\x03\x04", b"PK\x05\x06")),
)

# What a plain text file is, when nothing else matches and it decodes.
TEXT_KIND: Final[str] = "text"
UNKNOWN_KIND: Final[str] = "unknown"


@dataclass(frozen=True)
class FileKind:
    """What a file turned out to be."""

    kind: str
    label: str
    detail: str = ""

    @property
    def is_readable(self) -> bool:
        """True when some extractor can be asked to read this."""
        return self.kind not in {UNKNOWN_KIND}


def detect(path: Path) -> FileKind:
    """What this file actually is, from its contents.

    Never from the extension. A `.csv` holding a PDF is a mistake somebody makes
    regularly, and trusting the name sends it to a reader that cannot read it -
    which surfaces as a parsing error about column counts, nowhere near the
    truth.

    Raises:
        ExtractionError: the file cannot be opened at all.
    """
    try:
        with path.open("rb") as handle:
            head = handle.read(MAGIC_BYTES)
    except OSError as error:
        raise ExtractionError(f"khong mo duoc {path}: {error}") from error

    if not head:
        return FileKind(UNKNOWN_KIND, "rong", "file khong co byte nao")

    for signature in SIGNATURES:
        for magic in signature.magic:
            if head[signature.offset : signature.offset + len(magic)] == magic:
                return FileKind(signature.kind, signature.label)

    # Nothing recognised it. If it decodes as text it is text; if it does not,
    # saying "unknown" is more use than guessing.
    try:
        head.decode("utf-8")
    except UnicodeDecodeError:
        return FileKind(
            UNKNOWN_KIND,
            "khong nhan dang duoc",
            f"khong khop chu ky nao, va {MAGIC_BYTES} byte dau khong doc duoc thanh text",
        )
    return FileKind(TEXT_KIND, "text")


@dataclass(frozen=True)
class Confidence:
    """How sure a reader was, across everything it read."""

    mean: float
    lowest: float
    low_count: int
    total: int

    @property
    def low_share(self) -> float:
        """What fraction of what was read the reader was unsure about."""
        return self.low_count / self.total if self.total else 0.0

    @property
    def needs_review(self) -> bool:
        """True when somebody should look before this text is used.

        Not an error. A scan of a fax really is hard to read, and refusing it
        would leave a person with nothing. But criterion S6 says a poor
        extraction must not pass in silence, and this is the line past which
        silence is what it would be.
        """
        return self.total > 0 and self.low_share > REVIEW_SHARE

    def describe(self) -> str:
        """One sentence a person can act on."""
        if not self.total:
            return "khong doc duoc doan nao."
        said = (
            f"doc duoc {self.total} doan, tin cay trung binh {self.mean:.0%}, "
            f"thap nhat {self.lowest:.0%}"
        )
        if not self.low_count:
            return f"{said}; khong doan nao duoi {LOW_CONFIDENCE:.0%}."
        return (
            f"{said}; {self.low_count} doan duoi {LOW_CONFIDENCE:.0%} "
            "- can nguoi doi chieu lai truoc khi dung."
        )


def summarise(scores: Sequence[float]) -> Confidence:
    """Gather per-piece confidences into one picture.

    The mean alone hides the thing that matters: a document read at 95% average
    with three unreadable lines is a document with three wrong numbers in it, and
    the average says it is fine.
    """
    if not scores:
        return Confidence(mean=0.0, lowest=0.0, low_count=0, total=0)
    low = [score for score in scores if score < LOW_CONFIDENCE]
    return Confidence(
        mean=sum(scores) / len(scores),
        lowest=min(scores),
        low_count=len(low),
        total=len(scores),
    )
