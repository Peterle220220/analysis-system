"""Reading data out of things that are not tables.

Two rules carry the weight here and both are criterion S6: what was read must say
*where it came from*, and it must say *how sure the reader was*. A figure lifted
from a scan with neither is worth exactly as much as one a model invented.

The files are generated rather than committed, so the tests exercise the real
libraries on real bytes without carrying binaries in the repository.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from analysis_system.agents.extractors import (
    ExtractorAgent,
    ImageExtractor,
    PdfExtractor,
)
from analysis_system.contracts.agents import ExtractionResult
from analysis_system.contracts.base import DataRef, ScopeToken, TaskRequest, TaskResult
from analysis_system.manager.gates import span_options
from analysis_system.services import storage
from analysis_system.services.extraction import (
    LOW_CONFIDENCE,
    REVIEW_SHARE,
    ExtractionError,
    detect,
    summarise,
)
from analysis_system.services.readers import (
    _from_logprob,
    read_audio,
    read_image,
    read_pdf,
    read_pdf_tables,
    rows_to_frame,
)
from analysis_system.services.scoped_storage import ScopedStorage
from analysis_system.settings import (
    LAYER_NAMES,
    LayerPaths,
    Settings,
    load_settings,
    resolve,
)

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
MANIFEST_DIR = Path(__file__).resolve().parents[2] / "config" / "manifests"


def settings_in(root: Path) -> Settings:
    roots = {name: root / name for name in LAYER_NAMES}
    for path in roots.values():
        path.mkdir(parents=True, exist_ok=True)
    return load_settings().model_copy(update={"layers": LayerPaths(**roots)})


def token(agent_id: str, params: dict[str, object] | None = None) -> ScopeToken:
    """A token matching the shipped extractor manifests."""
    return ScopeToken(
        run_id="r_ex",
        task_id="t_read",
        agent_id=agent_id,
        allow_read=("raw://**",),
        allow_write=("extracted://**",),
        allow_tools=("pdfplumber", "pypdf", "pytesseract", "pillow", "pandas"),
        params=params or {},
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=30),
    )


def a_pdf() -> bytes:
    """A one-page report with a paragraph and a table."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    buffer = io.BytesIO()
    with PdfPages(buffer) as pdf:
        figure = plt.figure(figsize=(8.27, 11.69))
        figure.text(0.1, 0.9, "BAO CAO QUY 3", size=16)
        figure.text(0.1, 0.85, "Tong doanh thu dat muc cao nhat trong nam.", size=11)
        axes = figure.add_axes((0.1, 0.55, 0.8, 0.22))
        axes.axis("off")
        axes.table(
            cellText=[["Truc tuyen", "2800"], ["Cua hang", "900"]],
            colLabels=["Kenh", "Doanh thu"],
            loc="center",
        )
        pdf.savefig(figure)
        plt.close(figure)
    return buffer.getvalue()


def an_image(*, blur: float = 0.0) -> bytes:
    """A picture of two lines of text, optionally hard to read."""
    from PIL import Image, ImageDraw, ImageFilter

    picture = Image.new("RGB", (900, 220), "white")
    draw = ImageDraw.Draw(picture)
    draw.text((25, 50), "Doanh thu 4823 trieu dong", fill="black")
    draw.text((25, 130), "So don hang 1645", fill="black")
    picture = picture.resize((1800, 440), Image.Resampling.LANCZOS)
    if blur:
        picture = picture.filter(ImageFilter.GaussianBlur(blur))
    buffer = io.BytesIO()
    picture.save(buffer, format="PNG")
    return buffer.getvalue()


# --- what a file actually is -------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "kind"),
    [
        (b"%PDF-1.7\nrest", "pdf"),
        (b"\x89PNG\r\n\x1a\n....", "image"),
        (b"\xff\xd8\xff\xe0....", "image"),
        (b"RIFF....WAVE", "audio"),
        (b"ID3\x03....", "audio"),
        (b"OggS....", "audio"),
        (b"PK\x03\x04....", "zip"),
        (b"ten,gia\n1,2\n", "text"),
    ],
)
def test_a_file_is_what_its_bytes_say_it_is(tmp_path: Path, content: bytes, kind: str) -> None:
    path = tmp_path / "x.bin"
    path.write_bytes(content)
    assert detect(path).kind == kind


def test_the_extension_is_never_believed(tmp_path: Path) -> None:
    # A .csv holding a PDF is a mistake somebody makes regularly, and trusting
    # the name sends it to a reader that cannot read it - which surfaces as an
    # error about column counts, nowhere near the truth.
    path = tmp_path / "du_lieu.csv"
    path.write_bytes(b"%PDF-1.7\n...")
    assert detect(path).kind == "pdf"


def test_something_unrecognised_says_so_rather_than_guessing(tmp_path: Path) -> None:
    path = tmp_path / "x.bin"
    path.write_bytes(b"\x01\x02\x03\xfe\xff\x00\x99\x88\x77\x66\x55\x44\x33\x22\x11\x00")
    found = detect(path)
    assert found.kind == "unknown"
    assert not found.is_readable


def test_an_empty_file_is_not_mistaken_for_text(tmp_path: Path) -> None:
    path = tmp_path / "x.bin"
    path.write_bytes(b"")
    assert detect(path).kind == "unknown"


def test_a_file_that_cannot_be_opened_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ExtractionError, match="khong mo duoc"):
        detect(tmp_path / "khong_ton_tai.bin")


# --- how sure the reader was --------------------------------------------------------


def test_a_clean_reading_needs_nobody() -> None:
    assert not summarise([1.0, 1.0, 0.98]).needs_review


def test_enough_doubt_asks_for_a_person() -> None:
    # Criterion S6: a poor extraction must not pass in silence.
    scores = [0.4, 0.5] + [1.0] * 5
    found = summarise(scores)
    assert found.low_share > REVIEW_SHARE
    assert found.needs_review


def test_one_doubtful_word_in_many_does_not_stop_the_run() -> None:
    # A gate raised for every smudge is a gate people learn to click through.
    assert not summarise([0.5] + [1.0] * 20).needs_review


def test_the_average_never_hides_the_worst() -> None:
    # A page read at 95% with three unreadable figures is a page with three
    # wrong numbers in it, and the average says it is fine.
    found = summarise([1.0, 1.0, 1.0, 0.2])
    assert found.mean > 0.7
    assert found.lowest == 0.2
    assert found.low_count == 1


def test_nothing_read_is_not_high_confidence() -> None:
    found = summarise([])
    assert found.total == 0
    assert not found.needs_review
    assert "khong doc duoc" in found.describe()


def test_a_clean_reading_does_not_claim_somebody_must_check_it() -> None:
    assert "can nguoi doi chieu" not in summarise([1.0, 0.99]).describe()


# --- reading a document ---------------------------------------------------------------


def test_a_pdf_with_a_text_layer_is_read_exactly() -> None:
    # The characters were stored, not recognised, so nothing is being guessed.
    spans, declined = read_pdf(a_pdf())
    assert spans
    assert all(span.confidence == 1.0 for span in spans)
    assert any("BAO CAO" in span.text for span in spans)
    assert declined == []


def test_every_line_says_which_page_it_came_from() -> None:
    spans, _ = read_pdf(a_pdf())
    assert all(span.page >= 1 for span in spans)


def test_a_pdf_that_is_a_photograph_says_so() -> None:
    # Returning nothing would read as an empty document rather than an
    # unreadable one, and those need different responses.
    from PIL import Image

    picture = Image.new("RGB", (600, 400), "white")
    buffer = io.BytesIO()
    picture.save(buffer, format="PDF")
    spans, declined = read_pdf(buffer.getvalue())
    assert spans == []
    assert any("ANH CHUP" in note for note in declined)


def test_a_table_is_lifted_whole_rather_than_read_as_lines() -> None:
    # Reading a table as prose loses the columns, and the columns are usually
    # why somebody sent a document rather than a spreadsheet.
    tables, _ = read_pdf_tables(a_pdf())
    assert tables
    frame = rows_to_frame(tables[0])
    assert list(frame.columns) == ["Kenh", "Doanh thu"]
    assert len(frame.index) == 2


def test_a_table_with_only_a_header_has_no_rows_to_take() -> None:
    with pytest.raises(ExtractionError, match="mot dong"):
        rows_to_frame([["a", "b"]])


# --- reading a picture ------------------------------------------------------------------


def test_words_in_a_picture_are_read_with_their_own_confidence() -> None:
    spans, _ = read_image(an_image())
    assert spans
    assert all(0.0 <= span.confidence <= 1.0 for span in spans)
    assert any("4823" in span.text for span in spans)


def test_every_word_says_where_on_the_page_it_sat() -> None:
    # Confirming text without being able to go and look at the original is not
    # confirming anything.
    spans, _ = read_image(an_image())
    assert all(span.bbox is not None for span in spans)


def test_a_region_that_read_as_nothing_is_counted_not_scored() -> None:
    # Not a low confidence - an absent one. Averaging it in would quietly drag
    # the whole page down and hide which parts were actually read.
    _, declined = read_image(an_image(blur=1.1))
    assert any("khong doc ra chu nao" in note for note in declined)


# --- the agents ---------------------------------------------------------------------------


def stage(settings: Settings, name: str, content: bytes) -> DataRef:
    """Put a file where an extractor may read it, without borrowing its scope."""
    path = resolve(f"raw://{name}", settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return DataRef(path=f"raw://{name}", format="csv", content_hash=storage.sha256_file(path))


def report_of(result: TaskResult, settings: Settings) -> ExtractionResult:
    """The extraction report, found by what it is rather than where it sits.

    An extractor hands back the data it read *and* a report about the reading.
    Taking either by position is the mistake these tests are about.
    """
    for ref in result.output_refs:
        if ref.format == "json":
            return ExtractionResult.model_validate_json(
                resolve(ref.path, settings).read_text(encoding="utf-8")
            )
    raise AssertionError("khong tim thay bao cao trich xuat trong output")


def run_extractor(
    tmp_path: Path,
    agent: ExtractorAgent,
    name: str,
    content: bytes,
    params: dict[str, object] | None = None,
) -> tuple[TaskResult, Settings]:
    settings = settings_in(tmp_path)
    scope = token(agent.agent_id, params)
    files = ScopedStorage(scope, settings)
    ref = stage(settings, name, content)
    result = agent.execute(TaskRequest(scope=scope, input_refs=(ref,), instruction=""), files)
    return result, settings


def test_a_document_becomes_text_and_tables(tmp_path: Path) -> None:
    result, settings = run_extractor(
        tmp_path, PdfExtractor(settings_in(tmp_path), MANIFEST_DIR), "bc.pdf", a_pdf()
    )
    assert result.status == "OK", result.error
    found = report_of(result, settings)
    assert found.spans
    assert found.tables
    assert found.mean_confidence == 1.0


def test_every_span_carries_where_it_came_from(tmp_path: Path) -> None:
    result, settings = run_extractor(
        tmp_path, PdfExtractor(settings_in(tmp_path), MANIFEST_DIR), "bc.pdf", a_pdf()
    )
    found = report_of(result, settings)
    for span in found.spans:
        assert span.locator.describe()


def test_a_file_that_reads_as_nothing_fails_rather_than_succeeding(tmp_path: Path) -> None:
    # An absent extraction is not a poor one to be flagged. Calling it OK would
    # hand the next task an empty file with a clean bill of health.
    from PIL import Image

    blank = Image.new("RGB", (400, 200), "white")
    buffer = io.BytesIO()
    blank.save(buffer, format="PNG")
    result, _ = run_extractor(
        tmp_path,
        ImageExtractor(settings_in(tmp_path), MANIFEST_DIR),
        "trang.png",
        buffer.getvalue(),
    )
    assert result.status == "FAILED"
    assert result.error is not None
    assert result.error.code == "NOTHING_READ"


def test_text_without_a_table_is_said_out_loud(tmp_path: Path) -> None:
    # The difference between "here is your data" and "here is prose that
    # mentions numbers".
    result, _ = run_extractor(
        tmp_path, ImageExtractor(settings_in(tmp_path), MANIFEST_DIR), "anh.png", an_image()
    )
    assert result.status == "OK", result.error
    assert any("chua phai du lieu co cau truc" in note for note in result.declined)


def test_no_input_is_a_clean_failure(tmp_path: Path) -> None:
    settings = settings_in(tmp_path)
    scope = token("e1_pdf")
    result = PdfExtractor(settings, MANIFEST_DIR).execute(
        TaskRequest(scope=scope, input_refs=(), instruction=""), ScopedStorage(scope, settings)
    )
    assert result.status == "FAILED"
    assert result.error is not None
    assert result.error.code == "NO_INPUT"


# --- what a person is asked to confirm ------------------------------------------------


def test_only_the_doubtful_spans_are_put_in_front_of_a_person() -> None:
    # Four hundred confident lines is how somebody stops reading any of them,
    # which would defeat the check entirely.
    spans = [
        {"text": "chac chan", "confidence": 0.99, "locator": {"kind": "page", "page": 1}},
        {"text": "kho doc", "confidence": 0.4, "locator": {"kind": "page", "page": 2}},
    ]
    options = span_options(spans)
    assert len(options) == 1
    assert options[0].label == "kho doc"


def test_each_doubtful_span_says_where_to_look() -> None:
    spans = [
        {
            "text": "mo",
            "confidence": LOW_CONFIDENCE - 0.1,
            "locator": {"kind": "region", "page": 3, "bbox": [10.0, 20.0, 30.0, 40.0]},
        }
    ]
    assert "trang 3" in span_options(spans)[0].detail


def test_a_doubtful_moment_in_a_recording_says_when() -> None:
    spans = [
        {
            "text": "nghe khong ro",
            "confidence": 0.3,
            "locator": {"kind": "time", "start_s": 12.5, "end_s": 15.0},
        }
    ]
    assert "12.5s" in span_options(spans)[0].detail


def test_nothing_doubtful_asks_nothing() -> None:
    spans = [{"text": "ro rang", "confidence": 1.0, "locator": {"kind": "page", "page": 1}}]
    assert span_options(spans) == ()


# --- listening to a recording ----------------------------------------------------

WHISPER_CACHE = Path.home() / ".cache" / "huggingface"
HAS_MODEL = WHISPER_CACHE.is_dir()


def test_a_confident_segment_scores_higher_than_a_doubtful_one() -> None:
    # Not a probability and not pretending to be one: a rank, so that the same
    # threshold can be applied to speech and to characters alike.
    assert _from_logprob(-0.1) > _from_logprob(-1.0)
    assert _from_logprob(0.0) == 1.0


def test_the_scale_stays_between_nothing_and_certain() -> None:
    for value in (-99.0, -1.5, -0.5, 0.0, 1.0):
        assert 0.0 <= _from_logprob(value) <= 1.0


def test_a_hopeless_segment_scores_zero_rather_than_going_negative() -> None:
    # A negative confidence would sort below "not read at all", which is a
    # different thing and would corrupt every average it entered.
    assert _from_logprob(-50.0) == 0.0


def a_tone(seconds: float = 1.0) -> bytes:
    """A WAV file with a tone in it and nobody speaking."""
    import math
    import struct
    import wave

    buffer = io.BytesIO()
    rate = 16000
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        frames = b"".join(
            struct.pack("<h", int(12000 * math.sin(2 * math.pi * 440 * index / rate)))
            for index in range(int(rate * seconds))
        )
        handle.writeframes(frames)
    return buffer.getvalue()


@pytest.mark.skipif(not HAS_MODEL, reason="chua tai model nhan dang tieng noi")
def test_a_recording_with_no_speech_says_so_rather_than_inventing_words() -> None:
    # The failure this guards against is the one that matters most: a model asked
    # to transcribe silence will happily produce a plausible sentence.
    spans, declined = read_audio(a_tone(), model_size="tiny")
    assert spans == []
    assert any("khong nghe ra loi noi nao" in note for note in declined)


@pytest.mark.skipif(not HAS_MODEL, reason="chua tai model nhan dang tieng noi")
def test_a_recording_that_cannot_be_decoded_is_an_error() -> None:
    with pytest.raises(ExtractionError, match="khong nhan dang duoc"):
        read_audio(b"khong phai am thanh gi ca", model_size="tiny")


def test_the_data_leads_and_the_report_follows(tmp_path: Path) -> None:
    # Not a guarantee on its own - the consumer also asks for what it needs -
    # but it makes the common case the obvious one, and taking the report as
    # data failed several layers away from the mistake (L62).
    result, _ = run_extractor(
        tmp_path, PdfExtractor(settings_in(tmp_path), MANIFEST_DIR), "bc.pdf", a_pdf()
    )
    assert result.output_refs[0].format == "parquet"
    assert result.output_refs[-1].format == "json"
