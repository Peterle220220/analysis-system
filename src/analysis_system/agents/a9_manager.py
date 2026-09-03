"""A9: the Manager reads what its team found and answers the question.

Every other agent looks at data and reports. Nothing read those reports together
and said *so here is the answer* - so a question needing the miner and the
analyst got two sets of findings and no conclusion, and the person asking had to
be the one to join them up.

This is that step. It is written as an agent, with a manifest and a scope, for
the same reason everything else is: the moment it produces conclusions it becomes
the place where invention is most likely, and exempting the Manager from the
rules that hold everyone else would put the least-checked component exactly where
the most damage is done.

Three things it is held to, none of them new:

* **Numbers stay behind placeholders.** The rendering, the digit check and the
  rejection all come from `findings.py` unchanged - the same machinery A7 has
  used since Phase 2. A claim that types its own figure is dropped, not fixed.
* **A claim rests on something.** Every claim must cite metric keys that exist.
  One that cites nothing is an opinion, however well it reads.
* **What was *not* established is put in front of it.** Every skill's refusals
  arrive with its findings, because a conclusion drawn over a hole nobody
  mentioned is the failure this whole design is arranged against.

And where a claim's shape allows one, a chart is drawn from the very metrics it
cites - so the picture in the report is evidence for that sentence rather than
decoration near it.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar, Final

import pandas as pd

from analysis_system.agents.base import BaseAgent, ManifestDir, all_of, first_of
from analysis_system.agents.feedback import RETRY_RULE, as_prompt_fields, feedback_from
from analysis_system.contracts.agents import (
    AnalysisResult,
    ClaimEvidence,
    Finding,
    FindingProposal,
    ManagerAnswer,
    MetricValue,
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
from analysis_system.services.answer_shape import check as check_shape
from analysis_system.services.chart_choice import suggestion_for
from analysis_system.services.charts import ChartError, draw
from analysis_system.services.findings import render_all
from analysis_system.services.llm import LlmClient, LlmRequest
from analysis_system.services.prompts import load_prompt
from analysis_system.services.relevance import (
    DEFAULT_THRESHOLD,
    SemanticScorer,
    judge,
)
from analysis_system.services.scoped_storage import ScopedStorage
from analysis_system.settings import Settings

ARTIFACT_PREFIX: Final[str] = "artifacts://"
QUESTION_PARAM: Final[str] = "question"
MAX_CLAIMS: Final[int] = 8
# How close a claim has to be to the question to stay in the answer.
# Measured, not picked: on sixteen cases from real runs this is the
# highest line that still throws away nothing relevant.
RELEVANCE_FLOOR: Final[float] = DEFAULT_THRESHOLD

PLAN_PROBLEM_CODES: Final[frozenset[str]] = frozenset({"NO_REPORTS"})


def build_answer_request(
    question: str,
    reports: list[dict[str, Any]],
    metrics_view: list[dict[str, Any]],
    unanswered: list[str],
    feedback: RetryFeedback | None = None,
) -> LlmRequest:
    """Ask for an argument that answers the question, built only from what was found.

    The reports are what each skill said. `unanswered` is what none of them could
    establish, and it is not an afterthought: a conclusion that quietly steps over
    a gap reads exactly like one that does not.
    """
    payload: dict[str, Any] = {
        "question": question,
        "reports": reports,
        "metrics": metrics_view,
        # What the team could not establish. Put beside the findings rather than
        # below them, because an argument built over a gap nobody mentioned is
        # the failure this design is arranged against.
        "khong_xac_lap_duoc": unanswered,
        "max_claims": MAX_CLAIMS,
        **as_prompt_fields(feedback),
        "rules": [
            "Moi con so phai la placeholder dang {ten_chi_so}, lay tu danh sach metrics.",
            "TUYET DOI khong go con so truc tiep. Cau co chu so se bi loai bo.",
            "Moi luan diem phai dan it nhat mot metric_key co that. Luan diem khong dan "
            "duoc gi la mot y kien, du no doc hay den may - se bi loai.",
            "Tra loi DUNG cau hoi duoc hoi. Khong liet ke moi thu tim duoc.",
            "Neu phan 'khong_xac_lap_duoc' cham toi cau hoi, PHAI noi ro dieu do thay vi "
            "ket luan chong len cho trong.",
            "Khong suy dien nhan qua. Chi so do moi lien he thi viet 'di kem voi', "
            "'tuong quan voi' - khong viet 'lam cho', 'khien', 'dan den'.",
            "Khong de xuat hanh dong. Ban trinh bay cai da do duoc; quyet dinh lam gi "
            "la viec cua nguoi doc.",
            *([RETRY_RULE] if feedback else []),
        ],
    }
    return LlmRequest(
        purpose="a9_manager_answer",
        system=load_prompt("a9_manager_answer"),
        prompt=json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        schema=FindingProposal,
    )


class ManagerAgent(BaseAgent):
    """Reads every skill's report and answers the question that was asked."""

    agent_id: ClassVar[str] = "a9_manager"

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
        """Collect the reports, write the argument, and back each claim with a chart."""
        metrics, reports, unanswered, source, cited = self._collect(request, files)
        if not reports:
            return self._failed(
                request,
                "NO_REPORTS",
                "A9 can ket qua cua it nhat mot agent khac de tong hop.",
            )
        if self._llm is None:
            return self._failed(request, "NO_MODEL", "A9 can mot model de tong hop.")

        question = str(request.scope.params.get(QUESTION_PARAM) or request.instruction)
        answer = self._llm.complete(
            build_answer_request(
                question,
                reports,
                [
                    {"key": metric.key, "value": metric.value, "unit": metric.unit}
                    for metric in sorted(metrics.values(), key=lambda item: item.key)
                ],
                unanswered,
                feedback_from(request.scope.params),
            )
        )
        if not isinstance(answer.data, FindingProposal):
            return self._failed(request, "BAD_ANSWER", "Model khong tra ve dung FindingProposal.")

        # The same rendering, the same digit check, the same rejections A7 has
        # used since Phase 2. Building a second one for the Manager would be
        # building a second place for a number to be invented.
        claims = [
            Finding(
                claim_template=finding.claim_template,
                metric_keys=finding.metric_keys,
                evidence_ref=finding.evidence_ref or source,
                confidence=finding.confidence,
                dimension=finding.dimension,
            )
            for finding in answer.data.findings
        ]
        rendered, rejected = render_all(claims, metrics, "")

        # True is not the same as relevant. A claim about the share of
        # missing values is correct, cited, and not an answer to a question about
        # what carries the outcome.
        rendered, off_topic = self._on_topic(question, rendered)
        rejected.extend(off_topic)

        supported: list[ClaimEvidence] = []
        frame = self._table(request, files, cited)
        for index, claim in enumerate(rendered):
            keys = tuple(sorted(claim.metrics))
            if not keys:
                rejected.append(
                    f"claim[{index}]: khong dan chi so nao - day la mot y kien, khong phai "
                    "mot ket luan rut ra tu du lieu."
                )
                continue
            chart_ref, why = self._chart(keys, metrics, frame, request, files, index)
            supported.append(
                ClaimEvidence(
                    claim=claim.claim,
                    metric_keys=keys,
                    evidence_ref=claim.evidence_ref,
                    chart_ref=chart_ref,
                    chart_reason=why,
                )
            )

        if not supported:
            return self._failed(
                request,
                "NO_SUPPORTED_CLAIM",
                # Saying what was refused, and how much there was to work with.
                # "No claim passed" with nothing after it is a wall: it reads the
                # same whether the model wrote nonsense or was handed nothing.
                (
                    f"Khong luan diem nao qua duoc kiem tra "
                    f"({len(claims)} luan diem, {len(metrics)} chi so co san). "
                    + ("; ".join(rejected) if rejected else "Model khong dua ra luan diem nao.")
                ),
                retryable=True,
                payload=answer.data.model_dump(mode="json"),
            )

        # True, relevant, and still not what was asked for. A question about
        # causes answered with three averages has produced real figures about
        # the right subject that say nothing about what moves what. Said plainly
        # here rather than left for the reader to notice.
        shape = check_shape(question, [key for claim in supported for key in claim.metric_keys])
        if not shape.met:
            unanswered.insert(0, shape.shortfall)

        result = ManagerAnswer(
            question=question,
            claims=tuple(supported),
            unanswered=tuple(unanswered),
            rejected=tuple(rejected),
        )
        target = f"{ARTIFACT_PREFIX}{request.scope.run_id}_answer.json"
        written = files.save_text(result.model_dump_json(indent=2), target)

        return TaskResult(
            task_id=request.scope.task_id,
            agent_id=self.agent_id,
            status="OK",
            output_refs=(written,),
            declined=tuple(unanswered),
            metrics={
                "claims": float(len(supported)),
                "claims_rejected": float(len(rejected)),
                "charts": float(sum(1 for claim in supported if claim.chart_ref)),
                "metrics_available": float(len(metrics)),
                # 1 when the answer is the kind of thing the question asked for.
                # Worth a number rather than only a sentence: it is the one
                # figure that says whether asking was any use.
                "answers_the_question": float(shape.met),
            },
            payload=result.model_dump(mode="json"),
        )

    def _collect(
        self, request: TaskRequest, files: ScopedStorage
    ) -> tuple[dict[str, MetricValue], list[dict[str, Any]], list[str], str, list[str]]:
        """Everything the team measured, said, would not say, and worked from.

        Recognised by shape rather than by which agent produced it, so a skill
        added later reports upward without this having to learn its name.
        """
        metrics: dict[str, MetricValue] = {}
        reports: list[dict[str, Any]] = []
        unanswered: list[str] = []
        source = ""
        # The tables the reports were computed from. Following these is how a
        # chart gets drawn when the plan handed over artifacts and no data.
        cited: list[str] = []

        for ref in all_of(request.input_refs, "json"):
            text = files.load_text(ref.path)
            report = self._read_analysis(ref, text) or self._read_process_map(ref, text)
            if report is None:
                continue
            found, said, declined = report
            metrics.update(found)
            reports.append(said)
            unanswered.extend(declined)
            source = source or ref.path
            origin = said.get("nguon_du_lieu")
            if isinstance(origin, str) and origin and origin not in cited:
                cited.append(origin)
        return metrics, reports, unanswered, source, cited

    def _read_analysis(
        self, ref: DataRef, text: str
    ) -> tuple[dict[str, MetricValue], dict[str, Any], list[str]] | None:
        """A7's findings, if that is what this artifact holds."""
        try:
            found = AnalysisResult.model_validate_json(text)
        except ValueError:
            return None
        return (
            {metric.key: metric for metric in found.metrics},
            {
                "tu": "phan tich",
                "nguon": ref.path,
                "nguon_du_lieu": found.source,
                "cau_hoi": found.question,
                "ket_luan": [claim.claim for claim in found.findings],
            },
            list(found.rejected),
        )

    def _read_process_map(
        self, ref: DataRef, text: str
    ) -> tuple[dict[str, MetricValue], dict[str, Any], list[str]] | None:
        """A6's process map, if that is what this artifact holds."""
        try:
            found = ProcessMap.model_validate_json(text)
        except ValueError:
            return None
        said: dict[str, Any] = {
            "tu": "khai thac quy trinh",
            "nguon": ref.path,
            "nguon_du_lieu": found.source,
            "duong_di": [
                {"ten": variant.label or f"luong {variant.rank}", "buoc": variant.path}
                for variant in found.variants
            ],
            "cho_lau_nhat": [
                {"tu": step.source_activity, "den": step.target_activity}
                for step in found.handovers
            ],
            "so_sanh_duoc_theo": [attribute.name for attribute in found.attributes],
            "nhan_xet": list(found.concerns),
        }
        if found.gap is not None:
            said["khoang_cach"] = {
                "theo": found.gap.attribute,
                "giua": [found.gap.focus, found.gap.other],
                "cac_buoc": [
                    {"tu": step.source_activity, "den": step.target_activity}
                    for step in found.gap.steps
                ],
            }
        return ({metric.key: metric for metric in found.metrics}, said, list(found.refused))

    def _on_topic(
        self, question: str, claims: list[RenderedFinding]
    ) -> tuple[list[RenderedFinding], list[str]]:
        """Keep the claims that are about the question, and say what was set aside.

        Scored by meaning rather than by shared words. Measured on sixteen cases
        from real runs: comparing words got nine right and discarded seven real
        answers, because "the print-and-send step accounts for a third of the
        gap" and "why is postal slower" have no words in common at all.

        When no scorer can be built, nothing is filtered and the answer says so.
        Filtering with something that discards half the real answers would be
        worse than not filtering.
        """
        if not claims:
            return claims, []
        try:
            verdicts = judge(
                question, [claim.claim for claim in claims], SemanticScorer(), RELEVANCE_FLOOR
            )
        except Exception as error:  # noqa: BLE001 - an absent model is not a bad answer
            return claims, [
                f"khong kiem duoc do lien quan voi cau hoi ({error}) - moi luan diem "
                "duoc giu nguyen, ke ca cai co the lac de."
            ]

        kept = [claim for claim, verdict in zip(claims, verdicts, strict=True) if verdict.kept]
        notes = [
            (
                f"loai vi khong tra loi cau hoi (do lien quan {verdict.score:.2f} < "
                f"{RELEVANCE_FLOOR}): {verdict.claim[:70]}"
            )
            if verdict.checked
            # Kept, not passed. Saying nothing here would let an unjudged claim
            # read exactly like one that cleared the line.
            else (
                "GIU nhung CHUA kiem duoc do lien quan (cau hoi va luan diem khac "
                f"nhau ve dau tieng Viet): {verdict.claim[:70]}"
            )
            for verdict in verdicts
            if not verdict.kept or not verdict.checked
        ]
        return kept, notes

    def _table(
        self, request: TaskRequest, files: ScopedStorage, cited: list[str]
    ) -> pd.DataFrame | None:
        """The table behind the numbers.

        A scatter plot and a box plot need the rows, not the summaries, and those
        are exactly the shapes that show what a coefficient cannot.

        Handed over directly when the plan does that. Otherwise found by
        following the citation each report already carries - the table it was
        computed from, which is the same reference that makes its findings
        traceable. Guessing is not among the options: a citation that cannot be
        read means no chart, and the claim keeps its numbers and goes without.
        """
        ref = first_of(request.input_refs, "parquet")
        if ref is not None:
            return files.load_parquet(ref.path)
        for path in cited:
            if not path.endswith(".parquet"):
                continue
            try:
                return files.load_parquet(path)
            except Exception:  # noqa: BLE001 - an unreadable citation is simply no table
                continue
        return None

    def _chart(
        self,
        metric_keys: tuple[str, ...],
        metrics: dict[str, MetricValue],
        frame: pd.DataFrame | None,
        request: TaskRequest,
        files: ScopedStorage,
        index: int,
    ) -> tuple[str, str]:
        """A chart drawn from the very metrics this claim cites, if one suits it.

        Not every claim has a picture worth drawing. "Two thousand events broke
        the rule" is one number, and a bar chart of one bar shows nothing while
        looking as though it shows something. Those claims keep their citation,
        which is what makes them checkable, and go without a chart.
        """
        suggestion = suggestion_for(metric_keys, metrics, frame)
        if suggestion is None:
            return "", ""
        try:
            png = draw(suggestion.spec, metrics=metrics, frame=frame)
        except ChartError:
            return "", ""
        target = f"{ARTIFACT_PREFIX}{request.scope.run_id}_claim{index + 1}.png"
        written = files.save_bytes(png, target)
        return written.path, suggestion.reason

    def _failed(
        self,
        request: TaskRequest,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        payload: dict[str, Any] | None = None,
    ) -> TaskResult:
        """Report an honest failure, with nothing written."""
        return TaskResult(
            task_id=request.scope.task_id,
            agent_id=self.agent_id,
            status="FAILED",
            payload=payload or {},
            error=ErrorDetail(
                code=code,
                message=message,
                retryable=retryable,
                replannable=code in PLAN_PROBLEM_CODES,
            ),
        )
