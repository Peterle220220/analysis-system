"""A8 tests: the document is assembled by code; the model only writes prose."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from analysis_system.agents.a8_reporter import (
    ReporterAgent,
    render_html,
    render_markdown,
    render_narrative,
)
from analysis_system.contracts.agents import (
    AnalysisResult,
    MetricValue,
    NarrativeProposal,
    RenderedFinding,
)
from analysis_system.contracts.base import DataRef, ScopeToken, TaskRequest, TaskResult
from analysis_system.services import storage
from analysis_system.services.charts import ChartError, bar_chart, chart_from_metrics
from analysis_system.services.llm import LlmClient, LlmRequest, LlmResponse
from analysis_system.settings import LAYER_NAMES, LayerPaths, Settings, load_settings, resolve

NOW = datetime(2026, 8, 31, 20, 0, tzinfo=UTC)
MANIFEST_DIR = Path(__file__).resolve().parents[2] / "config" / "manifests"

METRICS = {
    "price.mean": MetricValue(key="price.mean", value=550000.0, source="mart://houses.parquet"),
    "city.Seattle.share_pct": MetricValue(
        key="city.Seattle.share_pct", value=50.0, unit="%", source="mart://houses.parquet"
    ),
    "city.Renton.share_pct": MetricValue(
        key="city.Renton.share_pct", value=25.0, unit="%", source="mart://houses.parquet"
    ),
}

FINDING = RenderedFinding(
    claim="Gia trung binh la 550,000.",
    template="Gia trung binh la {price.mean}.",
    metrics={"price.mean": 550000.0, "city.Seattle.share_pct": 50.0, "city.Renton.share_pct": 25.0},
    evidence_ref="mart://houses.parquet",
    confidence=0.9,
)

ANALYSIS = AnalysisResult(
    source="mart://houses.parquet",
    question="Gia nha the nao",
    findings=(FINDING,),
    metrics_available=3,
)


class FixedSummary:
    """Answers with one prepared narrative."""

    name = "test"

    def __init__(self, proposal: NarrativeProposal) -> None:
        self._proposal = proposal

    def complete(self, _request: LlmRequest) -> LlmResponse:
        return LlmResponse(data=self._proposal, provider=self.name, model="test")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    roots = {name: tmp_path / name for name in LAYER_NAMES}
    for root in roots.values():
        root.mkdir(parents=True, exist_ok=True)
    return load_settings().model_copy(update={"layers": LayerPaths(**roots)})


def token(params: dict[str, Any] | None = None) -> ScopeToken:
    return ScopeToken(
        run_id="r_rep",
        task_id="t_report",
        agent_id="a8_reporter",
        allow_read=("mart://**", "artifacts://**", "validation://**"),
        allow_write=("artifacts://**",),
        allow_tools=("pandas", "matplotlib"),
        params=params or {},
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
    )


def report(
    settings: Settings,
    proposal: NarrativeProposal | None = None,
    *,
    analysis: AnalysisResult = ANALYSIS,
    params: dict[str, Any] | None = None,
) -> TaskResult:
    storage.write_text(
        analysis.model_dump_json(indent=2), resolve("artifacts://findings.json", settings)
    )
    ref = DataRef(path="artifacts://findings.json", format="json", content_hash="a" * 64)
    llm = LlmClient(FixedSummary(proposal)) if proposal else None
    agent = ReporterAgent(settings, MANIFEST_DIR, llm=llm)
    return agent.run(
        TaskRequest(scope=token(params), input_refs=(ref,), instruction="viet bao cao"), now=NOW
    )


# --- charts -------------------------------------------------------------------


def test_a_bar_chart_is_produced_as_png() -> None:
    png = bar_chart(["a", "b"], [1.0, 2.0], title="thu")
    assert png.startswith(b"\x89PNG")


def test_the_same_numbers_draw_the_same_bytes() -> None:
    # matplotlib stamps a creation date by default, which would break S1.
    first = bar_chart(["a", "b"], [1.0, 2.0], title="thu")
    second = bar_chart(["a", "b"], [1.0, 2.0], title="thu")
    assert first == second


def test_different_numbers_draw_different_bytes() -> None:
    assert bar_chart(["a"], [1.0], title="x") != bar_chart(["a"], [2.0], title="x")


def test_drawing_nothing_is_an_error_not_an_empty_picture() -> None:
    with pytest.raises(ChartError, match="Khong co gia tri"):
        bar_chart([], [], title="x")


def test_mismatched_labels_and_values_are_refused() -> None:
    with pytest.raises(ChartError, match="khac so gia tri"):
        bar_chart(["a", "b"], [1.0], title="x")


def test_a_chart_is_built_from_the_metric_keys() -> None:
    values = {key: metric.value for key, metric in METRICS.items()}
    png = chart_from_metrics(values, title="ty trong", suffix=".share_pct")
    assert png.startswith(b"\x89PNG")


def test_a_suffix_matching_nothing_is_an_error() -> None:
    with pytest.raises(ChartError, match="khong co chi so nao|Khong co chi so nao"):
        chart_from_metrics({"a.mean": 1.0}, title="x", suffix=".share_pct")


# --- the narrative ------------------------------------------------------------


def test_code_substitutes_the_figures_into_the_summary() -> None:
    text, problems = render_narrative("Gia trung binh la {price.mean}.", METRICS)
    assert problems == []
    assert "550,000" in text
    assert "{" not in text


def test_a_summary_with_a_typed_number_is_rejected() -> None:
    _, problems = render_narrative("Gia trung binh khoang 550 nghin do.", METRICS)
    assert any("go truc tiep" in problem for problem in problems)


def test_a_summary_referring_to_an_unknown_metric_is_rejected() -> None:
    _, problems = render_narrative("Tang truong {price.growth}.", METRICS)
    assert any("khong ton tai" in problem for problem in problems)


# --- assembling the document --------------------------------------------------


def test_the_report_carries_findings_metrics_and_sources() -> None:
    text = render_markdown(
        title="Bao cao",
        summary="Tom tat.",
        findings=(FINDING,),
        metrics=METRICS,
        charts=("r_rep_share.png",),
        sources=("mart://houses.parquet",),
    )
    assert "# Bao cao" in text
    assert FINDING.claim in text
    assert "`price.mean`" in text
    assert "![r_rep_share.png]" in text
    assert "mart://houses.parquet" in text


def test_a_report_with_no_findings_says_so_rather_than_looking_empty() -> None:
    text = render_markdown("Bao cao", "", (), METRICS, (), ("mart://x.parquet",))
    assert "Không có kết luận nào vượt qua kiểm tra." in text


def test_the_html_needs_no_network_to_render() -> None:
    html = render_html("# Bao cao", "Bao cao")
    assert "<!doctype html>" in html
    assert "http" not in html  # no external stylesheet, font or script


def test_html_escapes_its_content() -> None:
    assert "&lt;script&gt;" in render_html("<script>", "x")


# --- the agent ----------------------------------------------------------------


def test_a_full_report_is_written(settings: Settings) -> None:
    result = report(settings, NarrativeProposal(summary_template="Gia trung binh {price.mean}."))
    assert result.is_ok, result.error
    assert result.payload["markdown"].endswith(".md")
    assert result.payload["html"].endswith(".html")
    assert (settings.layers.artifacts / "report" / "r_rep.md").is_file()
    assert (settings.layers.artifacts / "report" / "r_rep.html").is_file()


def test_the_chart_is_written_beside_the_report(settings: Settings) -> None:
    result = report(settings, NarrativeProposal(summary_template="Gia {price.mean}."))
    assert result.payload["charts"]
    assert (settings.layers.artifacts / "report" / "r_rep_share.png").is_file()


def test_a_summary_that_invents_a_number_stops_the_report(settings: Settings) -> None:
    result = report(settings, NarrativeProposal(summary_template="Tang 45 phan tram."))
    assert result.status == "FAILED"
    assert result.error is not None
    assert result.error.code == "SUMMARY_REJECTED"
    assert not (settings.layers.artifacts / "report").exists()


def test_a_report_can_be_produced_without_a_model(settings: Settings) -> None:
    # No summary, but the findings and figures still make a document.
    result = report(settings, None)
    assert result.is_ok, result.error
    assert result.payload["findings"] == 1


def test_the_report_quotes_only_metrics_a_finding_stood_behind(settings: Settings) -> None:
    assert report(settings, None).is_ok
    text = (settings.layers.artifacts / "report" / "r_rep.md").read_text(encoding="utf-8")
    assert "price.mean" in text
    assert "price.growth" not in text


def test_malformed_input_is_reported(settings: Settings) -> None:
    storage.write_text("khong phai json", resolve("artifacts://findings.json", settings))
    ref = DataRef(path="artifacts://findings.json", format="json", content_hash="b" * 64)
    agent = ReporterAgent(settings, MANIFEST_DIR)
    result = agent.run(TaskRequest(scope=token(), input_refs=(ref,), instruction="x"), now=NOW)
    assert result.status == "FAILED"
    assert result.error.code == "BAD_INPUT"  # type: ignore[union-attr]


def test_it_cannot_write_into_the_mart(settings: Settings) -> None:
    storage.write_text(ANALYSIS.model_dump_json(), resolve("artifacts://findings.json", settings))
    ref = DataRef(path="artifacts://findings.json", format="json", content_hash="a" * 64)
    wider = token().model_copy(update={"allow_write": ("mart://**",)})
    agent = ReporterAgent(settings, MANIFEST_DIR)
    result = agent.run(TaskRequest(scope=wider, input_refs=(ref,), instruction="x"), now=NOW)
    assert result.status == "BOUNDARY_VIOLATION"


def test_the_manifest_records_the_ban_on_retyping_numbers(settings: Settings) -> None:
    agent = ReporterAgent(settings, MANIFEST_DIR)
    assert "retype_numbers" in agent.manifest.deny
    assert agent.manifest.allow.llm.max_sample_rows == 0
