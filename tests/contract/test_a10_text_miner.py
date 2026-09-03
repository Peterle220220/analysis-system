"""A10 đọc văn xuôi, và lập bảng CHỈ KHI được yêu cầu.

Two properties carry most of the weight here, and both are about not claiming
more than was measured: a table is built only when somebody names the terms for
it, and every row of that table points at a place where its figures can actually
be found.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from analysis_system.agents.a10_text_miner import (
    TextMinerAgent,
    mentions_table,
    metric_name,
    to_metrics,
)
from analysis_system.contracts.agents import (
    ExtractedSpan,
    ExtractionResult,
    SourceLocator,
    TermReport,
)
from analysis_system.contracts.base import DataRef, ScopeToken, TaskRequest, TaskResult
from analysis_system.services.salience import read
from analysis_system.services.scoped_storage import ScopedStorage
from analysis_system.settings import Settings, load_settings

MANIFEST_DIR = Path("config/manifests")
NOW = datetime.now(UTC)

PAGES = {
    1: [
        "Doanh thu quy III dat 4880 ty dong, tang 12,5% so voi cung ky.",
        "Kenh buu dien dong gop 620 ty dong trong tong so do.",
    ],
    2: [
        "Ty le hoan cua kenh buu dien la 9,4%, cao nhat trong sau kenh.",
        "Thoi gian giao trung binh qua kenh buu dien la 6,5 ngay.",
    ],
    3: [
        "Nhom du lieu thu nghiem machine learning de du bao ton kho.",
        "Do chinh xac cua machine learning dat 87% tren tap kiem tra.",
    ],
}


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """A workspace of its own, so nothing here touches real data."""
    base = load_settings()
    layers = base.layers.model_copy(
        update={
            name: str(tmp_path / name)
            for name in base.layers.model_dump()
            if isinstance(getattr(base.layers, name), str)
        }
    )
    return base.model_copy(update={"layers": layers})


def token(params: dict[str, object] | None = None) -> ScopeToken:
    """A token matching the shipped a10_text_miner manifest."""
    return ScopeToken(
        run_id="r_text",
        task_id="t_dem",
        agent_id="a10_text_miner",
        allow_read=("extracted://**",),
        allow_write=("artifacts://**", "extracted://**"),
        allow_tools=(),
        params=params or {},
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
    )


def stage(settings: Settings, scope: ScopeToken) -> DataRef:
    """Write an extraction result for A10 to read, one span per page."""
    files = ScopedStorage(scope.model_copy(update={"allow_write": ("extracted://**",)}), settings)
    result = ExtractionResult(
        source="raw://bao_cao.pdf",
        kind="pdf",
        spans=tuple(
            ExtractedSpan(
                text="\n".join(lines),
                locator=SourceLocator(kind="page", page=page),
                confidence=1.0,
            )
            for page, lines in PAGES.items()
        ),
        mean_confidence=1.0,
    )
    return files.save_text(result.model_dump_json(), "extracted://r_text_pdf.json")


def run(
    settings: Settings, params: dict[str, object] | None = None
) -> tuple[TaskResult, ScopedStorage]:
    scope = token(params)
    ref = stage(settings, scope)
    files = ScopedStorage(scope, settings)
    return (
        TextMinerAgent(settings, MANIFEST_DIR).execute(
            TaskRequest(scope=scope, input_refs=(ref,), instruction="doc"), files
        ),
        files,
    )


# --- it reads, and it reports both ends -------------------------------------------


def test_it_reads_prose_and_reports_what_it_is_about(settings: Settings) -> None:
    result, _ = run(settings)
    assert result.status == "OK", result.error
    report = TermReport.model_validate(result.payload)
    assert report.total_words > 0
    assert {row.band for row in report.terms} & {"nen", "vua", "hiem"}


def test_a_term_mentioned_twice_survives_the_cut(settings: Settings) -> None:
    """The case the whole thing was built for.

    Sorting by count and cutting the tail buries exactly the term worth
    noticing, which is why the cut gives each band its own share.
    """
    result, _ = run(settings)
    report = TermReport.model_validate(result.payload)
    assert any(row.term == "machine learning" for row in report.terms)


def test_each_band_travels_with_what_it_means(settings: Settings) -> None:
    """ "Appears twice" means nothing on its own, so it never travels on its own."""
    result, _ = run(settings)
    report = TermReport.model_validate(result.payload)
    assert all(row.meaning for row in report.terms)


def test_it_emits_metrics_in_the_shape_every_skill_uses(settings: Settings) -> None:
    """So a claim about a term goes through the same checks as one about a column."""
    result, _ = run(settings)
    report = TermReport.model_validate(result.payload)
    keys = {metric.key for metric in report.metrics}
    assert "text.words.total" in keys
    assert any(key.startswith("term.") and key.endswith(".count") for key in keys)


def test_a_metric_key_never_carries_a_space(settings: Settings) -> None:
    """A key with a space in it produces a claim nobody can substitute into."""
    assert metric_name("machine learning") == "machine_learning"
    result, _ = run(settings)
    report = TermReport.model_validate(result.payload)
    assert all(" " not in metric.key for metric in report.metrics)


# --- and it builds a table only when told to --------------------------------------


def test_no_table_is_built_unasked(settings: Settings) -> None:
    """The boss was explicit, and the reasoning holds without him.

    Which term deserves a table is a judgement about what somebody wants to find
    out. Guessing would build one around the most frequent term - which is, by
    this agent's own reckoning, the term that distinguishes nothing.
    """
    result, _ = run(settings)
    assert result.metrics["table_rows"] == 0.0
    assert [ref.path for ref in result.output_refs] == ["artifacts://r_text_terms.json"]


def test_naming_terms_builds_the_table(settings: Settings) -> None:
    result, files = run(settings, {"terms": ["machine learning", "buu dien"]})
    assert result.status == "OK", result.error
    assert result.metrics["table_rows"] > 0
    tables = [ref for ref in result.output_refs if ref.path.endswith(".parquet")]
    assert len(tables) == 1
    frame = files.load_parquet(tables[0].path)
    assert set(frame["tu"]) == {"machine learning", "buu dien"}


def test_every_row_points_where_its_figures_can_be_found(settings: Settings) -> None:
    """A row naming a page and listing another page's figures is a false trail.

    Tokens run on across the whole document, so a window reaching back from the
    top of page three lands on page two - and a reader following that row finds
    nothing there.
    """
    result, files = run(settings, {"terms": ["machine learning"]})
    tables = [ref for ref in result.output_refs if ref.path.endswith(".parquet")]
    frame = files.load_parquet(tables[0].path)
    row = frame[frame["doc_o"] == "page 3"].iloc[0]
    assert "87%" in row["so_o_gan"], "so cua chinh trang do phai co"
    assert "6,5" not in row["so_o_gan"], "so cua trang 2 khong duoc lot sang"


def test_asking_for_a_term_that_is_not_there_says_so(settings: Settings) -> None:
    """Silence would read exactly like a term that appears nowhere near a figure."""
    result, _ = run(settings, {"terms": ["khong he co tu nay"]})
    assert result.status == "OK", result.error
    assert result.metrics["table_rows"] == 0.0
    assert any("khong lap duoc bang" in note for note in result.declined)


def test_a_report_with_no_terms_yields_no_rows() -> None:
    found = read(
        "\n".join(line for lines in PAGES.values() for line in lines),
        locators=[f"page {page}" for page, lines in PAGES.items() for _ in lines],
    )
    report = TermReport(source="x", terms=(), metrics=to_metrics(found))
    assert mentions_table(report, {"buu dien"}).empty, "khong co term thi khong co dong"


# --- and it refuses honestly ------------------------------------------------------


def test_no_extraction_among_the_inputs_is_refused(settings: Settings) -> None:
    scope = token()
    files = ScopedStorage(scope, settings)
    result = TextMinerAgent(settings, MANIFEST_DIR).execute(
        TaskRequest(scope=scope, input_refs=(), instruction="doc"), files
    )
    assert result.status == "FAILED"
    assert result.error is not None
    assert result.error.code == "NO_TEXT"
