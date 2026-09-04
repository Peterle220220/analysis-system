"""A7 tests: the model may interpret, but it may not produce a number."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from analysis_system.agents.a7_analyst import (
    AnalystAgent,
    build_analysis_request,
    groupable_columns,
)
from analysis_system.contracts.agents import (
    Finding,
    FindingProposal,
    MetricValue,
    ProcessHandover,
    ProcessMap,
    ProcessVariant,
)
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
    doubled_unit,
    extreme_misuse,
    group_families,
    label_of,
    label_vocabulary,
    name_placeholders,
    placeholders,
    rankings,
    render_all,
    render_finding,
    untested_claim,
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
        allow_read=(
            "mart://**",
            "clean://**",
            "validation://**",
            "profile://**",
            "artifacts://**",
        ),
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
    # Exhaustive on purpose: this set is what guarantees no raw row reaches the
    # model. A new key has to be added here deliberately, having been looked at.
    assert set(payload) == {
        "question",
        "source_table",
        "metrics",
        "process_paths",
        # Looked at, as this test demands. It carries group NAMES taken from the
        # metric keys - never a row, never a value. The figures stay behind
        # their keys where the digit rule can still reach them.
        "xep_hang_nhom",
        "max_findings",
        "rules",
    }
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


def test_a_made_up_citation_is_replaced_by_the_real_one(settings: Settings) -> None:
    """The model does not get to decide what a claim cites.

    There is exactly one legal value - the table the metrics were computed from
    - and the code handed it to the model in the first place, so asking for it
    back could only introduce error. It did: the models copy the example URI
    out of the prompt and cite `mart://r1_case_total`, a table that exists in an
    illustration and nowhere else, then burn three retries on it.

    Overriding is the stricter choice, not the looser one. A citation dropped
    for pointing nowhere was the visible failure; the dangerous one is a
    plausible URI pointing at a real table that has nothing to do with the
    claim, which the old check would have passed.
    """
    proposal = FindingProposal(
        findings=[
            Finding(
                claim_template="Gia trung binh la {price.mean}.",
                metric_keys=("price.mean",),
                evidence_ref="mart://khong_he_ton_tai.parquet",
                confidence=0.9,
            )
        ]
    )
    result = analyse(settings, proposal)
    assert result.is_ok, result.error
    assert len(result.payload["findings"]) == 1
    assert result.payload["findings"][0]["evidence_ref"] == "mart://houses.parquet"


def test_a_blank_citation_is_filled_in_too(settings: Settings) -> None:
    """Silence and invention get the same treatment, because both are guesses."""
    proposal = FindingProposal(
        findings=[
            Finding(
                claim_template="Gia trung binh la {price.mean}.",
                metric_keys=("price.mean",),
                evidence_ref="",
                confidence=0.9,
            )
        ]
    )
    result = analyse(settings, proposal)
    assert result.is_ok, result.error
    assert result.payload["findings"][0]["evidence_ref"] == "mart://houses.parquet"


def test_a_claim_with_no_usable_metric_still_fails(settings: Settings) -> None:
    """Tracing is now structural, so the remaining way to fail is the numbers.

    A citation can no longer be wrong - the code writes it. What can still be
    wrong is a claim resting on a metric nobody measured, and that must still
    take the whole run down rather than be reported as a finding.
    """
    proposal = FindingProposal(
        findings=[
            Finding(
                claim_template="Gia trung binh la {khong.he.do.duoc}.",
                metric_keys=("khong.he.do.duoc",),
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


def test_the_model_is_told_which_table_the_numbers_came_from() -> None:
    # Demanding a citation while withholding what to cite leaves the model
    # guessing - and on real data it guessed mart://frame.parquet, twice.
    request = build_analysis_request([], "gia nha the nao", 10, source="mart://houses.parquet")
    assert '"source_table": "mart://houses.parquet"' in request.prompt
    assert "BANG DUNG gia tri cua 'source_table'" in request.prompt


def test_the_model_is_told_not_to_write_units_itself() -> None:
    # Observed on real output: "40.24 %%" and "2,012 dong dong" - the model
    # wrote the unit and the renderer appended it again.
    request = build_analysis_request([], "gia nha the nao", 10)
    assert "KHONG viet don vi sau placeholder" in request.prompt


# --- a digit inside the data's own label is not an invented number -------------


def bucket_metrics() -> dict[str, MetricValue]:
    """Metrics whose categories carry digits, as any bucketed measure does."""
    return {
        key: MetricValue(key=key, value=value, source="mart://x.parquet")
        for key, value in {
            "exam_score.mean": 78.5,
            "exam_score.mean.by.study_bucket.0-2h": 65.0,
            "exam_score.mean.by.study_bucket.6h_": 88.0,
            "study_bucket.0-2h.count": 120.0,
        }.items()
    }


def test_naming_a_group_whose_label_has_digits_is_allowed() -> None:
    # Categories 0-2h and 6h+ cannot be named without writing a digit. Banning
    # them did not stop invention; it stopped the model discussing the dimension
    # at all, and the analysis quietly avoided the question it was asked.
    finding = Finding(
        claim_template="Nhom 0-2h dat {exam_score.mean.by.study_bucket.0-2h} diem.",
        metric_keys=("exam_score.mean.by.study_bucket.0-2h",),
        evidence_ref="mart://x.parquet",
        confidence=0.9,
    )
    assert check_finding(finding, bucket_metrics()) == []


def test_a_number_the_model_made_up_is_still_refused() -> None:
    # The relaxation must not become a hole: 42 is in no label.
    finding = Finding(
        claim_template="Nhom 0-2h dat 42 diem.",
        metric_keys=(),
        evidence_ref="mart://x.parquet",
        confidence=0.9,
    )
    problems = check_finding(finding, bucket_metrics())
    assert any("go truc tiep" in problem for problem in problems)


def test_the_vocabulary_is_taken_from_the_metric_keys() -> None:
    words = label_vocabulary(bucket_metrics())
    assert "0-2h" in words
    assert "study_bucket" in words
    assert "exam_score" in words


def test_a_conclusion_records_which_content_it_was_computed_from(
    settings: Settings,
) -> None:
    # A path alone traces to a name. The s1 report cited mart://study.parquet,
    # a later run replaced that file, and every check still passed while the
    # citation had quietly stopped being true.
    result = analyse(settings, FindingProposal(findings=[GOOD]))
    assert result.is_ok, result.error
    assert result.payload["findings"][0]["evidence_hash"] == "a" * 64
    assert result.evidence[0].content_hash == "a" * 64


# --- association is not causation ----------------------------------------------


def correlation_metrics() -> dict[str, MetricValue]:
    return {
        key: MetricValue(key=key, value=value, source="mart://x.parquet")
        for key, value in {
            "study_time_hours.corr.with.exam_score": 0.57,
            "study_time_hours.r2.with.exam_score": 32.2,
        }.items()
    }


def causal_claim(template: str) -> Finding:
    return Finding(
        claim_template=template,
        metric_keys=("study_time_hours.corr.with.exam_score",),
        evidence_ref="mart://x.parquet",
        confidence=0.9,
    )


@pytest.mark.parametrize(
    "template",
    [
        "Gio hoc lam tang diem thi, he so {study_time_hours.corr.with.exam_score}.",
        "Hoc nhieu khien diem cao hon: {study_time_hours.corr.with.exam_score}.",
        "Gio hoc anh huong den diem thi {study_time_hours.corr.with.exam_score}.",
        "Thoi gian hoc dan den ket qua tot hon {study_time_hours.corr.with.exam_score}.",
    ],
)
def test_a_correlation_may_not_be_written_as_a_cause(template: str) -> None:
    # Which one moves the other, or whether a third thing moves both, is not in
    # the number. A report that quietly asserts it says more than the data can
    # support.
    problems = check_finding(causal_claim(template), correlation_metrics())
    assert any("nhan qua" in problem for problem in problems)


def test_describing_the_pattern_is_allowed() -> None:
    finding = causal_claim(
        "Gio hoc tuong quan voi diem thi o muc {study_time_hours.corr.with.exam_score}."
    )
    assert check_finding(finding, correlation_metrics()) == []


def test_a_causal_word_is_fine_when_nothing_inferential_was_measured() -> None:
    # The guard applies to claims resting on association. A descriptive count
    # carries no such implication either way.
    plain = {"rows.total": MetricValue(key="rows.total", value=1000.0, source="mart://x.parquet")}
    finding = Finding(
        claim_template="Viec bo hoc dan den {rows.total} dong bi loai.",
        metric_keys=("rows.total",),
        evidence_ref="mart://x.parquet",
        confidence=0.9,
    )
    assert check_finding(finding, plain) == []


# --- the process map A6 writes ----------------------------------------------------


def process_map(settings: Settings) -> DataRef:
    """A map on disk, shaped exactly as A6 writes one."""
    found = ProcessMap(
        source="clean://log.parquet",
        metrics=(
            MetricValue(key="process.variant.1.share_pct", value=62.5, unit="%", source="variant"),
            MetricValue(
                key="process.wait.A__to__B.median_hours",
                value=24.0,
                unit="gio",
                source="bottleneck",
            ),
        ),
        variants=(
            ProcessVariant(
                rank=1,
                path="A -> B -> C",
                steps=3,
                cases_key="process.variant.1.cases",
                share_key="process.variant.1.share_pct",
                label="Luong chuan",
            ),
        ),
        handovers=(
            ProcessHandover(
                rank=1,
                source_activity="A",
                target_activity="B",
                total_hours_key="process.wait.A__to__B.total_hours",
                median_hours_key="process.wait.A__to__B.median_hours",
                observations_key="process.wait.A__to__B.observations",
            ),
        ),
    )
    target = resolve("artifacts://r_process_map.json", settings)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(found.model_dump_json(indent=2), encoding="utf-8")
    return DataRef(path="artifacts://r_process_map.json", format="json", content_hash="b" * 64)


def analyse_with_map(
    settings: Settings, proposal: FindingProposal, *, map_first: bool = False
) -> TaskResult:
    """Run A7 with both a mart table and a process map among its inputs."""
    storage.write_parquet(houses(), resolve("mart://houses.parquet", settings))
    table = DataRef(path="mart://houses.parquet", format="parquet", content_hash="a" * 64)
    found = process_map(settings)
    refs = (found, table) if map_first else (table, found)
    agent = AnalystAgent(settings, MANIFEST_DIR, llm=LlmClient(FixedFindings(proposal)))
    return agent.run(
        TaskRequest(scope=token(), input_refs=refs, instruction="quy trinh chay the nao"),
        now=NOW,
    )


PROCESS_FINDING = FindingProposal(
    findings=[
        Finding(
            claim_template="Duong di pho bien nhat chiem {process.variant.1.share_pct}.",
            metric_keys=("process.variant.1.share_pct",),
            evidence_ref="mart://houses.parquet",
            confidence=0.9,
        )
    ]
)


def test_a_finding_may_cite_a_process_metric_like_any_other(settings: Settings) -> None:
    # The whole payoff of naming the measurements: nothing about how a claim is
    # checked had to change for process mining to become quotable.
    result = analyse_with_map(settings, PROCESS_FINDING)
    assert result.status == "OK"
    assert "62.50 %" in result.payload["findings"][0]["claim"]


def test_the_map_is_found_wherever_the_plan_put_it(settings: Settings) -> None:
    # Depending on input order would be a rule nobody writing a plan would know.
    result = analyse_with_map(settings, PROCESS_FINDING, map_first=True)
    assert result.status == "OK"
    assert "62.5" in result.payload["findings"][0]["claim"]


def test_the_path_names_reach_the_prompt_but_their_figures_do_not(settings: Settings) -> None:
    # A model cannot say which path is the common one without being told what
    # the path is - and a figure in front of it is a figure it can copy.
    llm = FixedFindings(PROCESS_FINDING)
    storage.write_parquet(houses(), resolve("mart://houses.parquet", settings))
    table = DataRef(path="mart://houses.parquet", format="parquet", content_hash="a" * 64)
    AnalystAgent(settings, MANIFEST_DIR, llm=LlmClient(llm)).run(
        TaskRequest(
            scope=token(),
            input_refs=(table, process_map(settings)),
            instruction="quy trinh chay the nao",
        ),
        now=NOW,
    )
    payload = json.loads(llm.last.prompt)
    paths = payload["process_paths"]
    assert paths and paths[0]["path"] == "A -> B -> C"
    assert paths[0]["label"] == "Luong chuan"
    assert all(not isinstance(value, float) for entry in paths for value in entry.values())


def test_a_run_without_a_process_map_carries_on_unchanged(settings: Settings) -> None:
    # Most tables are not event logs. The join must not quietly become a
    # requirement, and a claim citing an ordinary metric must still work.
    result = analyse(settings, FindingProposal(findings=[GOOD]))
    assert result.status == "OK"
    assert not [key for key in result.payload["findings"][0]["claim"] if key.startswith("process")]


def test_a_process_metric_cited_with_no_map_supplied_is_refused(settings: Settings) -> None:
    # The placeholder has nothing behind it, so the claim is dropped rather than
    # rendered with a gap where the number should be.
    result = analyse(settings, PROCESS_FINDING)
    assert result.status == "FAILED"
    assert result.error is not None


def test_the_prompt_says_what_a_process_metric_means() -> None:
    # The unit is attached by code, so the model must be told not to write one.
    request = build_analysis_request([], "cau hoi", 3, process=[{"path": "A -> B"}])
    assert "process." in request.prompt
    assert "median_hours" in request.prompt


# --- L86: xep hang mot nhom la mot phat bieu ve mot cai TEN --------------------


def ranked_metrics() -> dict[str, MetricValue]:
    """Bon nhom co the so sanh, cong vai thong ke ve chinh phep so sanh do."""
    return {
        key: MetricValue(key=key, value=value, unit=unit, source="mart://x.parquet")
        for key, value, unit in [
            ("gio_xu_ly.mean", 24.73, ""),
            ("gio_xu_ly.mean.by.nhom_van_de.ky_thuat", 24.2561, ""),
            ("gio_xu_ly.mean.by.nhom_van_de.tai_khoan", 24.5875, ""),
            ("gio_xu_ly.mean.by.nhom_van_de.thanh_toan", 24.6624, ""),
            ("gio_xu_ly.mean.by.nhom_van_de.van_chuyen", 25.4173, ""),
            ("gio_xu_ly.anova.by.nhom_van_de.f_stat", 0.0723, ""),
            ("gio_xu_ly.anova.by.nhom_van_de.p_value", 0.9748, ""),
            ("gio_xu_ly.anova.by.nhom_van_de.groups", 4.0, "nhom"),
            ("nhom_van_de.distinct", 4.0, "gia tri"),
            ("nhom_van_de.ky_thuat.count", 100.0, "dong"),
        ]
    }


def test_a_breakdown_of_groups_is_told_apart_from_statistics_about_it() -> None:
    # gio_xu_ly.anova.by.nhom_van_de.p_value looks exactly like a group called
    # "p_value" unless the statistic names are known. Ranking p_value against
    # f_stat would be arithmetic on two unrelated quantities.
    families = group_families(ranked_metrics())
    assert set(families) == {"gio_xu_ly.mean.by.nhom_van_de"}
    assert families["gio_xu_ly.mean.by.nhom_van_de"]["van_chuyen"] == 25.4173


def test_the_real_sentence_that_started_this_is_refused() -> None:
    # Verbatim from a run on phieu_ho_tro.csv. The metric is real, the value is
    # real, no digit was typed - and it reads "Nhom van de 4 gia tri co thoi
    # gian xu ly trung binh cao nhat", which means nothing.
    finding = Finding(
        claim_template=(
            "Nhom van de {nhom_van_de.distinct} co thoi gian xu ly trung binh cao nhat, "
            "la {gio_xu_ly.mean}."
        ),
        metric_keys=("nhom_van_de.distinct", "gio_xu_ly.mean"),
        evidence_ref="mart://x.parquet",
        confidence=0.8,
    )
    problems = check_finding(finding, ranked_metrics())
    assert any("khong tro toi chi so cua nhom nao" in problem for problem in problems)


def test_naming_the_wrong_group_as_highest_is_refused() -> None:
    # ky_thuat is the fastest of the four, not the slowest. Nothing about the
    # sentence gives that away - only the numbers do, and code has them.
    problem = extreme_misuse(
        "Nhom ky_thuat co thoi gian xu ly cao nhat {gio_xu_ly.mean.by.nhom_van_de.ky_thuat}.",
        ["gio_xu_ly.mean.by.nhom_van_de.ky_thuat"],
        ranked_metrics(),
    )
    assert problem is not None
    assert "van_chuyen" in problem


def test_naming_the_right_group_as_highest_passes() -> None:
    problem = extreme_misuse(
        "Nhom van_chuyen lau nhat {gio_xu_ly.mean.by.nhom_van_de.van_chuyen}.",
        ["gio_xu_ly.mean.by.nhom_van_de.van_chuyen"],
        ranked_metrics(),
    )
    assert problem is None


def test_the_lowest_group_is_checked_in_its_own_direction() -> None:
    # The same claim is right one way round and wrong the other.
    metrics = ranked_metrics()
    key = "gio_xu_ly.mean.by.nhom_van_de.ky_thuat"
    assert extreme_misuse(f"Nhom ky_thuat nhanh nhat {{{key}}}.", [key], metrics) is None
    assert extreme_misuse(f"Nhom ky_thuat cham nhat {{{key}}}.", [key], metrics) is not None


def test_an_extreme_the_code_computed_needs_no_second_opinion() -> None:
    # gio_xu_ly.max IS the maximum. There is no group being ranked here, and
    # demanding one would ban a perfectly ordinary sentence.
    metrics = dict(ranked_metrics())
    metrics["gio_xu_ly.max"] = MetricValue(
        key="gio_xu_ly.max", value=51.75, source="mart://x.parquet"
    )
    claim = "Thoi gian xu ly cao nhat la {gio_xu_ly.max}."
    assert extreme_misuse(claim, ["gio_xu_ly.max"], metrics) is None


def test_a_sentence_naming_both_ends_is_not_a_ranking_claim() -> None:
    # "cao nhat X, thap nhat Y" asserts no single rank, so there is nothing to
    # check and rejecting it would be a false alarm.
    keys = [
        "gio_xu_ly.mean.by.nhom_van_de.van_chuyen",
        "gio_xu_ly.mean.by.nhom_van_de.ky_thuat",
    ]
    claim = (
        "Cao nhat {gio_xu_ly.mean.by.nhom_van_de.van_chuyen}, "
        "thap nhat {gio_xu_ly.mean.by.nhom_van_de.ky_thuat}."
    )
    assert extreme_misuse(claim, keys, ranked_metrics()) is None


def test_a_claim_that_ranks_nothing_is_left_alone() -> None:
    # Most findings do not rank anything. The check must be silent on them.
    claim = "Thoi gian xu ly trung binh la {gio_xu_ly.mean}."
    assert extreme_misuse(claim, ["gio_xu_ly.mean"], ranked_metrics()) is None


def test_the_ranking_handed_to_the_model_carries_keys_not_numbers() -> None:
    # Same division as process_paths. Each key is a handle the model spends two
    # ways - {ten:key} for the name, {key} for the figure - and the figure never
    # leaves its key, where the digit rule can still reach it.
    ranked = rankings(ranked_metrics())
    assert ranked == [
        {"xep_hang": "cao nhat", "khoa": "gio_xu_ly.mean.by.nhom_van_de.van_chuyen"},
        {"xep_hang": "thap nhat", "khoa": "gio_xu_ly.mean.by.nhom_van_de.ky_thuat"},
    ]
    assert not [
        value for row in ranked for value in row.values() if any(c.isdigit() for c in value)
    ]


def test_the_prompt_hands_over_the_ranking_and_says_what_to_do_with_it() -> None:
    # Refusing a wrong ranking left the question unanswered. A new field with no
    # rule explaining it is L80 again: the model picks wrong among 160 keys.
    request = build_analysis_request(
        [],
        "nhom nao lau nhat?",
        3,
        ranked=rankings(ranked_metrics()),
    )
    assert "xep_hang_nhom" in request.prompt
    assert "van_chuyen" in request.prompt
    assert "code da so sanh san" in request.prompt


def test_a_run_with_no_breakdown_hands_over_an_empty_ranking() -> None:
    # One column of numbers has no groups to rank. The field must still exist,
    # empty, rather than the model inventing what it would have contained.
    plain = {"rows.total": MetricValue(key="rows.total", value=1000.0, source="mart://x.parquet")}
    assert rankings(plain) == []


# --- goi ten mot nhom ma khong phai go ten no ---------------------------------


def test_a_name_placeholder_renders_the_group_name_not_its_value() -> None:
    # The whole point. Asked to compare two months the model wrote
    # "o {diem_hai_long.by.ngay_mo.1970-01}", which rendered as "o 5" - the
    # label it was reaching for disappeared into the number.
    finding = Finding(
        claim_template=(
            "Nhom {ten:gio_xu_ly.mean.by.nhom_van_de.van_chuyen} lau nhat, "
            "{gio_xu_ly.mean.by.nhom_van_de.van_chuyen}."
        ),
        evidence_ref="mart://x.parquet",
        confidence=0.8,
    )
    rendered = render_finding(finding, ranked_metrics())
    assert rendered.claim == "Nhom van_chuyen lau nhat, 25.42."


def test_a_name_placeholder_is_not_counted_as_citing_a_figure() -> None:
    # A claim made only of names states nothing checkable, so the existing rule
    # that every claim must cite a metric has to keep applying.
    template = "Nhom {ten:gio_xu_ly.mean.by.nhom_van_de.van_chuyen} cham."
    assert placeholders(template) == []
    assert name_placeholders(template) == ["gio_xu_ly.mean.by.nhom_van_de.van_chuyen"]
    finding = Finding(claim_template=template, evidence_ref="mart://x.parquet")
    assert any("khong tro toi chi so nao" in p for p in check_finding(finding, ranked_metrics()))


def test_naming_a_calculation_instead_of_a_group_is_refused() -> None:
    # "distinct" is the name of a calculation. Rendering it would produce
    # "Nhom van de distinct", which is the same failure in a new costume.
    finding = Finding(
        claim_template="Nhom {ten:nhom_van_de.distinct} cham nhat, {gio_xu_ly.mean}.",
        evidence_ref="mart://x.parquet",
    )
    problems = check_finding(finding, ranked_metrics())
    assert any("khong phai ten cua mot nhom nao ca" in problem for problem in problems)


def test_a_name_placeholder_still_has_to_name_the_real_extreme() -> None:
    # Naming a group is not a way around the ranking check.
    finding = Finding(
        claim_template=(
            "Nhom {ten:gio_xu_ly.mean.by.nhom_van_de.ky_thuat} lau nhat, {gio_xu_ly.mean}."
        ),
        evidence_ref="mart://x.parquet",
    )
    problems = check_finding(finding, ranked_metrics())
    assert any("van_chuyen" in problem for problem in problems)


def test_the_label_is_the_last_segment_of_the_key() -> None:
    assert label_of("gio_xu_ly.mean.by.nhom_van_de.van_chuyen") == "van_chuyen"
    assert label_of("diem_hai_long.by.ngay_mo.1970-01") == "1970-01"


def test_a_digit_inside_a_name_placeholder_is_not_an_invented_number() -> None:
    # Period labels carry digits. Banning them would ban naming a month, which
    # is exactly the corner L79 was about.
    metrics = dict(ranked_metrics())
    for label, value in [("1970-01", 5.0), ("2026-01", 3.11)]:
        key = f"diem_hai_long.mean.by.ngay_mo.{label}"
        metrics[key] = MetricValue(key=key, value=value, source="mart://x.parquet")
    finding = Finding(
        claim_template=(
            "Thang {ten:diem_hai_long.mean.by.ngay_mo.1970-01} dat "
            "{diem_hai_long.mean.by.ngay_mo.1970-01}."
        ),
        evidence_ref="mart://x.parquet",
    )
    assert check_finding(finding, metrics) == []
    assert render_finding(finding, metrics).claim == "Thang 1970-01 dat 5."


def test_the_prompt_teaches_the_name_placeholder() -> None:
    # A new mechanism with no rule explaining it is L80 again.
    request = build_analysis_request([], "nhom nao lau nhat?", 3)
    assert "{ten:<khoa>}" in request.prompt


def test_declaring_both_forms_of_the_same_citation_is_accepted() -> None:
    # What the model actually did the first time it used a name placeholder: it
    # listed every placeholder it wrote, both forms. That is the honest thing to
    # do, and a check that only knew about values rejected the very claims this
    # mechanism exists to make possible.
    key = "gio_xu_ly.mean.by.nhom_van_de.van_chuyen"
    finding = Finding(
        claim_template=f"Nhom {{ten:{key}}} lau nhat, {{{key}}}.",
        metric_keys=(key, f"ten:{key}"),
        evidence_ref="mart://x.parquet",
    )
    assert check_finding(finding, ranked_metrics()) == []


def test_a_unit_typed_after_a_placeholder_that_has_one_is_refused() -> None:
    # Real output: "voi ty le 0 %%" - code appends the unit, the model wrote it
    # too. The prompt has forbidden this for a long time; nothing checked it.
    metrics = {
        "chuyen_cap.null_pct": MetricValue(
            key="chuyen_cap.null_pct", value=0.0, unit="%", source="mart://x.parquet"
        )
    }
    finding = Finding(
        claim_template="Khong co gia tri thieu, ty le {chuyen_cap.null_pct}%.",
        evidence_ref="mart://x.parquet",
    )
    problems = check_finding(finding, metrics)
    assert any("da co don vi" in problem for problem in problems)


def test_a_placeholder_with_no_unit_may_be_followed_by_anything() -> None:
    # Only the metric's own unit is the problem. Ordinary words must stay legal.
    metrics = ranked_metrics()
    claim = "Thoi gian xu ly trung binh {gio_xu_ly.mean} gio lam viec."
    assert doubled_unit(claim, metrics) is None


def vietnamese_metrics() -> dict[str, MetricValue]:
    """A yes/no column, spelled the way the data really spells it."""
    return {
        key: MetricValue(key=key, value=value, source="mart://x.parquet")
        for key, value in {
            "gio_xu_ly.mean.by.chuyen_cap.Có": 51.75,
            "gio_xu_ly.mean.by.chuyen_cap.Không": 20.33,
        }.items()
    }


def test_a_label_with_vietnamese_diacritics_can_be_cited() -> None:
    # An ASCII-only placeholder pattern did not see these at all, so a claim
    # about them counted as citing nothing and was thrown away. On Vietnamese
    # data that is most labels.
    template = "Phieu {ten:gio_xu_ly.mean.by.chuyen_cap.Có} mat {gio_xu_ly.mean.by.chuyen_cap.Có}."
    assert placeholders(template) == ["gio_xu_ly.mean.by.chuyen_cap.Có"]
    assert name_placeholders(template) == ["gio_xu_ly.mean.by.chuyen_cap.Có"]


def test_a_vietnamese_label_renders_as_its_own_name() -> None:
    finding = Finding(
        claim_template=(
            "Phieu chuyen cap {ten:gio_xu_ly.mean.by.chuyen_cap.Có} mat "
            "{gio_xu_ly.mean.by.chuyen_cap.Có}."
        ),
        evidence_ref="mart://x.parquet",
    )
    metrics = vietnamese_metrics()
    assert check_finding(finding, metrics) == []
    assert render_finding(finding, metrics).claim == "Phieu chuyen cap Có mat 51.75."


# --- khong ai khai dimensions ---------------------------------------------------


def labelled() -> pd.DataFrame:
    """Cau va nhan, dung hinh dang cua emotions.txt sau khi them cot so tu.

    Muoi hai dong, ba nhan. Du de moi nhan that su la mot nhom, va du de cot
    cau - moi dong mot gia tri - khong bi nham la mot cach chia nhom.
    """
    sentences = [
        "i feel sad today",
        "i am angry now",
        "so happy today",
        "i feel calm and happy",
        "this makes me furious",
        "what a lovely day",
        "i am so down",
        "i hate this so much",
        "everything is wonderful",
        "i feel empty inside",
        "i am furious about it",
        "a joyful morning",
    ]
    return pd.DataFrame(
        {
            "cot_1": sentences,
            "cot_2": ["sadness", "anger", "joy"] * 4,
            "word_count": [float(len(text.split())) for text in sentences],
        }
    )


def test_a_label_column_is_something_to_group_by() -> None:
    # Not judgement: few enough distinct values to be groups, more than one so
    # there is something to compare.
    assert groupable_columns(labelled()) == ("cot_2",)


def test_a_free_text_column_is_not_a_grouping() -> None:
    # cot_1 is a different sentence every row. Grouping by it gives one row per
    # group, which is not a comparison.
    assert "cot_1" not in groupable_columns(labelled())


def test_a_numeric_column_is_not_a_grouping() -> None:
    assert "word_count" not in groupable_columns(labelled())


def test_a_single_valued_column_is_not_a_grouping() -> None:
    # One group is not a comparison either.
    frame = labelled().assign(nguon="web")
    assert "nguon" not in groupable_columns(frame)


def test_per_group_metrics_exist_even_when_nobody_asked_for_them(settings: Settings) -> None:
    # Measured on emotions.txt: asked to compare two labels, the run computed no
    # per-label number of any kind, could not answer, and said nothing about
    # why. `dimensions` decides whether those metrics exist at all and is
    # explained nowhere in the planning prompt, so it was never set.
    storage.write_parquet(labelled(), resolve("mart://nhan.parquet", settings))
    ref = DataRef(path="mart://nhan.parquet", format="parquet", content_hash="b" * 64)
    proposal = FindingProposal(
        findings=[
            Finding(
                claim_template="Tong cong {rows.total}.",
                evidence_ref="mart://nhan.parquet",
                confidence=0.8,
            )
        ]
    )
    agent = AnalystAgent(settings, MANIFEST_DIR, llm=LlmClient(FixedFindings(proposal)))
    # params carries no "dimensions" at all - the case that was broken.
    request = TaskRequest(
        scope=token({"measures": []}),
        input_refs=(ref,),
        instruction="so sanh do dai cau theo nhan",
    )
    result = agent.run(request, now=NOW)
    assert result.status == "OK"
    keys = {metric["key"] for metric in result.payload["metrics"]}
    assert "cot_2.joy.count" in keys
    assert "word_count.mean.by.cot_2.anger" in keys


# --- mot phep kiem chua chay thi khong duoc noi la da chay ----------------------


def test_the_real_sentence_claiming_a_test_that_never_ran_is_refused() -> None:
    # Verbatim from a run on emotions.txt, and it passed every rule there was:
    # a real key, no typed digit, no ranking, no doubled unit. No test had run.
    # The model cited one metric and put that figure in the t slot and the p
    # slot both, which read as "t-statistic: 2,666.67, p-value: 2,666.67".
    metrics = {
        "sentence_count.mean": MetricValue(
            key="sentence_count.mean", value=2666.6667, source="mart://x.parquet"
        )
    }
    finding = Finding(
        claim_template=(
            "T-test cho thay co su khac biet dang ke giua hai nhom "
            "(t-statistic: {sentence_count.mean}, p-value: {sentence_count.mean})."
        ),
        evidence_ref="mart://x.parquet",
    )
    problems = check_finding(finding, metrics)
    assert any("khong co phep kiem nao duoc chay" in problem.lower() for problem in problems)


def test_naming_a_test_that_did_run_is_fine() -> None:
    # The metrics are the evidence the test happened. When they are there, the
    # claim is allowed to say so.
    assert (
        untested_claim(
            "Kiem dinh ANOVA cho thay khac biet, {word_count.anova.by.nhan.p_value}.",
            ["word_count.anova.by.nhan.p_value"],
        )
        is None
    )


def test_a_claim_that_mentions_no_test_is_left_alone() -> None:
    # Most findings describe averages. The check must be silent on them.
    assert untested_claim("So tu trung binh la {word_count.mean}.", ["word_count.mean"]) is None


def test_the_word_alone_is_what_triggers_it_not_the_shape_of_the_sentence() -> None:
    # "co y nghia thong ke" is the phrase readers trust most, and it is exactly
    # as much of a claim about a test as naming the test is.
    problem = untested_claim(
        "Khac biet nay co y nghia thong ke, {word_count.mean}.", ["word_count.mean"]
    )
    assert problem is not None
