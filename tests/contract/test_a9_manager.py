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

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from analysis_system.agents.a9_manager import ManagerAgent, build_answer_request
from analysis_system.contracts.agents import (
    AnalysisResult,
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
        params=params or {"question": "diem thi phu thuoc gi"},
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
            claim_template="Gio hoc di kem voi diem thi, he so {score.corr.with.hours}.",
            metric_keys=("score.corr.with.hours",),
            evidence_ref="mart://x.parquet",
            confidence=0.9,
        )
    ],
    summary="mot luan diem",
)


def answer_with(
    tmp_path: Path, proposal: FindingProposal, *, declined: tuple[str, ...] = ()
) -> tuple[ManagerAnswer | None, Any, Any]:
    """Run A9 and hand back the answer it wrote, if it wrote one."""
    settings = settings_in(tmp_path)
    scope = token()
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
    assert "metric_key" in request.prompt


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
