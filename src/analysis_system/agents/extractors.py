"""E1, E2, E3: read a document, a picture and a recording into the same shape.

One base class, three readers. The part that differs between reading a PDF and
reading a recording is one function call; everything else - assembling spans,
measuring confidence, writing the result, deciding whether a person should look -
is the same work, and writing it three times would mean fixing it three times.

They keep separate agent ids and separate manifests because their boundaries
really are different: the agent that runs OCR has no business loading a speech
model, and a manifest is how that is said.

**None of them consults a model.** Reading is a measurement. A model asked to
read an illegible scan produces plausible text exactly where the scan was
illegible, which is the failure criterion S6 exists to catch - and it would
produce it with no confidence attached, because it was never unsure.
"""

from __future__ import annotations

from typing import ClassVar, Final

from analysis_system.agents.base import BaseAgent
from analysis_system.core.scoped_storage import ScopedStorage
from analysis_system.domains.data_ingestion.documents import read_document
from analysis_system.domains.data_ingestion.extraction import ExtractionError, summarise
from analysis_system.domains.data_ingestion.readers import (
    RawSpan,
    read_audio,
    read_image,
    read_pdf,
    read_pdf_tables,
    rows_to_frame,
)
from analysis_system.models.agents import (
    ExtractedSpan,
    ExtractionResult,
    SourceLocator,
)
from analysis_system.models.base import DataRef, ErrorDetail, TaskRequest, TaskResult

EXTRACTED_PREFIX: Final[str] = "extracted://"
LANGUAGES_PARAM: Final[str] = "languages"
MODEL_PARAM: Final[str] = "asr_model"
# Present once a person has looked at the doubtful spans. Its presence is
# what tells this agent it has already asked and been answered.
APPROVED_PARAM: Final[str] = "approved_spans"


class ExtractorAgent(BaseAgent):
    """Turn one file into text that can be traced back to where it came from.

    Subclasses supply the reader and their own id. Everything else is shared,
    including the one decision that matters: whether what was read is clear
    enough to use without a person looking at it first.
    """

    agent_id: ClassVar[str] = "e0_extractor"
    kind: ClassVar[str] = "unknown"

    def read(self, content: bytes, request: TaskRequest) -> tuple[list[RawSpan], list[str]]:
        """Read the bytes. The one thing that differs between extractors."""
        raise NotImplementedError

    def tables(self, _content: bytes) -> tuple[list[list[list[str]]], list[str]]:
        """Any tables the format carries whole. Most formats carry none."""
        return [], []

    def execute(self, request: TaskRequest, files: ScopedStorage) -> TaskResult:
        """Read the source, measure how sure the reading was, and write it down."""
        if not request.input_refs:
            return self._failed(request, "NO_INPUT", f"{self.agent_id} can mot file de doc.")

        source = request.input_refs[0]
        try:
            # Bytes, never a path: a path walks straight round the boundary the
            # scope exists to draw.
            content = files.load_bytes(source.path)
            spans, declined = self.read(content, request)
            rows, table_notes = self.tables(content)
        except ExtractionError as error:
            return self._failed(request, "UNREADABLE", str(error))

        if not spans:
            # Nothing was read at all. That is not a poor extraction to be
            # flagged, it is an absent one, and calling it OK would hand the next
            # task an empty file with a clean bill of health.
            return self._failed(
                request,
                "NOTHING_READ",
                "khong doc ra noi dung nao tu file. " + "; ".join(declined),
            )

        confidence = summarise([span.confidence for span in spans])
        reviewed = request.scope.params.get(APPROVED_PARAM) is not None
        written: list[DataRef] = []
        for index, table in enumerate(rows, start=1):
            try:
                frame = rows_to_frame(table)
            except ExtractionError as error:
                table_notes.append(f"bang {index}: {error}")
                continue
            stem = f"{request.scope.run_id}_{request.scope.task_id}"
            target = f"{EXTRACTED_PREFIX}{stem}_bang{index}.parquet"
            written.append(files.save_parquet(frame, target))

        if not written:
            # Said plainly, because it is the difference between "here is your
            # data" and "here is some prose that mentions numbers". Turning
            # sentences into rows is a different problem from reading them.
            table_notes.append(
                "khong tim thay bang nao trong file - phan doc duoc la VAN BAN, "
                "chua phai du lieu co cau truc de phan tich."
            )

        result = ExtractionResult(
            source=source.path,
            kind=self.kind,
            spans=tuple(_as_span(span) for span in spans),
            tables=tuple(ref.path for ref in written),
            mean_confidence=round(confidence.mean, 4),
            lowest_confidence=round(confidence.lowest, 4),
            low_confidence_spans=confidence.low_count,
            declined=(*declined, *table_notes),
        )
        target = (
            f"{EXTRACTED_PREFIX}{request.scope.run_id}_{request.scope.task_id}_{self.kind}.json"
        )
        artifact = files.save_text(result.model_dump_json(indent=2), target)

        return TaskResult(
            task_id=request.scope.task_id,
            agent_id=self.agent_id,
            # A poor reading stops for a person rather than flowing on -
            # criterion S6 asks exactly that. Asked once: a decision already
            # recorded means somebody has looked, and asking again would make
            # the run unresumable.
            status=("NEEDS_REVIEW" if confidence.needs_review and not reviewed else "OK"),
            # Data first, report last. Whoever reads this next wants the
            # table; the report describes how it was read. Ordering alone
            # is not a guarantee - the consumer also asks for what it
            # needs - but it makes the common case the obvious one.
            output_refs=(*written, artifact),
            declined=(
                result.declined
                if not reviewed
                else (*result.declined, "cac doan doc chua chac da duoc nguoi doi chieu.")
            ),
            metrics={
                "spans": float(len(spans)),
                "tables": float(len(written)),
                "mean_confidence": round(confidence.mean, 4),
                "low_confidence_spans": float(confidence.low_count),
            },
            payload=result.model_dump(mode="json"),
        )

    def _failed(self, request: TaskRequest, code: str, message: str) -> TaskResult:
        """Report an honest failure, with nothing written."""
        return TaskResult(
            task_id=request.scope.task_id,
            agent_id=self.agent_id,
            status="FAILED",
            error=ErrorDetail(code=code, message=message, retryable=False, replannable=False),
        )


def _as_span(span: RawSpan) -> ExtractedSpan:
    """One reading, with where it came from attached and not optional."""
    if span.end_s or span.start_s:
        locator = SourceLocator(
            kind="time", start_s=span.start_s, end_s=span.end_s, speaker=span.speaker
        )
    elif span.bbox is not None:
        locator = SourceLocator(kind="region", page=span.page, bbox=span.bbox)
    else:
        locator = SourceLocator(kind="page", page=span.page)
    return ExtractedSpan(text=span.text, locator=locator, confidence=round(span.confidence, 4))


class PdfExtractor(ExtractorAgent):
    """E1. A document with a text layer, read exactly; one without, refused clearly."""

    agent_id: ClassVar[str] = "e1_pdf"
    kind: ClassVar[str] = "pdf"

    def read(self, content: bytes, _request: TaskRequest) -> tuple[list[RawSpan], list[str]]:
        """Every line, with the page it sits on."""
        return read_pdf(content)

    def tables(self, content: bytes) -> tuple[list[list[list[str]]], list[str]]:
        """Tables lifted whole, because reading them as lines loses the columns."""
        return read_pdf_tables(content)


class ImageExtractor(ExtractorAgent):
    """E2. A picture of text, recognised word by word with a box round each word."""

    agent_id: ClassVar[str] = "e2_image"
    kind: ClassVar[str] = "image"

    def read(self, content: bytes, request: TaskRequest) -> tuple[list[RawSpan], list[str]]:
        """Words, each with its own confidence and its own place on the page.

        Per word rather than per page: a page read at ninety-five per cent with
        three illegible figures is a page with three wrong numbers in it, and the
        average says it is fine.
        """
        languages = str(request.scope.params.get(LANGUAGES_PARAM) or "vie+eng")
        return read_image(content, languages=languages)


class DocumentExtractor(ExtractorAgent):
    """E4. A Word file, an email or a web page: text somebody wrote, parsed.

    One agent for three formats because the decision between them is not a
    judgement - the bytes say which is which. A `.docx` is a zip with a
    `word/document.xml` in it, an email begins with headers, and anything else
    that decodes as text with tags in it is markup. Guessing from the file
    extension would mean trusting a name somebody typed.

    Confidence is 1.0 and that is a claim, not a placeholder. E1 and E2 *read* -
    a scan can be blurred, a photograph can be dark, and how sure the reader was
    is a real measurement that criterion S6 acts on. This one *parses*: either
    the bytes are a Word document or they are not, and if they are not it fails
    and says so rather than returning something unsure.
    """

    agent_id: ClassVar[str] = "e4_document"
    kind: ClassVar[str] = "document"

    def read(self, content: bytes, _request: TaskRequest) -> tuple[list[RawSpan], list[str]]:
        """Whichever of the three this is, read into the same shape as the rest.

        Raises:
            ExtractionError: the bytes are none of the three, or are damaged.
        """
        return read_document(content)


class AudioExtractor(ExtractorAgent):
    """E3. A recording, transcribed in segments, each with when it was said."""

    agent_id: ClassVar[str] = "e3_audio"
    kind: ClassVar[str] = "audio"

    def read(self, content: bytes, request: TaskRequest) -> tuple[list[RawSpan], list[str]]:
        """What was said and when. Who said it is not yet answered, and says so."""
        size = str(request.scope.params.get(MODEL_PARAM) or "tiny")
        language = str(request.scope.params.get(LANGUAGES_PARAM) or "vi")
        return read_audio(content, model_size=size, language=language)
