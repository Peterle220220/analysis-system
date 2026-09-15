"""Three readers: a PDF, a picture of text, and a recording of speech.

All code. No model is consulted, for the same reason A5 never consults one:
reading is a measurement, and a measurement that varies between runs is not one.
A model asked to "read" a scan would produce plausible text where the scan was
illegible, which is precisely the failure criterion S6 exists to catch.

Each returns the same shape - spans of text, each with where it came from and how
sure the reader was - so whatever consumes them does not need to know which of
the three produced them.
"""

from __future__ import annotations

import contextlib
import io
from dataclasses import dataclass
from typing import Any, Final

from analysis_system.domains.data_ingestion.extraction import ExtractionError

# Text shorter than this is punctuation or noise picked up by the reader, not
# content. Keeping it would drag the average confidence around for nothing.
MIN_SPAN_CHARS: Final[int] = 2
# OCR reports confidence per word, 0-100. Words it did not recognise at all come
# back as -1, which is not a low confidence but an absent one.
OCR_NOT_RECOGNISED: Final[float] = -1.0
# Whisper reports a log-probability per segment. This is the floor used when
# turning it into something on 0..1 that a person can read.
ASR_FLOOR: Final[float] = -1.5


@dataclass(frozen=True)
class RawSpan:
    """One piece of text as a reader found it, before it becomes a contract."""

    text: str
    confidence: float
    page: int = 0
    bbox: tuple[float, float, float, float] | None = None
    start_s: float = 0.0
    end_s: float = 0.0
    speaker: str = ""


def read_pdf(content: bytes) -> tuple[list[RawSpan], list[str]]:
    """Every line of text in a PDF, with the page it sits on.

    A PDF that carries a text layer is read exactly - the characters are already
    there and nothing is being guessed, so confidence is 1. A PDF that is a
    picture of a page carries no text layer at all, and this says so rather than
    returning nothing and letting a caller read that as an empty document.

    Returns:
        The spans, and anything it could not do.

    Raises:
        ExtractionError: the file is not a readable PDF.
    """
    import pdfplumber

    spans: list[RawSpan] = []
    declined: list[str] = []
    try:
        with pdfplumber.open(io.BytesIO(content)) as document:
            pages = len(document.pages)
            for number, page in enumerate(document.pages, start=1):
                text = page.extract_text() or ""
                for line in text.splitlines():
                    stripped = line.strip()
                    if len(stripped) >= MIN_SPAN_CHARS:
                        # A text layer is not a reading, it is a retrieval:
                        # the characters were stored, not recognised.
                        spans.append(RawSpan(text=stripped, confidence=1.0, page=number))
    except Exception as error:  # noqa: BLE001 - any malformed PDF is the same failure
        raise ExtractionError(f"khong doc duoc PDF: {error}") from error

    if not spans:
        declined.append(
            f"PDF {pages} trang khong co lop text nao - day la ANH CHUP trang giay, "
            "khong phai tai lieu co chu. Can OCR, va OCR thi co the doc sai."
        )
    return spans, declined


def read_pdf_tables(content: bytes) -> tuple[list[list[list[str]]], list[str]]:
    """Tables lifted whole out of a PDF.

    Separate from the text because a table is not prose: reading it as lines
    loses the columns, and the columns are usually the reason somebody sent a PDF
    rather than a spreadsheet.
    """
    import pdfplumber

    found: list[list[list[str]]] = []
    declined: list[str] = []
    try:
        with pdfplumber.open(io.BytesIO(content)) as document:
            for page in document.pages:
                for table in page.extract_tables():
                    rows = [
                        [str(cell) if cell is not None else "" for cell in row] for row in table
                    ]
                    if len(rows) > 1:
                        found.append(rows)
    except Exception as error:  # noqa: BLE001
        declined.append(f"khong tach duoc bang trong PDF: {error}")
    return found, declined


def read_image(content: bytes, *, languages: str = "vie+eng") -> tuple[list[RawSpan], list[str]]:
    """Text recognised in a picture, word by word, with where each word sat.

    Every word carries its own confidence and its own box, rather than one
    number for the whole page. A page read at 95% average with three illegible
    figures is a page with three wrong numbers in it, and the average says it is
    fine.

    Raises:
        ExtractionError: the image cannot be opened, or OCR is not installed.
    """
    import pytesseract
    from PIL import Image

    declined: list[str] = []
    try:
        with Image.open(io.BytesIO(content)) as picture:
            data = pytesseract.image_to_data(
                picture.convert("RGB"),
                lang=languages,
                output_type=pytesseract.Output.DICT,
            )
    except Exception as error:  # noqa: BLE001 - a missing binary and a broken file read alike
        raise ExtractionError(f"khong OCR duoc anh: {error}") from error

    spans: list[RawSpan] = []
    unrecognised = 0
    for index, word in enumerate(data.get("text", [])):
        stripped = str(word).strip()
        score = float(data.get("conf", [])[index])
        if score == OCR_NOT_RECOGNISED:
            # Not a low confidence - no reading at all. Counted, not scored:
            # averaging in a -1 would quietly drag the whole page down.
            unrecognised += 1
            continue
        if len(stripped) < MIN_SPAN_CHARS:
            continue
        left = float(data["left"][index])
        top = float(data["top"][index])
        spans.append(
            RawSpan(
                text=stripped,
                confidence=score / 100.0,
                page=1,
                bbox=(
                    left,
                    top,
                    left + float(data["width"][index]),
                    top + float(data["height"][index]),
                ),
            )
        )

    if unrecognised:
        declined.append(
            f"{unrecognised} vung trong anh khong doc ra chu nao. Do khong phai "
            "'doc duoc voi do tin cay thap' ma la 'khong doc duoc' - neu cho do co "
            "so lieu thi so lieu do dang thieu."
        )
    if not spans:
        declined.append("khong nhan ra chu nao trong anh.")
    return spans, declined


def read_audio(
    content: bytes, *, model_size: str = "tiny", language: str = "vi"
) -> tuple[list[RawSpan], list[str]]:
    """What was said, in segments, each with when it was said.

    The model is loaded on first use and not before: it is a few hundred
    megabytes, and a run that never sees a recording should never pay for it.

    Confidence comes from the model's own average log-probability per segment,
    mapped onto 0..1 so it reads the same way as OCR's. It is a rougher signal
    than OCR's - speech recognition is confident and wrong more often than
    character recognition is - so the threshold it feeds is doing more work here.

    Raises:
        ExtractionError: the audio cannot be read.
    """
    from faster_whisper import WhisperModel

    try:
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        segments, info = model.transcribe(io.BytesIO(content), language=language, vad_filter=True)
    except Exception as error:  # noqa: BLE001
        raise ExtractionError(f"khong nhan dang duoc am thanh: {error}") from error

    spans: list[RawSpan] = []
    for segment in segments:
        stripped = str(segment.text).strip()
        if len(stripped) < MIN_SPAN_CHARS:
            continue
        spans.append(
            RawSpan(
                text=stripped,
                confidence=_from_logprob(float(getattr(segment, "avg_logprob", ASR_FLOOR))),
                start_s=float(segment.start),
                end_s=float(segment.end),
            )
        )

    declined: list[str] = []
    if not spans:
        declined.append("khong nghe ra loi noi nao trong file am thanh.")
    else:
        declined.append(
            "chua tach duoc NGUOI NOI - moi doan deu khong ghi ai noi. Cau hoi "
            "kieu 'ai noi gi' chua tra loi duoc tu ban ghi nay."
        )
    with contextlib.suppress(AttributeError):
        if float(info.duration) > 0:
            declined.append(f"do dai ban ghi: {float(info.duration):.1f} giay.")
    return spans, declined


def _from_logprob(value: float) -> float:
    """Turn a mean log-probability into something on 0..1.

    Not a probability and not pretending to be one: it is a rank, so that a
    segment the model was unsure about sorts below one it was sure about and the
    same threshold can be applied to speech and to characters alike.
    """
    if value >= 0.0:
        return 1.0
    return max(0.0, min(1.0, 1.0 + value / abs(ASR_FLOOR)))


def rows_to_frame(rows: list[list[str]]) -> Any:
    """A table lifted from a document, as a frame with its first row as headers.

    Raises:
        ExtractionError: the table has no usable shape.
    """
    import pandas as pd

    if len(rows) < 2:
        raise ExtractionError("bang chi co mot dong - khong tach duoc tieu de.")
    header = [name.strip() or f"cot_{index + 1}" for index, name in enumerate(rows[0])]
    width = len(header)
    body = [row[:width] + [""] * (width - len(row)) for row in rows[1:]]
    return pd.DataFrame(body, columns=header)
