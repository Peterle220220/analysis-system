"""A7 tests: the model may interpret, but it may not produce a number."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from analysis_system.agents.a7_analyst import AnalystAgent, build_analysis_request
from analysis_system.contracts.agents import Finding, FindingProposal
from analysis_system.contracts.base import (
    DataRef,
    RetryFeedback,
    ScopeToken,
    TaskRequest,
    TaskResult,
)
from analysis_system.services import storage
from analysis_system.services.findings import (
    FindingError,
    check_finding,
    placeholders,
    render_all,
    render_finding,
)
from analysis_system.services.llm import LlmClient, LlmRequest, LlmResponse
from analysis_system.services.metrics import compute_metrics, metric_catalogue
from analysis_system.settings import LAYER_NAMES, LayerPaths, Settings, load_settings, resolve

NOW = datetime(2026, 8, 31, 19, 0, tzinfo=UTC)
MANIFEST_DIR = Path(__file__).resolve().parents[2] / "config" / "manifests"


def houses() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "city": ["Seattle", "Seattle", "Renton", "Kent"],
            "price": [800000.0, 700000.0, 400000.0, 300000.0],
            "beds": [4.0, 3.0, 3.0, 2.0],
        }
    )


def metrics() -> dict[str, Any]:
    return compute_metrics(houses(), dimensions=("city",))


class FixedFindings:
    """Answers with one prepared proposal."""

    name = "test"

    def __init__(self, proposal: FindingProposal) -> None:
        self._proposal = proposal
        self.calls = 0

    def complete(self, request: LlmRequest) -> LlmResponse:
        self.calls += 1
        self.last = request
        return LlmResponse(data=self._proposal, provider=self.name, model="test")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    roots = {name: tmp_path / name for name in LAYER_NAMES}
    for root in roots.values():
        root.mkdir(parents=True, exist_ok=True)
    return load_settings().model_copy(update={"layers": LayerPaths(**roots)})


def token(params: dict[str, Any] | None = None) -> ScopeToken:
    return ScopeToken(
        run_id="r_an",
        task_id="t_findings",
        agent_id="a7_analyst",
        allow_read=("mart://**", "clean://**", "validation://**", "profile://**"),
        allow_write=("artifacts://**",),
        allow_tools=("pandas",),
        params=params or {"dimensions": ["city"]},
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
    )


def analyse(
    settings: Settings, proposal: FindingProposal | None, params: dict[str, Any] | None = None
) -> TaskResult:
    storage.write_parquet(houses(), resolve("mart://houses.parquet", settings))
    ref = DataRef(path="mart://houses.parquet", format="parquet", content_hash="a" * 64)
    llm = LlmClient(FixedFindings(proposal)) if proposal else None
    agent = AnalystAgent(settings, MANIFEST_DIR, llm=llm)
    request = TaskRequest(scope=token(params), input_refs=(ref,), instruction="gia nha the nao")
    return agent.run(request, now=NOW)


GOOD = Finding(
    claim_template=(
        "Gia trung binh o Seattle la {price.mean.by.city.Seattle}, cao hon muc chung {price.mean}."
    ),
    metric_keys=("price.mean.by.city.Seattle", "price.mean"),
    evidence_ref="mart://houses.parquet",
    confidence=0.9,
    dimension="city",
)


# --- the metrics code computes ------------------------------------------------


def test_the_basic_shape_of_the_table_is_measured() -> None:
    computed = metrics()
    assert computed["rows.total"].value == 4.0
    assert computed["price.mean"].value == 550000.0
    assert computed["price.max"].value == 800000.0


def test_a_measure_is_broken_down_by_a_dimension() -> None:
    computed = metrics()
    assert computed["price.mean.by.city.Seattle"].value == 750000.0
    assert computed["city.Seattle.count"].value == 2.0
    assert computed["city.Seattle.share_pct"].value == 50.0


def test_a_text_column_gets_no_average() -> None:
    assert "city.mean" not in metrics()


def test_the_same_table_always_produces_the_same_keys() -> None:
    assert sorted(compute_metrics(houses())) == sorted(compute_metrics(houses()))


# --- the anti-hallucination mechanism -----------------------------------------


def test_a_claim_with_a_typed_number_is_refused() -> None:
    # The whole mechanism in one test: a digit the model wrote itself.
    lying = Finding(
        claim_template="Gia trung binh o Seattle la 999 trieu.",
        evidence_ref="mart://houses.parquet",
        confidence=0.9,
    )
    problems = check_finding(lying, metrics())
    assert any("con so go truc tiep" in problem for problem in problems)


def test_a_claim_referring_to_a_metric_that_does_not_exist_is_refused() -> None:
    invented = Finding(
        claim_template="Ty le tang truong la {price.growth_pct}.",
        evidence_ref="mart://houses.parquet",
    )
    problems = check_finding(invented, metrics())
    assert any("khong ton tai" in problem for problem in problems)


def test_a_claim_with_no_metric_at_all_is_refused() -> None:
    vague = Finding(claim_template="Gia nha kha cao.", evidence_ref="mart://houses.parquet")
    problems = check_finding(vague, metrics())
    assert any("khong tro toi chi so nao" in problem for problem in problems)


def test_a_claim_without_evidence_is_refused() -> None:
    # Criterion S4: a conclusion nobody can trace is a conclusion nobody can check.
    orphan = Finding(claim_template="Gia trung binh la {price.mean}.", evidence_ref="")
    problems = check_finding(orphan, metrics())
    assert any("evidence_ref" in problem for problem in problems)


def test_declared_keys_must_match_the_placeholders_used() -> None:
    mismatched = Finding(
        claim_template="Gia trung binh la {price.mean}.",
        metric_keys=("price.max",),
        evidence_ref="mart://houses.parquet",
    )
    problems = check_finding(mismatched, metrics())
    assert any("khong khop" in problem for problem in problems)


def test_a_confidence_outside_the_range_is_refused() -> None:
    overconfident = Finding(
        claim_template="Gia trung binh la {price.mean}.",
        evidence_ref="mart://houses.parquet",
        confidence=1.5,
    )
    assert any("confidence" in problem for problem in check_finding(overconfident, metrics()))


def test_a_good_finding_passes_every_check() -> None:
    assert check_finding(GOOD, metrics()) == []


# --- rendering ----------------------------------------------------------------


def test_code_substitutes_the_real_figures() -> None:
    rendered = render_finding(GOOD, metrics())
    assert "750,000" in rendered.claim
    assert "550,000" in rendered.claim
    assert "{" not in rendered.claim
    assert rendered.metrics["price.mean"] == 550000.0


def test_the_same_finding_renders_the_same_way_every_time() -> None:
    assert render_finding(GOOD, metrics()).claim == render_finding(GOOD, metrics()).claim


def test_rendering_a_bad_finding_raises_rather_than_repairs() -> None:
    # Repairing it would mean deciding what it meant to say.
    with pytest.raises(FindingError):
        render_finding(Finding(claim_template="Gia la 999."), metrics())


def test_bad_findings_are_dropped_and_reported_not_silently_lost() -> None:
    good_and_bad = [GOOD, Finding(claim_template="Gia la 999.", evidence_ref="x")]
    rendered, rejected = render_all(good_and_bad, metrics())
    assert len(rendered) == 1
    assert len(rejected) == 1
    assert "finding[1]" in rejected[0]


def test_placeholders_are_found_in_order() -> None:
    assert placeholders("{a} roi {b} roi {a}") == ["a", "b", "a"]


# --- the agent ----------------------------------------------------------------


def test_a_good_proposal_produces_findings(settings: Settings) -> None:
    result = analyse(settings, FindingProposal(findings=[GOOD], summary="mot ket luan"))
    assert result.is_ok, result.error
    assert len(result.payload["findings"]) == 1
    assert "750,000" in result.payload["findings"][0]["claim"]
    assert result.output_refs[0].path.startswith("artifacts://")


def test_every_finding_carries_evidence_back_to_the_data(settings: Settings) -> None:
    result = analyse(settings, FindingProposal(findings=[GOOD]))
    assert result.evidence
    assert result.evidence[0].source == "mart://houses.parquet"


def test_a_proposal_of_only_invented_numbers_produces_nothing(settings: Settings) -> None:
    lying = Finding(claim_template="Gia tang 45 phan tram.", evidence_ref="mart://houses.parquet")
    result = analyse(settings, FindingProposal(findings=[lying]))
    assert result.status == "FAILED"
    assert result.error is not None
    assert result.error.code == "NO_VALID_FINDING"
    assert not list(settings.layers.artifacts.iterdir())


def test_the_model_is_shown_metrics_and_never_rows() -> None:
    # A max metric necessarily equals some row value, so looking for a number
    # proves nothing. What matters is the shape: named aggregates, no records.
    request = build_analysis_request(metric_catalogue(metrics()), "gia the nao", 10)
    payload = json.loads(request.prompt)
    assert set(payload) == {"question", "metrics", "max_findings", "rules"}
    assert "sample_rows" not in request.prompt
    assert all(set(entry) == {"key", "value", "unit", "source"} for entry in payload["metrics"])
    assert any(entry["key"] == "price.mean" for entry in payload["metrics"])


def test_without_a_model_it_says_so_rather_than_inventing(settings: Settings) -> None:
    result = analyse(settings, None)
    assert result.status == "FAILED"
    assert result.error.code == "NO_MODEL"  # type: ignore[union-attr]


def test_it_cannot_write_into_the_mart(settings: Settings) -> None:
    storage.write_parquet(houses(), resolve("mart://houses.parquet", settings))
    ref = DataRef(path="mart://houses.parquet", format="parquet", content_hash="a" * 64)
    agent = AnalystAgent(
        settings, MANIFEST_DIR, llm=LlmClient(FixedFindings(FindingProposal(findings=[GOOD])))
    )
    wider = token().model_copy(update={"allow_write": ("mart://**",)})
    result = agent.run(TaskRequest(scope=wider, input_refs=(ref,), instruction="x"), now=NOW)
    assert result.status == "BOUNDARY_VIOLATION"


def test_the_manifest_records_the_ban_and_the_gate(settings: Settings) -> None:
    agent = AnalystAgent(settings, MANIFEST_DIR)
    assert "state_number_not_in_metrics" in agent.manifest.deny
    assert agent.manifest.allow.llm.max_sample_rows == 0
    assert agent.manifest.human_gate.required is True  # HUMAN GATE 2


# --- a conclusion nobody can trace back is not evidence-backed -----------------


def test_a_finding_citing_a_file_that_does_not_exist_is_dropped(settings: Settings) -> None:
    # Its numbers are real - the placeholder machinery guarantees that - but
    # criterion S4 asks for a conclusion that can be traced, and this one
    # traces nowhere.
    proposal = FindingProposal(
        findings=[
            Finding(
                claim_template="Gia trung binh la {price.mean}.",
                metric_keys=("price.mean",),
                evidence_ref="mart://khong_he_ton_tai.parquet",
                confidence=0.9,
            ),
            GOOD,
        ]
    )
    result = analyse(settings, proposal)
    assert result.is_ok, result.error
    assert len(result.payload["findings"]) == 1
    assert result.payload["findings"][0]["evidence_ref"] == "mart://houses.parquet"
    assert any("khong tro toi file nao" in reason for reason in result.payload["rejected"])


def test_a_run_where_nothing_can_be_traced_fails(settings: Settings) -> None:
    proposal = FindingProposal(
        findings=[
            Finding(
                claim_template="Gia trung binh la {price.mean}.",
                metric_keys=("price.mean",),
                evidence_ref="mart://bia_ra.parquet",
                confidence=0.9,
            )
        ]
    )
    result = analyse(settings, proposal)
    assert result.status == "FAILED"
    assert result.error is not None
    assert result.error.code == "NO_VALID_FINDING"


# --- a second attempt is told what was wrong with the first --------------------


def test_findings_rejected_by_the_check_are_worth_another_attempt(
    settings: Settings,
) -> None:
    # The model can write this again without a typed digit once told that is
    # what was wrong. A different plan cannot help it.
    proposal = FindingProposal(
        findings=[
            Finding(
                claim_template="Gia trung binh khoang 550 nghin.",
                metric_keys=("price.mean",),
                evidence_ref="mart://houses.parquet",
                confidence=0.9,
            )
        ]
    )
    result = analyse(settings, proposal)
    assert result.status == "FAILED"
    assert result.error is not None
    assert result.error.retryable
    assert not result.error.replannable
    # The rejected draft travels with it, so the next attempt can be shown it.
    assert result.payload["findings"]


def test_being_handed_no_input_is_the_one_thing_a_new_plan_could_fix(
    settings: Settings,
) -> None:
    agent = AnalystAgent(settings, MANIFEST_DIR)
    result = agent.run(TaskRequest(scope=token(), instruction="x"), now=NOW)
    assert result.error is not None
    assert result.error.code == "NO_INPUT"
    assert result.error.replannable


def test_the_retry_question_carries_the_previous_answer_and_the_reasons() -> None:
    feedback = RetryFeedback(
        attempt=1,
        max_attempts=3,
        previous_answer={"findings": [{"claim_template": "Tang 45 phan tram."}]},
        rejected_because=("finding[0]: cau chua chu so go truc tiep",),
    )
    request = build_analysis_request([], "gia nha the nao", 10, feedback)
    assert "chu so go truc tiep" in request.prompt
    assert "Tang 45 phan tram" in request.prompt
    assert '"attempt": "2/3"' in request.prompt


def test_a_first_attempt_asks_the_plain_question() -> None:
    # No feedback fields, so the fingerprint is unchanged in the ordinary case.
    plain = build_analysis_request([], "gia nha the nao", 10)
    assert "rejected_because" not in plain.prompt
    assert "previous_answer" not in plain.prompt
