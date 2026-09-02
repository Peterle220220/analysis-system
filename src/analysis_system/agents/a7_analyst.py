"""A7 Analyst: draw conclusions from figures the code computed.

The division is the same as everywhere else, taken to its strictest form here
because this is where a wrong number does the most damage. Code computes every
value. The model writes sentences with placeholders where numbers go. Code
substitutes them.

A sentence containing a digit the model typed itself is rejected, not corrected.
Correcting it would mean deciding what it meant to say.

Every finding carries an evidence_ref pointing back at the table it came from,
which is what criterion S4 asks for: a conclusion nobody can trace is a
conclusion nobody can check.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar, Final

import pandas as pd

from analysis_system.agents.a6_process_miner import MAP_SUFFIX
from analysis_system.agents.base import BaseAgent, ManifestDir, all_of
from analysis_system.agents.feedback import RETRY_RULE, as_prompt_fields, feedback_from
from analysis_system.contracts.agents import (
    AnalysisResult,
    FindingProposal,
    ProcessMap,
    RenderedFinding,
)
from analysis_system.contracts.base import (
    DataRef,
    ErrorDetail,
    RetryFeedback,
    TaskRequest,
    TaskResult,
)
from analysis_system.services.findings import render_all
from analysis_system.services.llm import LlmClient, LlmRequest
from analysis_system.services.metrics import compute_metrics, metric_catalogue
from analysis_system.services.prompts import load_prompt
from analysis_system.services.scoped_storage import ScopedStorage
from analysis_system.services.statistics import (
    StatisticsError,
    StatisticsSpec,
    compute_statistics,
    suggest_spec,
)
from analysis_system.settings import Settings

ARTIFACT_PREFIX: Final[str] = "artifacts://"
QUESTION_PARAM: Final[str] = "question"
DIMENSIONS_PARAM: Final[str] = "dimensions"
MEASURES_PARAM: Final[str] = "measures"
TESTS_PARAM: Final[str] = "tests"
MAX_FINDINGS: Final[int] = 10


def build_analysis_request(
    metrics_view: list[dict[str, Any]],
    question: str,
    max_findings: int,
    feedback: RetryFeedback | None = None,
    source: str = "",
    process: list[dict[str, Any]] | None = None,
) -> LlmRequest:
    """Build the one question A7 asks.

    The model is given the metric set and the business question. It is not given
    the table: every number it may use is already in front of it, named.

    On a retry the previous answer and the reasons it was rejected go in too.
    Asking the identical question again and hoping for a different answer is not
    a strategy.
    """
    payload: dict[str, Any] = {
        "question": question,
        # The table every metric was measured from. Demanding a citation while
        # withholding what to cite leaves the model guessing, and it guessed
        # mart://frame.parquet - twice, on two different runs.
        "source_table": source,
        "metrics": metrics_view,
        # The names behind the process metric keys. A model cannot say which
        # path is the common one without being told what the path is, and the
        # path is text - the numbers stay behind their keys.
        "process_paths": process or [],
        "max_findings": max_findings,
        **as_prompt_fields(feedback),
        "rules": [
            "Moi con so phai la placeholder dang {ten_chi_so}, lay tu danh sach metrics.",
            "TUYET DOI khong go con so truc tiep vao cau. Cau co chu so se bi loai bo.",
            "Moi finding phai co evidence_ref tro toi bang du lieu nguon.",
            "Khong ket luan dieu ma cac chi so tren khong cho thay.",
            "KHONG viet don vi sau placeholder (khong viet '%', 'dong', 'EUR'...). "
            "He thong tu chen don vi, ban viet them se thanh '40.24 %%'.",
            "evidence_ref phai BANG DUNG gia tri cua 'source_table' o tren. "
            "Khong duoc tu dat ten file khac.",
            "Chi so co '.corr.', '.ttest.', '.anova.' chi do MOI LIEN HE, khong do "
            "nhan qua. TUYET DOI khong viet 'lam tang', 'khien', 'dan den', "
            "'anh huong den'. Viet 'di kem voi', 'tuong quan voi', 'cao hon o nhom...'.",
            "p_value nho khong co nghia la khac biet lon. Neu noi ve khac biet giua "
            "cac nhom thi nen dan ca effect_size hoac eta_sq.",
            "Chi so bat dau bang 'process.' do QUY TRINH da chay ra sao. "
            "'.median_hours' la thoi gian cho, don vi gio - he thong tu chen don vi. "
            "Muon noi ve mot duong di thi dung ten trong 'process_paths', dung go so buoc.",
            "Chi so '.coef.' la he so hoi quy: gia tri thay doi bao nhieu khi bien do "
            "tang mot don vi VA CAC BIEN KHAC GIU NGUYEN. Neu dan he so thi phai noi ro "
            "dieu kien 'giu nguyen cac yeu to khac'.",
            *([RETRY_RULE] if feedback else []),
        ],
    }
    return LlmRequest(
        purpose="a7_analyst_findings",
        system=load_prompt("a7_analyst_findings"),
        prompt=json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        schema=FindingProposal,
    )


PLAN_PROBLEM_CODES: Final[frozenset[str]] = frozenset({"NO_INPUT"})


class AnalystAgent(BaseAgent):
    """Turns a mart table into findings that can be traced back to it."""

    agent_id: ClassVar[str] = "a7_analyst"

    def __init__(
        self,
        settings: Settings,
        manifest_dir: ManifestDir = None,
        *,
        llm: LlmClient | None = None,
    ) -> None:
        """Bind an optional model client on top of the usual agent setup."""
        super().__init__(settings, manifest_dir)
        self._llm = llm

    def execute(self, request: TaskRequest, files: ScopedStorage) -> TaskResult:
        """Compute the metrics, ask for findings, and render the ones that hold up."""
        if not request.input_refs:
            return self._failed(request, "NO_INPUT", "A7 can mot bang mart de phan tich.")

        source = self._table(request)
        if source is None:
            return self._failed(
                request,
                "NO_INPUT",
                "A7 can mot bang mart de phan tich - cac input deu khong phai bang.",
            )
        frame = files.load_parquet(source.path)
        metrics = self._metrics(frame, request.scope.params)
        # Anything A6 measured about the process joins the metric set as-is.
        # These are metrics like any other - named, computed by code, with a
        # unit - so nothing about how a claim is checked has to change.
        process, process_context = self._process_map(request, files)
        metrics.update(process)
        try:
            inferred, declined = self._statistics(frame, request.scope.params)
        except StatisticsError as error:
            return self._failed(request, "BAD_TESTS", str(error))
        metrics.update(inferred)

        if self._llm is None:
            return self._failed(
                request, "NO_MODEL", "A7 can mot model de dien giai. Chi so da tinh xong."
            )

        question = str(request.scope.params.get(QUESTION_PARAM) or request.instruction)
        answer = self._llm.complete(
            build_analysis_request(
                metric_catalogue(metrics),
                question,
                MAX_FINDINGS,
                feedback_from(request.scope.params),
                source.path,
                process_context,
            )
        )
        if not isinstance(answer.data, FindingProposal):
            return self._failed(request, "BAD_PROPOSAL", "Model khong tra ve dung FindingProposal.")

        rendered, rejected = render_all(list(answer.data.findings), metrics, source.content_hash)

        # A claim nobody can trace back is not evidence-backed, whatever its
        # numbers say. Dropped, not repaired: inventing the right path would be
        # deciding what the model meant to cite.
        traceable: list[RenderedFinding] = []
        for index, finding in enumerate(rendered):
            if files.citation_exists(finding.evidence_ref):
                traceable.append(finding)
            else:
                rejected.append(
                    f"finding[{index}]: evidence_ref {finding.evidence_ref!r} "
                    "khong tro toi file nao doc duoc"
                )
        rendered = traceable

        if not rendered:
            # Worth another attempt: the model can write better sentences when
            # told which ones were thrown out and why. A different plan cannot.
            return self._failed(
                request,
                "NO_VALID_FINDING",
                "Khong finding nao qua duoc kiem tra. " + "; ".join(rejected),
                retryable=True,
                payload=answer.data.model_dump(mode="json"),
            )

        result = AnalysisResult(
            source=source.path,
            question=question,
            findings=tuple(rendered),
            metrics_available=len(metrics),
            # Tests that could not honestly be run are reported beside the
            # findings, never dropped: an absent number and a number nobody was
            # told about look identical from the outside.
            rejected=(*rejected, *declined),
        )
        target = f"{ARTIFACT_PREFIX}{request.scope.run_id}_findings.json"
        written = files.save_text(result.model_dump_json(indent=2), target)

        return TaskResult(
            task_id=request.scope.task_id,
            agent_id=self.agent_id,
            status="OK",
            output_refs=(written,),
            metrics={
                "findings": float(len(rendered)),
                "findings_rejected": float(len(rejected)),
                "metrics_computed": float(len(metrics)),
            },
            payload=result.model_dump(mode="json"),
            evidence=tuple(finding.as_evidence() for finding in rendered),
        )

    def _table(self, request: TaskRequest) -> DataRef | None:
        """The table to analyse, chosen by what it is rather than where it sits.

        Position was never a good way to name an input, and it stopped working
        the moment a process map could arrive alongside the table: a plan that
        listed them the other way round had this agent reading JSON as Parquet.
        The resulting error pointed at the storage layer, which is nowhere near
        where the mistake was.
        """
        for ref in all_of(request.input_refs, "parquet"):
            return ref
        return None

    def _process_map(
        self, request: TaskRequest, files: ScopedStorage
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Metrics and path names from a process map, when one was handed over.

        Recognised by what it is rather than by position: a plan may put the map
        first or second among the inputs, and depending on the order would be a
        rule nobody writing a plan would know about.
        """
        for ref in request.input_refs:
            if ref.format != "json" or not ref.path.endswith(MAP_SUFFIX):
                continue
            found = ProcessMap.model_validate_json(files.load_text(ref.path))
            context: list[dict[str, Any]] = [
                {
                    "path": variant.path,
                    "label": variant.label,
                    "steps": variant.steps,
                    "share_key": variant.share_key,
                    "cases_key": variant.cases_key,
                }
                for variant in found.variants
            ]
            context.extend(
                {
                    "from": handover.source_activity,
                    "to": handover.target_activity,
                    "median_hours_key": handover.median_hours_key,
                    "observations_key": handover.observations_key,
                }
                for handover in found.handovers
            )
            return {metric.key: metric for metric in found.metrics}, context
        return {}, []

    def _metrics(self, frame: pd.DataFrame, params: dict[str, Any]) -> dict[str, Any]:
        """Compute every value the analysis is allowed to quote."""
        dimensions = tuple(str(name) for name in (params.get(DIMENSIONS_PARAM) or []))
        measures = tuple(str(name) for name in (params.get(MEASURES_PARAM) or []))
        return compute_metrics(frame, dimensions=dimensions, measures=measures)

    def _statistics(
        self, frame: pd.DataFrame, params: dict[str, Any]
    ) -> tuple[dict[str, Any], list[str]]:
        """Run the statistical tests the task declared, if it declared any.

        Declared rather than guessed: running a test nobody asked for produces a
        number somebody will quote.
        """
        raw = params.get(TESTS_PARAM)
        if raw is not None:
            return compute_statistics(frame, StatisticsSpec.from_params(raw))

        # Nobody said which tests to run. Deriving them from the table beats
        # running none: requiring the pair to be named up front asks the person
        # to name the relationship they already suspect, and the answer they
        # were looking for is usually the one they did not think to ask about.
        spec, notes = suggest_spec(
            frame,
            dimensions=[str(name) for name in (params.get(DIMENSIONS_PARAM) or [])],
            measures=[str(name) for name in (params.get(MEASURES_PARAM) or [])],
        )
        metrics, declined = compute_statistics(frame, spec)
        # The choices travel with the results. A test nobody asked for is fine;
        # a test nobody was told about is not.
        return metrics, [*notes, *declined]

    def _failed(
        self,
        request: TaskRequest,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        payload: dict[str, Any] | None = None,
    ) -> TaskResult:
        """Report an honest failure, with nothing written.

        The rejected answer travels in the payload so the next attempt can be
        shown what was wrong with it. Nothing downstream reads it: only the
        Manager, and only to build the next question.
        """
        return TaskResult(
            task_id=request.scope.task_id,
            agent_id=self.agent_id,
            status="FAILED",
            payload=payload or {},
            error=ErrorDetail(
                code=code,
                message=message,
                retryable=retryable,
                # Being handed the wrong input is the one failure a different
                # plan could actually fix.
                replannable=code in PLAN_PROBLEM_CODES,
            ),
        )
