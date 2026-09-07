"""A9: the Manager answers, under the same rules as everyone else.

This is where invention is most likely - it is the one component whose job is to
draw conclusions - so it is the one held hardest to the same three rules: numbers
stay behind placeholders, every claim cites something real, and what could not be
established is put in front of it before it writes a word.

The tests are written from the failures a real run produced. Two claims once came
back with byte-identical charts of neither of their subjects, and the metric set
once died with the task that computed it, leaving the Manager nothing to cite.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from analysis_system.agents.a9_manager import (
    ManagerAgent,
    build_answer_request,
    verified_needs,
)
from analysis_system.contracts.agents import (
    AnalysisResult,
    DataNeed,
    Finding,
    FindingProposal,
    ManagerAnswer,
    MetricValue,
    ProcessMap,
    RenderedFinding,
)
from analysis_system.contracts.base import DataRef, ScopeToken, TaskRequest
from analysis_system.services import storage
from analysis_system.services.boundary import load_manifest
from analysis_system.services.llm import LlmClient, LlmRequest, LlmResponse
from analysis_system.services.scoped_storage import ScopedStorage
from analysis_system.settings import (
    LAYER_NAMES,
    LayerPaths,
    Settings,
    load_settings,
    resolve,
)

NOW = datetime(2026, 9, 3, 9, 0, tzinfo=UTC)
MANIFEST_DIR = Path(__file__).resolve().parents[2] / "config" / "manifests"


def settings_in(root: Path) -> Settings:
    roots = {name: root / name for name in LAYER_NAMES}
    for path in roots.values():
        path.mkdir(parents=True, exist_ok=True)
    return load_settings().model_copy(update={"layers": LayerPaths(**roots)})


def token(params: dict[str, Any] | None = None) -> ScopeToken:
    """A token matching the shipped a9_manager manifest."""
    return ScopeToken(
        run_id="r_ans",
        task_id="t_answer",
        agent_id="a9_manager",
        allow_read=(
            "artifacts://**",
            "mart://**",
            "clean://**",
            "validation://**",
            "profile://**",
        ),
        allow_write=("artifacts://**",),
        allow_tools=("pandas", "matplotlib"),
        params=params or {"question": "điểm thi phụ thuộc vào những yếu tố gì"},
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
    )


def frame() -> pd.DataFrame:
    rows = 60
    return pd.DataFrame(
        {
            "score": [round(50 + (index * 7) % 40 + 0.5, 1) for index in range(rows)],
            "hours": [round((index * 3) % 11 + 0.5, 1) for index in range(rows)],
            "sleep": [round((index * 5) % 9 + 0.5, 1) for index in range(rows)],
        }
    )


def measured() -> tuple[MetricValue, ...]:
    return (
        MetricValue(key="score.corr.with.hours", value=0.62, source="pearson"),
        MetricValue(key="score.corr.with.sleep", value=0.11, source="pearson"),
        MetricValue(key="rows.total", value=60.0, unit="dong", source="frame"),
        # A summary of the very thing the question is about: relevant beyond
        # doubt, and still not a cause. That pairing is what separates the
        # shape check from the relevance check.
        MetricValue(key="score.mean", value=82.62, unit="diem", source="frame"),
    )


def stage(settings: Settings, *, declined: tuple[str, ...] = ()) -> tuple[DataRef, DataRef]:
    """An analysis artifact and the table behind it, where A9 can read them."""
    found = AnalysisResult(
        source="mart://x.parquet",
        question="diem thi phu thuoc gi",
        findings=(
            RenderedFinding(
                claim="Gio hoc di kem voi diem thi.",
                template="Gio hoc di kem voi diem thi {score.corr.with.hours}.",
                metrics={"score.corr.with.hours": 0.62},
                evidence_ref="mart://x.parquet",
            ),
        ),
        metrics_available=len(measured()),
        metrics=measured(),
        rejected=declined,
    )
    path = resolve("artifacts://r_ans_findings.json", settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(found.model_dump_json(indent=2), encoding="utf-8")

    storage.write_parquet(frame(), resolve("mart://x.parquet", settings))
    return (
        DataRef(path="artifacts://r_ans_findings.json", format="json", content_hash="a" * 64),
        DataRef(path="mart://x.parquet", format="parquet", content_hash="b" * 64),
    )


class Answers:
    """A model that returns one prepared argument."""

    name = "test"

    def __init__(self, proposal: FindingProposal) -> None:
        self._proposal = proposal
        self.last: LlmRequest | None = None

    def complete(self, request: LlmRequest) -> LlmResponse:
        self.last = request
        return LlmResponse(data=self._proposal, provider=self.name, model="test")


GOOD = FindingProposal(
    findings=[
        Finding(
            claim_template="Giờ học đi kèm với điểm thi, hệ số {score.corr.with.hours}.",
            metric_keys=("score.corr.with.hours",),
            evidence_ref="mart://x.parquet",
            confidence=0.9,
        )
    ],
    summary="mot luan diem",
)


def answer_with(
    tmp_path: Path,
    proposal: FindingProposal,
    *,
    declined: tuple[str, ...] = (),
    question: str | None = None,
    context: str = "",
) -> tuple[ManagerAnswer | None, Any, Any]:
    """Run A9 and hand back the answer it wrote, if it wrote one."""
    settings = settings_in(tmp_path)
    params: dict[str, Any] = {}
    if question:
        params["question"] = question
    if context:
        params["boi_canh"] = context
    scope = token(params or None)
    files = ScopedStorage(scope, settings)
    refs = stage(settings, declined=declined)
    model = Answers(proposal)
    result = ManagerAgent(settings, MANIFEST_DIR, llm=LlmClient(model)).execute(
        TaskRequest(scope=scope, input_refs=refs, instruction=""), files
    )
    if result.status != "OK":
        return None, result, model
    written = resolve(result.output_refs[0].path, settings)
    return ManagerAnswer.model_validate_json(written.read_text(encoding="utf-8")), result, model


# --- it answers ---------------------------------------------------------------------


def test_it_turns_the_teams_reports_into_an_answer(tmp_path: Path) -> None:
    answer, result, _ = answer_with(tmp_path, GOOD)
    assert result.status == "OK", result.error
    assert answer is not None
    assert answer.claims
    assert "0.62" in answer.claims[0].claim


def test_a_claim_gets_a_chart_drawn_from_the_metrics_it_cites(tmp_path: Path) -> None:
    # The whole point: the picture beside a sentence is evidence for that
    # sentence, not decoration near it.
    answer, _, _ = answer_with(tmp_path, GOOD)
    assert answer is not None
    assert answer.claims[0].chart_ref.endswith(".png")
    assert answer.claims[0].chart_reason


def test_the_model_never_sees_the_rows(tmp_path: Path) -> None:
    _, _, model = answer_with(tmp_path, GOOD)
    assert model.last is not None
    payload = model.last.prompt
    assert "reports" in payload
    assert "score.corr.with.hours" in payload


# --- and is held to the same rules as everyone else ----------------------------------


def test_a_claim_that_types_its_own_number_is_dropped(tmp_path: Path) -> None:
    # The same machinery A7 has used since Phase 2, reused rather than rebuilt:
    # building a second one would be building a second place to invent a figure.
    typed = FindingProposal(
        findings=[
            Finding(
                claim_template="Gio hoc di kem voi diem thi, he so 0.62.",
                metric_keys=("score.corr.with.hours",),
                evidence_ref="mart://x.parquet",
            )
        ]
    )
    answer, result, _ = answer_with(tmp_path, typed)
    assert answer is None
    assert result.error is not None
    assert result.error.code == "NO_SUPPORTED_CLAIM"


def test_a_claim_citing_a_metric_that_does_not_exist_is_dropped(tmp_path: Path) -> None:
    invented = FindingProposal(
        findings=[
            Finding(
                claim_template="Cai gi do bang {khong.he.co}.",
                metric_keys=("khong.he.co",),
                evidence_ref="mart://x.parquet",
            )
        ]
    )
    answer, result, _ = answer_with(tmp_path, invented)
    assert answer is None
    assert result.error is not None


def test_when_nothing_survives_the_refusal_says_what_it_had_to_work_with(
    tmp_path: Path,
) -> None:
    # "No claim passed" with nothing after it reads the same whether the model
    # wrote nonsense or was handed nothing at all.
    _, result, _ = answer_with(tmp_path, FindingProposal(findings=[]))
    assert result.error is not None
    assert "chi so co san" in result.error.message


# --- the chart has to actually happen ------------------------------------------------


def stage_without_table(settings: Settings) -> DataRef:
    """An analysis artifact and no table alongside it.

    The shape a real plan produced: the Manager was handed what its skills
    wrote, and the table was the run's source, which goes to tasks declaring no
    inputs - and the Manager declares several.
    """
    found = AnalysisResult(
        source="mart://x.parquet",
        question="diem thi phu thuoc gi",
        findings=(
            RenderedFinding(
                claim="Gio hoc di kem voi diem thi.",
                template="Gio hoc di kem voi diem thi {score.corr.with.hours}.",
                metrics={"score.corr.with.hours": 0.62},
                evidence_ref="mart://x.parquet",
            ),
        ),
        metrics_available=len(measured()),
        metrics=measured(),
    )
    path = resolve("artifacts://r_ans_findings.json", settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(found.model_dump_json(indent=2), encoding="utf-8")
    # The table exists where the artifact says it does - just not among the
    # inputs the plan handed over.
    storage.write_parquet(frame(), resolve("mart://x.parquet", settings))
    return DataRef(path="artifacts://r_ans_findings.json", format="json", content_hash="a" * 64)


def test_a_correlation_claim_gets_its_chart_even_when_no_table_was_handed_over(
    tmp_path: Path,
) -> None:
    # L59. Every claim was right, every citation held, and not one chart was
    # drawn - because a scatter plot needs the rows and the rows never arrived.
    # The table is found by following the citation the report already carries.
    settings = settings_in(tmp_path)
    scope = token()
    files = ScopedStorage(scope, settings)
    result = ManagerAgent(settings, MANIFEST_DIR, llm=LlmClient(Answers(GOOD))).execute(
        TaskRequest(scope=scope, input_refs=(stage_without_table(settings),), instruction=""),
        files,
    )
    assert result.status == "OK", result.error
    answer = ManagerAnswer.model_validate_json(
        resolve(result.output_refs[0].path, settings).read_text(encoding="utf-8")
    )
    assert answer.claims[0].chart_ref.endswith(".png")


def test_a_citation_pointing_nowhere_costs_the_chart_and_nothing_else(
    tmp_path: Path,
) -> None:
    # Guessing at the table is not among the options. An unreadable citation
    # means no chart; the claim keeps its numbers and stands.
    settings = settings_in(tmp_path)
    found = AnalysisResult(
        source="mart://khong_he_co.parquet",
        question="q",
        findings=(),
        metrics_available=len(measured()),
        metrics=measured(),
    )
    path = resolve("artifacts://r_ans_findings.json", settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(found.model_dump_json(indent=2), encoding="utf-8")

    scope = token()
    result = ManagerAgent(settings, MANIFEST_DIR, llm=LlmClient(Answers(GOOD))).execute(
        TaskRequest(
            scope=scope,
            input_refs=(
                DataRef(
                    path="artifacts://r_ans_findings.json", format="json", content_hash="a" * 64
                ),
            ),
            instruction="",
        ),
        ScopedStorage(scope, settings),
    )
    assert result.status == "OK", result.error
    answer = ManagerAnswer.model_validate_json(
        resolve(result.output_refs[0].path, settings).read_text(encoding="utf-8")
    )
    assert answer.claims
    assert answer.claims[0].chart_ref == ""


def test_the_run_reports_how_many_claims_got_a_chart(tmp_path: Path) -> None:
    # Countable, so a run that drew none is visible without opening the answer.
    _, result, _ = answer_with(tmp_path, GOOD)
    assert result.metrics["charts"] >= 1.0


# --- what nobody could establish -----------------------------------------------------


def test_what_no_skill_could_establish_is_put_in_front_of_the_model(
    tmp_path: Path,
) -> None:
    # A conclusion drawn over a gap nobody mentioned reads exactly like a sound
    # one, which is why this is the rule that matters most here.
    _, _, model = answer_with(tmp_path, GOOD, declined=("khong du dong de chay hoi quy",))
    assert model.last is not None
    assert "khong du dong de chay hoi quy" in model.last.prompt
    assert "khong_xac_lap_duoc" in model.last.prompt


def test_the_gaps_travel_into_the_answer_itself(tmp_path: Path) -> None:
    answer, result, _ = answer_with(tmp_path, GOOD, declined=("khong kiem duoc thu tu",))
    assert answer is not None
    assert "khong kiem duoc thu tu" in answer.unanswered
    # And onward, so the run reports it without knowing which agent refused.
    assert "khong kiem duoc thu tu" in result.declined


def test_the_prompt_carries_the_rules_the_code_enforces() -> None:
    request = build_answer_request("cau hoi", [{"tu": "phan tich"}], [], [])
    assert "khong_xac_lap_duoc" in request.prompt
    assert "metric_key" in request.system


# --- what it needs ---------------------------------------------------------------


def test_with_no_reports_it_says_so_rather_than_inventing_one(tmp_path: Path) -> None:
    settings = settings_in(tmp_path)
    scope = token()
    result = ManagerAgent(settings, MANIFEST_DIR).execute(
        TaskRequest(scope=scope, input_refs=(), instruction=""), ScopedStorage(scope, settings)
    )
    assert result.status == "FAILED"
    assert result.error is not None
    assert result.error.code == "NO_REPORTS"
    assert result.error.replannable


def test_it_reads_a_process_map_as_readily_as_an_analysis(tmp_path: Path) -> None:
    # Recognised by shape rather than by which agent produced it, so a skill
    # added later reports upward without this having to learn its name.
    settings = settings_in(tmp_path)
    found = ProcessMap(
        source="clean://log.parquet",
        metrics=(MetricValue(key="process.cases", value=100.0, unit="case", source="volume"),),
        refused=("khong co cot thoi gian",),
    )
    path = resolve("artifacts://r_ans_map.json", settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(found.model_dump_json(indent=2), encoding="utf-8")

    scope = token()
    model = Answers(GOOD)
    result = ManagerAgent(settings, MANIFEST_DIR, llm=LlmClient(model)).execute(
        TaskRequest(
            scope=scope,
            input_refs=(
                DataRef(path="artifacts://r_ans_map.json", format="json", content_hash="c" * 64),
            ),
            instruction="",
        ),
        ScopedStorage(scope, settings),
    )
    assert model.last is not None
    assert "khai thac quy trinh" in model.last.prompt
    assert "khong co cot thoi gian" in model.last.prompt
    assert result is not None


# --- the manifest ------------------------------------------------------------------


def test_the_manager_is_bound_like_every_other_agent() -> None:
    # Exempting it from the rules would put the least-checked component exactly
    # where the most damage is done.
    manifest = load_manifest("a9_manager", MANIFEST_DIR)
    assert manifest.allow.write == ("artifacts://**",)
    assert "raw://**" not in manifest.allow.read
    assert "state_number_not_in_metrics" in manifest.deny


def test_a_person_approves_the_argument_before_it_becomes_a_report() -> None:
    gate = load_manifest("a9_manager", MANIFEST_DIR).human_gate
    assert gate.required
    assert gate.at == "after_execution"
    assert gate.approve == "claims"


@pytest.mark.parametrize("layer", ["raw://x.csv", "clean://x.parquet"])
def test_it_cannot_write_outside_artifacts(tmp_path: Path, layer: str) -> None:
    from analysis_system.services.boundary import BoundaryViolation

    files = ScopedStorage(token(), settings_in(tmp_path))
    with pytest.raises(BoundaryViolation):
        files.save_text("{}", layer)


# --- and answers the question that was actually asked --------------------------------

# The embedding model is a download rather than something pip put in place. Where
# it is missing these skip, the same way the transcription tests do.
NEEDS_MODEL = pytest.mark.skipif(
    not (Path.home() / ".cache" / "huggingface").is_dir(),
    reason="chua tai model do do lien quan",
)

BESIDE_THE_POINT = FindingProposal(
    findings=[
        Finding(
            claim_template="Bảng có {rows.total} dòng dữ liệu.",
            metric_keys=("rows.total",),
            evidence_ref="mart://x.parquet",
            confidence=0.9,
        )
    ],
    summary="mot con so that",
)


@NEEDS_MODEL
def test_a_true_claim_that_answers_nothing_is_set_aside(tmp_path: Path) -> None:
    """The run this whole check was built for.

    Asked which factors carry exam results, the Manager reported the average
    attendance and the share of missing values. Every figure real, every citation
    good, and not an answer to anything - and enough of those leave the reader
    doing the sorting the system exists to do.
    """
    answer, result, _ = answer_with(
        tmp_path, BESIDE_THE_POINT, question="Yếu tố nào ảnh hưởng đến điểm thi cuối kỳ?"
    )
    assert answer is None
    assert result.error is not None
    assert result.error.code == "NO_SUPPORTED_CLAIM"


@NEEDS_MODEL
def test_what_was_set_aside_is_named_with_its_score(tmp_path: Path) -> None:
    """Dropped in silence is indistinguishable from never said.

    The reader has to be able to disagree with the filter, which means seeing
    what it took out and how close the call was.
    """
    _, result, _ = answer_with(
        tmp_path, BESIDE_THE_POINT, question="Yếu tố nào ảnh hưởng đến điểm thi cuối kỳ?"
    )
    assert result.error is not None
    assert "khong tra loi cau hoi" in result.error.message
    assert "do lien quan" in result.error.message


@NEEDS_MODEL
def test_a_claim_that_does_answer_the_question_survives(tmp_path: Path) -> None:
    """The other direction: a filter that drops everything would pass the tests above."""
    answer, result, _ = answer_with(
        tmp_path, GOOD, question="Yếu tố nào ảnh hưởng đến điểm thi cuối kỳ?"
    )
    assert result.status == "OK", result.error
    assert answer is not None
    assert answer.claims


def test_without_a_scorer_nothing_is_filtered_and_the_answer_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing model must not quietly become a stricter filter.

    Filtering with something unavailable, or falling back to comparing words -
    which discarded seven real answers out of sixteen when it was measured -
    would throw away findings to work around a download that failed. The claim
    stays, and the answer admits it went unchecked.
    """

    def no_model(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("khong tai duoc model")

    monkeypatch.setattr("analysis_system.agents.a9_manager.judge", no_model)
    answer, result, _ = answer_with(
        tmp_path, BESIDE_THE_POINT, question="Yếu tố nào ảnh hưởng đến điểm thi cuối kỳ?"
    )
    assert result.status == "OK", result.error
    assert answer is not None
    assert answer.claims, "mot model thieu khong duoc bien thanh bo loc chat hon"
    assert any("khong kiem duoc do lien quan" in note for note in answer.rejected)


# --- and answers the KIND of thing that was asked for -------------------------------

# About exam scores beyond any doubt - so the relevance check passes it - and a
# mean, so it cannot say what carries them. Relevance and shape catch different
# failures, and this claim is the case that separates them.
A_MEAN_NOT_A_CAUSE = FindingProposal(
    findings=[
        Finding(
            claim_template="Điểm thi cuối kỳ trung bình đạt {score.mean} điểm.",
            metric_keys=("score.mean",),
            evidence_ref="mart://x.parquet",
            confidence=0.9,
        )
    ],
    summary="mot con so that ve dung chu de",
)


def test_a_cause_question_answered_with_a_count_says_so(tmp_path: Path) -> None:
    """True, cited, on the right subject - and not an answer.

    Asked which factors carry the exam score, a run came back with a row count.
    Nothing about it is false; nothing about it says what moves what. The reader
    is told that in the answer rather than left to notice.
    """
    answer, result, _ = answer_with(
        tmp_path,
        A_MEAN_NOT_A_CAUSE,
        question="Yếu tố nào ảnh hưởng đến điểm thi cuối kỳ?",
    )
    assert result.status == "OK", result.error
    assert answer is not None
    assert any("NGUYEN NHAN" in note for note in answer.unanswered)
    assert result.metrics["answers_the_question"] == 0.0


def test_an_unmet_demand_never_costs_a_claim(tmp_path: Path) -> None:
    """The check reports; it does not delete.

    A question about causes answered with a true average still leaves the reader
    better off with the average plus a sentence saying it is not a cause than
    with nothing at all. A check built to help must not start destroying work.
    """
    answer, _, _ = answer_with(
        tmp_path,
        A_MEAN_NOT_A_CAUSE,
        question="Yếu tố nào ảnh hưởng đến điểm thi cuối kỳ?",
    )
    assert answer is not None
    assert answer.claims, "luan diem that van phai duoc giu"
    assert answer.claims[0].metric_keys == ("score.mean",)


def test_a_cause_question_answered_with_a_relationship_passes_clean(tmp_path: Path) -> None:
    """The other direction: a check that flagged everything would pass the tests above."""
    answer, result, _ = answer_with(
        tmp_path, GOOD, question="Yếu tố nào ảnh hưởng đến điểm thi cuối kỳ?"
    )
    assert result.status == "OK", result.error
    assert answer is not None
    assert result.metrics["answers_the_question"] == 1.0
    assert not any("NGUYEN NHAN" in note for note in answer.unanswered)


# --- Manager hoi nguoc, nhung chi ve cai da that su bi tu choi ---------------------


def test_a_request_pointing_at_a_real_refusal_is_kept() -> None:
    """The difference between a statement and something a reader can act on.

    "khong noi duoc ve mua vu" makes a reader shrug. "cho toi them mot nam du
    lieu" sends them to fetch it.
    """
    refusals = ["chi co mot chu ky nen khong noi duoc ve mua vu."]
    kept, dropped = verified_needs(
        [
            DataNeed(
                blocked_by="chi co mot chu ky nen khong noi duoc ve mua vu.",
                ask="du lieu ban hang cua nam truoc",
                unlocks="so sanh cung ky giua hai nam",
            )
        ],
        refusals,
    )
    assert len(kept) == 1
    assert dropped == []


def test_a_request_pointing_at_nothing_is_dropped() -> None:
    """The same rule that governs figures, aimed at a different invention.

    A claim may only cite a metric that was computed; a request may only name a
    refusal that happened. A plausible request is worse than none - somebody
    goes and fetches data that changes nothing.
    """
    kept, dropped = verified_needs(
        [
            DataNeed(
                blocked_by="du lieu thieu cot doanh thu theo vung",
                ask="bang doanh thu theo tinh thanh",
            )
        ],
        ["chi co mot chu ky nen khong noi duoc ve mua vu."],
    )
    assert kept == ()
    assert len(dropped) == 1
    assert "khong he xay ra" in dropped[0]


def test_dropping_a_request_is_said_out_loud() -> None:
    """A request removed in silence looks like a Manager that needed nothing."""
    _, dropped = verified_needs(
        [DataNeed(blocked_by="bia ra", ask="them du lieu")],
        ["mot han che that"],
    )
    assert "them du lieu" in dropped[0]


def test_a_quote_retyped_with_different_accents_still_matches() -> None:
    """A model re-types a sentence; refusing over a diacritic teaches nobody."""
    kept, _ = verified_needs(
        [DataNeed(blocked_by="CHI CO MOT CHU KY", ask="them mot nam du lieu")],
        ["chi co mot chu ky nen khong noi duoc ve mua vu."],
    )
    assert len(kept) == 1


def test_the_stored_request_carries_the_refusal_as_it_really_reads() -> None:
    """Not as the model re-typed it.

    The reader follows this back to the run's own refusals, and a paraphrase
    would not be findable there.
    """
    real = "chi co 12 dong - duoi 40 thi mot 'nhom' chi la vai diem gan nhau do ngau nhien."
    kept, _ = verified_needs([DataNeed(blocked_by="chi co 12 dong", ask="them du lieu")], [real])
    assert kept[0].blocked_by == real


def test_asking_for_nothing_is_a_valid_answer() -> None:
    """An empty list beats a list made to look thorough."""
    assert verified_needs([], ["mot han che"]) == ((), [])


def test_the_needs_reach_the_answer_and_the_metrics(tmp_path: Path) -> None:
    """End to end, so the wiring is proved rather than assumed."""
    asking = FindingProposal(
        findings=list(GOOD.findings),
        needs=[
            DataNeed(
                blocked_by="khong tu chay hoi quy",
                ask="khai bao bien giai thich trong tests.regressions",
                unlocks="do duoc bien nao mang ket qua",
            )
        ],
    )
    answer, result, _ = answer_with(
        tmp_path,
        asking,
        declined=("khong tu chay hoi quy - phai khai trong tests.regressions",),
    )
    assert answer is not None
    assert len(answer.needs) == 1
    assert answer.needs[0].ask.startswith("khai bao")
    assert result.metrics["needs"] == 1.0


def test_an_invented_need_never_reaches_the_answer(tmp_path: Path) -> None:
    inventing = FindingProposal(
        findings=list(GOOD.findings),
        needs=[DataNeed(blocked_by="mot han che khong ai noi", ask="du lieu doi thu")],
    )
    answer, result, _ = answer_with(tmp_path, inventing)
    assert answer is not None
    assert answer.needs == ()
    assert result.metrics["needs"] == 0.0
    assert any("khong he xay ra" in note for note in answer.rejected)


# --- thu hang do CODE tinh, khong de Manager tu do ---------------------------------


def test_the_manager_is_handed_the_ranking_of_every_breakdown() -> None:
    """A7 duoc dua thu hang tu lau; A9 thi khong, va no do sai.

    Tren mot lan chay that, cung mot cau tra loi noi sai nhom cao nhat BA lan:
    'Fund_Diversification' thay vi 'Better_Returns', 'Fixed_Returns' thay vi
    'Risk_Free', 'Newspapers_and_Magazines' thay vi 'Financial_Consultants'.
    Ca ba bi nem di, va nguoi hoi mat ba phan tu cau tra loi.
    """
    ranked = [{"family": "Reason_FD.share_pct", "cao_nhat": "Risk_Free"}]

    request = build_answer_request("Vì sao chọn FD?", [], [], [], None, ranked)

    assert "xep_hang_nhom" in request.prompt
    assert "Risk_Free" in request.prompt


def test_without_a_ranking_the_field_is_present_and_empty() -> None:
    # Co mat va rong khac han vang mat: model doc mot khoa rong thi biet la
    # khong co gi, con khong thay khoa nao thi no tu di tim cau tra loi.
    request = build_answer_request("Câu hỏi", [], [], [])
    assert '"xep_hang_nhom": []' in request.prompt


def test_the_manager_is_told_to_take_the_ranking_rather_than_work_it_out() -> None:
    # Du lieu co mat ma khong ai bao dung thi model van tu do.
    request = build_answer_request("Câu hỏi", [], [], [])
    assert "xep_hang_nhom" in request.prompt
    assert "Code da xep san" in request.system


# --- he qua thuc tien, khong phai chien luoc --------------------------------------


def rules_of(request: LlmRequest) -> str:
    """Toan bo phan luat, de doc bang mat.

    Luat nam trong `system`, khong nam trong payload du lieu: o `boi_canh` la
    van ban nguoi dung tu go, va de chung mot cau truc voi luat thi mot dong
    "bo qua moi luat tren" doc y het mot luat.
    """
    return request.system


def test_the_manager_is_asked_what_the_number_means() -> None:
    """Chu he thong cham: "chi liet ke so lieu tho, khong co gia tri thuc tien".

    Do la mot LUAT da viet, khong phai thieu sot - va cach go la doi "chien
    luoc" thanh "he qua": mot ben doi suy dien nhan qua va kien thuc nganh, mot
    ben doc thang tu chinh con so.
    """
    rules = rules_of(build_answer_request("Câu hỏi", [], [], []))
    assert "CO NGHIA GI" in rules


def test_there_is_a_way_out_when_a_number_means_nothing() -> None:
    """Chot chan quan trong nhat cua A2.

    Doi y nghia ma khong cho duong thoat thi model se LUON noi duoc mot cau - ke
    ca khi con so do chang co y nghia thuc tien nao. Do la cach che tao insight
    rong, va no nguy hiem hon ca may dem so.
    """
    rules = rules_of(build_answer_request("Câu hỏi", [], [], []))
    assert "chua noi duoc gi" in rules


def test_recommending_an_action_is_still_forbidden() -> None:
    # Noi long phan y nghia KHONG duoc keo theo noi long phan nay: mot he thong
    # bia ra "nen do tien vao dau" tu 40 dong du lieu thi nguy hiem hon mot he
    # thong im lang.
    rules = rules_of(build_answer_request("Câu hỏi", [], [], []))
    assert "Khong khuyen hanh dong" in rules


def test_causal_language_is_still_forbidden() -> None:
    rules = rules_of(build_answer_request("Câu hỏi", [], [], []))
    assert "Khong suy dien nhan qua" in rules


# --- cot duoc hoi ten ma ca cau tra loi khong cham toi -------------------------

# Bang chu giai nguoi dung tu viet trong o Boi canh. Nho no ma cau hoi tieng
# Viet goi duoc ten cot - va do la thu code doi chieu duoc, khac han mot cai
# nhan may tu doan.
CHU_GIAI = "hours = giờ học\nscore = điểm thi"


def test_a_column_named_only_through_the_glossary_is_noticed(tmp_path: Path) -> None:
    """Loi that, thu nho lai: hoi mot dang, tra loi bang cot khac.

    Luan diem GOOD dua tren cot `score`. Cau hoi noi ve "gio hoc", ma chu giai
    khai "gio hoc" la cot `hours` - khong luan diem nao cham toi no.
    """
    answer, result, _ = answer_with(
        tmp_path,
        GOOD,
        question="giờ học của học sinh thế nào",
        context=CHU_GIAI,
    )
    assert result.status == "OK", result.error
    assert answer is not None
    assert any("hours" in line for line in answer.unanswered)


def test_that_warning_reaches_the_top_of_the_page(tmp_path: Path) -> None:
    """No phai nam trong `warnings`, khoi do code gan len dau cau tra loi.

    Nam duoi `unanswered` thoi thi nguoi doc gap phai no sau khi da doc xong
    moi con so - tuc la sau khi da tin.
    """
    answer, _, _ = answer_with(
        tmp_path,
        GOOD,
        question="giờ học của học sinh thế nào",
        context=CHU_GIAI,
    )
    assert answer is not None
    assert any("hours" in line for line in answer.warnings)


def test_without_a_glossary_it_stays_quiet(tmp_path: Path) -> None:
    """Khong khai thi khong doan. Day la ca thuong gap nhat."""
    answer, _, _ = answer_with(tmp_path, GOOD, question="giờ học của học sinh thế nào")
    assert answer is not None
    assert not any("chưa được trả lời" in line for line in answer.warnings)


# --- menh lenh mot cho, du lieu mot cho ---------------------------------------


def test_the_rules_are_not_in_the_data_payload() -> None:
    """O `boi_canh` la van ban nguoi dung tu go, va no di trong payload du lieu.

    De luat nam cung mot cau truc voi no thi mot dong "bo qua moi luat phia
    tren" go vao o Boi canh se nam ngang hang voi luat that, va viec no co duoc
    nghe theo hay khong chi con la chuyen may rui ve cach dien dat.
    """
    request = build_answer_request("Câu hỏi", [], [], [])
    payload = json.loads(request.prompt.split("\n\n", 1)[1])
    assert "rules" not in payload
    assert "Moi con so phai la placeholder" not in request.prompt


def test_the_data_half_says_it_is_data() -> None:
    request = build_answer_request("Câu hỏi", [], [], [])
    assert request.prompt.startswith("DU LIEU DE PHAN TICH")


def test_user_written_context_still_travels_as_data() -> None:
    """Tach ra khong duoc lam mat o Boi canh - no van phai den duoc model."""
    request = build_answer_request("Câu hỏi", [], [], [], context="Duration = thời gian giữ vốn")
    assert "thời gian giữ vốn" in request.prompt


def test_a_retry_rule_lands_with_the_rules_not_with_the_data() -> None:
    from analysis_system.agents.feedback import RETRY_RULE
    from analysis_system.contracts.base import RetryFeedback

    feedback = RetryFeedback(attempt=1, max_attempts=3, rejected_because=("go so truc tiep",))
    request = build_answer_request("Câu hỏi", [], [], [], feedback)
    assert RETRY_RULE in request.system
    assert "go so truc tiep" in request.prompt
