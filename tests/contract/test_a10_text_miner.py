"""A10 đọc văn xuôi, và lập bảng CHỈ KHI được yêu cầu.

Two properties carry most of the weight here, and both are about not claiming
more than was measured: a table is built only when somebody names the terms for
it, and every row of that table points at a place where its figures can actually
be found.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from analysis_system.agents.a10_text_miner import (
    TextMinerAgent,
    mentions_table,
    metric_name,
    to_metrics,
)
from analysis_system.core import storage
from analysis_system.core.scoped_storage import ScopedStorage
from analysis_system.core.settings import (
    LAYER_NAMES,
    LayerPaths,
    Settings,
    load_settings,
    resolve,
)
from analysis_system.models.agents import (
    ExtractedSpan,
    ExtractionResult,
    SourceLocator,
    TermReport,
)
from analysis_system.models.base import DataRef, ScopeToken, TaskRequest, TaskResult
from analysis_system.services.salience import lift, read

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
    """A workspace of its own, and this time it really is one.

    The line above used to be a claim the code did not keep. It filtered the
    layer fields with `isinstance(..., str)`, and they are `Path` - so the
    condition was never true, the update dict was always empty, and
    `model_copy` handed back the real settings unchanged. These tests ran
    against the user's own data layers and wrote files into them.

    It surfaced only after a clean-up: raw/ was emptied, one `make check` put
    a.docx, b.eml, c.html, ten_sai.txt and thu.msg straight back.
    """
    roots = {name: tmp_path / name for name in LAYER_NAMES}
    for root in roots.values():
        root.mkdir(parents=True, exist_ok=True)
    return load_settings().model_copy(update={"layers": LayerPaths(**roots)})


def token(params: dict[str, object] | None = None) -> ScopeToken:
    """A token matching the shipped a10_text_miner manifest."""
    return ScopeToken(
        run_id="r_text",
        task_id="t_dem",
        agent_id="a10_text_miner",
        allow_read=("extracted://**", "clean://**", "mart://**"),
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
    assert [ref.path for ref in result.output_refs] == ["artifacts://r_text_t_dem_terms.json"]


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


# --- van ban nam trong mot cot cua bang ----------------------------------------


def labelled_frame() -> pd.DataFrame:
    """Cau da gan nhan, dung hinh dang cua emotions.txt."""
    return pd.DataFrame(
        {
            "cot_1": [
                "i feel so hopeless and empty inside",
                "i am furious about the delay",
                "what a wonderful sunny morning",
                "i feel empty and hopeless again",
                "this delay makes me furious",
                "a wonderful and joyful day",
            ],
            "cot_2": ["sadness", "anger", "joy", "sadness", "anger", "joy"],
        }
    )


def mine_column(settings: Settings, params: dict[str, object]) -> TaskResult:
    """Chay A10 tren mot bang thay vi tren mot tai lieu da trich."""
    storage.write_parquet(labelled_frame(), resolve("clean://nhan.parquet", settings))
    ref = DataRef(path="clean://nhan.parquet", format="parquet", content_hash="e" * 64)
    agent = TextMinerAgent(settings, MANIFEST_DIR)
    request = TaskRequest(
        scope=token(params),
        input_refs=(ref,),
        instruction="tu nao hay xuat hien",
    )
    return agent.run(request, now=NOW)


def test_text_in_a_column_can_be_counted(settings: Settings) -> None:
    # The ordinary case for this kind of work, and the one shape the agent
    # could not see: a CSV of sentences with the prose in one column.
    result = mine_column(settings, {"text_column": "cot_1"})
    assert result.status == "OK"
    terms = {row["term"] for row in result.payload["terms"]}
    assert "hopeless" in terms
    assert "furious" in terms
    assert result.payload["source"].endswith("#cot_1")


def test_rows_can_be_narrowed_before_counting(settings: Settings) -> None:
    # "What do the sadness sentences say" without building a table to ask it of.
    result = mine_column(settings, {"text_column": "cot_1", "where": {"cot_2": "sadness"}})
    assert result.status == "OK"
    terms = {row["term"] for row in result.payload["terms"]}
    assert "hopeless" in terms
    # furious belongs to the anger rows, which this filter excluded.
    assert "furious" not in terms


def test_a_column_that_is_not_there_is_refused_with_the_ones_that_are(
    settings: Settings,
) -> None:
    result = mine_column(settings, {"text_column": "khong_co"})
    assert result.status == "FAILED"
    assert result.error is not None
    assert "cot_1" in result.error.message


def test_a_filter_that_matches_nothing_is_refused_rather_than_counted_empty(
    settings: Settings,
) -> None:
    result = mine_column(settings, {"text_column": "cot_1", "where": {"cot_2": "khong_ton_tai"}})
    assert result.status == "FAILED"
    assert result.error is not None
    assert result.error.code == "NOTHING_TO_COUNT"


def test_a_filter_may_name_several_values(settings: Settings) -> None:
    # Asked about two groups at once the Manager sends a list, which is the
    # natural way to say it. A straight equality compared every row against the
    # printed form of the list and matched nothing.
    result = mine_column(
        settings, {"text_column": "cot_1", "where": {"cot_2": ["sadness", "anger"]}}
    )
    assert result.status == "OK"
    terms = {row["term"] for row in result.payload["terms"]}
    assert "hopeless" in terms
    assert "furious" in terms
    assert "wonderful" not in terms


def test_a_filtered_group_is_measured_against_the_rest(settings: Settings) -> None:
    # Counting inside one group answers "what does it talk about". Both the
    # sadness rows and the fear rows of a real dataset came back with the same
    # three words on top - "feel", "feel like", "im feeling" - because that is
    # what every row is made of. Characteristic is a comparison, not a count.
    result = mine_column(settings, {"text_column": "cot_1", "where": {"cot_2": "anger"}})
    assert result.status == "OK"
    lifts = {m["key"]: m["value"] for m in result.payload["metrics"] if m["key"].endswith(".lift")}
    assert lifts, "phai co so do dac trung khi da loc"
    # "furious" belongs to the anger rows and nowhere else, so it stands out;
    # "feel" is spread across every group and does not.
    assert lifts["term.furious.lift"] > lifts.get("term.feel.lift", 0.0)


def test_no_comparison_is_offered_when_nothing_was_filtered_out(settings: Settings) -> None:
    # Reading the whole column leaves nothing to be characteristic against, and
    # a ratio of every term against itself would be a column of ones.
    result = mine_column(settings, {"text_column": "cot_1"})
    assert not [m for m in result.payload["metrics"] if m["key"].endswith(".lift")]


def test_lift_says_how_many_times_more_concentrated() -> None:
    # A ratio of 1 means the group uses a term exactly as much as everyone else.
    inside = read("furious furious delay")
    outside = read("wonderful morning delay")
    scores = lift(inside, outside)
    assert scores["furious"] > scores["delay"]
