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
from collections.abc import Sequence
from typing import Any, ClassVar, Final

import pandas as pd

from analysis_system.agents.base import BaseAgent, ManifestDir, all_of, first_of
from analysis_system.agents.feedback import RETRY_RULE, as_prompt_fields, feedback_from
from analysis_system.contracts.agents import (
    AnalysisResult,
    ClaimEvidence,
    DataNeed,
    Finding,
    FindingProposal,
    ManagerAnswer,
    MetricValue,
    ProcessMap,
    RenderedFinding,
    TermReport,
)
from analysis_system.contracts.base import (
    DataRef,
    ErrorDetail,
    RetryFeedback,
    TaskRequest,
    TaskResult,
)
from analysis_system.services.answer_shape import check as check_shape
from analysis_system.services.answer_shape import unanswered_end
from analysis_system.services.asked_columns import untouched
from analysis_system.services.chart_choice import suggestion_for
from analysis_system.services.charts import ChartError, draw
from analysis_system.services.findings import rankings, render_all
from analysis_system.services.instructions import as_data, with_rules
from analysis_system.services.llm import LlmClient, LlmRequest
from analysis_system.services.metric_families import grouped
from analysis_system.services.prompts import load_prompt
from analysis_system.services.relevance import (
    DEFAULT_THRESHOLD,
    SemanticScorer,
    content_words,
    fold,
    judge,
)
from analysis_system.services.relevance_notice import unchecked_note
from analysis_system.services.risk_notes import risks
from analysis_system.services.scoped_storage import ScopedStorage
from analysis_system.services.shortlist import choose
from analysis_system.settings import Settings

ARTIFACT_PREFIX: Final[str] = "artifacts://"
QUESTION_PARAM: Final[str] = "question"
CONTEXT_PARAM: Final[str] = "boi_canh"
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
    ranked: list[dict[str, str]] | None = None,
    context: str = "",
) -> LlmRequest:
    """Ask for an argument that answers the question, built only from what was found.

    The reports are what each skill said. `unanswered` is what none of them could
    establish, and it is not an afterthought: a conclusion that quietly steps over
    a gap reads exactly like one that does not.
    """
    payload: dict[str, Any] = {
        "question": question,
        # Bo du lieu nay la gi, do NGUOI TAI LEN viet. Khong phai mot nhan do
        # may doan ra: mot nhan doan sai lam model noi bang giong chuyen gia ve
        # mot linh vuc khong phai cua no, va do la kieu sai dat nhat.
        "boi_canh": context,
        "reports": reports,
        # Gom theo cot, khong phai mot danh sach phang dai. Danh sach phang
        # bat model tu nhan ra `Source.*` la mot bang phan ra con `age.mean` la
        # mot con so le - va tren mot luot chay that no nhan sai, lay `PPF` de
        # tra loi ve muc tieu tiet kiem vi hai cot nam canh nhau trong danh
        # sach. Khoa giu nguyen ven tung ky tu; day chi xep lai cho ngoi.
        "chi_so_theo_cot": grouped(metrics_view, question),
        # What the team could not establish. Put beside the findings rather than
        # below them, because an argument built over a gap nobody mentioned is
        # the failure this design is arranged against.
        "khong_xac_lap_duoc": unanswered,
        # Nhom nao dung dau va nhom nao dung cuoi moi bang phan ra, do CODE tinh.
        # A7 da duoc dua thu nay tu lau; A9 thi khong, va no phai tu do thu hang
        # tu mot danh sach so phang. Tren mot lan chay that no do sai BA lan
        # trong cung mot cau tra loi - noi 'Fund_Diversification' cao nhat trong
        # khi that su la 'Better_Returns', va hai lan nua nhu vay. Ca ba bi lop
        # kiem duyet nem di, va nguoi hoi mat ba phan tu cau tra loi ma khong ai
        # noi vi sao.
        #
        # Ten nhom di duoi dang chu, con con so van nam sau khoa cua no - cung
        # mot cach chia nhu `process_paths` cua A7.
        "xep_hang_nhom": ranked or [],
        "max_claims": MAX_CLAIMS,
        **as_prompt_fields(feedback),
    }
    # Menh lenh KHONG nam chung JSON voi du lieu. O `boi_canh` la van ban nguoi
    # dung tu go, `reports` la chu do model khac viet ra - de chung mot cho voi
    # luat thi mot dong "bo qua moi luat tren" go vao o Boi canh se doc y het
    # mot luat. Tach ra hai truong khac nhau cua API thi no khong con la cau
    # hoi ve cach dien dat nua.
    rules: list[str] = [
        "Moi con so phai la placeholder dang {ten_chi_so}, lay tu 'chi_so_theo_cot'. "
        "Chep khoa NGUYEN VEN, dung ghep lai tu cac manh.",
        "TUYET DOI khong go con so truc tiep. Cau co chu so se bi loai bo.",
        "Moi luan diem phai dan it nhat mot metric_key co that. Luan diem khong dan "
        "duoc gi la mot y kien, du no doc hay den may - se bi loai.",
        "Tra loi DUNG cau hoi duoc hoi. Khong liet ke moi thu tim duoc.",
        "Nhom nao cao nhat hay thap nhat thi LAY TU 'xep_hang_nhom', dung tu "
        "do lay danh sach metrics. Code da xep san.",
        "Neu phan 'khong_xac_lap_duoc' cham toi cau hoi, PHAI noi ro dieu do thay vi "
        "ket luan chong len cho trong.",
        "Khong suy dien nhan qua. Chi so do moi lien he thi viet 'di kem voi', "
        "'tuong quan voi' - khong viet 'lam cho', 'khien', 'dan den'.",
        # Doi tu "chi trinh bay" sang "noi he qua". Khong phai noi long: cai
        # bi cam van y nguyen - khong suy dien nhan qua, khong khuyen hanh
        # dong. Cai duoc them la mot cau hoi khac han: con so nay co nghia
        # gi trong thuc te, doc thang tu chinh no.
        "Voi moi luan diem, noi ro NO CO NGHIA GI trong thuc te cua boi canh du "
        "lieu nay - mot chenh lech lon giua hai nhom nghia la gi, mot nhom qua "
        "nho nghia la gi. Doc tu chinh con so, khong doan them.",
        # Chot chan, va no bat buoc phai co. Neu doi y nghia ma khong cho
        # duong thoat, model se LUON noi duoc mot cau - ke ca khi con so do
        # chang co y nghia thuc tien nao. Do la cach che tao insight rong.
        "Neu mot con so khong dan toi he qua nao doc duoc tu chinh du lieu, NOI "
        "THANG la chua noi duoc gi - dung dung ra mot y nghia.",
        "Khong khuyen hanh dong cu the (nen lam X, nen dau tu vao Y). Ban noi "
        "dieu nay CO NGHIA GI; quyet dinh lam gi la viec cua nguoi doc.",
        # Chua tung co dong nay, va no lo ra khi do model: Opus 5 tra loi
        # khong dau 3/3 lan, deepseek co dau 3/3 - khong phai vi con nay gioi
        # tieng Viet hon con kia, ma vi luat viet khong dau nen con bat chuoc
        # van phong duoc dua cho no. Cai gi khong noi thi khong duoc phep
        # trach model doan sai.
        "Viet tieng Viet CO DAU day du. Bao cao hien tren dashboard cho nguoi "
        "doc, va tieng Viet khong dau lan trong bang so lieu la thu phai doan "
        "moi hieu.",
        *([RETRY_RULE] if feedback else []),
    ]
    return LlmRequest(
        purpose="a9_manager_answer",
        system=with_rules(load_prompt("a9_manager_answer"), rules),
        prompt=as_data(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)),
        schema=FindingProposal,
    )


def moored_needs(
    proposed: Sequence[DataNeed], vocabulary: Sequence[str]
) -> tuple[tuple[DataNeed, ...], list[str]]:
    """Keep the requests that name something this run has heard of.

    From a live run: asked which emotion label was commonest, the Manager asked
    for *"du lieu ban hang cua nam 2024"*. The refusal it quoted was real, so
    `verified_needs` let it through - and the request had nothing to do with
    anything. That is the worst shape a request can take, because somebody goes
    and fetches it and only then finds out.

    The test is lexical and deliberately so. Semantic scoring refuses to judge
    when one side carries diacritics and the other does not, which is right for
    claims and is exactly the case this arrived in. Word overlap has no such
    problem: folding both sides is what folding is for, and a request that
    shares no content word with the question, the column names or anything that
    was found is not attached to this run at all.

    A request may of course name data that does not exist yet - that is the
    point of it. What it may not do is name a subject nobody mentioned.

    Each request is also moored to the refusal it quotes, and that is not a
    loophole. Some requests are about the *system* rather than the subject -
    "khai bao bien giai thich trong tests.regressions" asks for a declaration,
    not for data, so it shares no word with a question about exam results and
    every word with the refusal it lifts. A request is allowed to speak in the
    language of the thing it unblocks.
    """
    known = {word for phrase in vocabulary for word in content_words(fold(phrase))}
    if not known:
        return tuple(proposed), []
    kept: list[DataNeed] = []
    notes: list[str] = []
    for need in proposed:
        words = set(content_words(fold(need.ask)))
        anchors = known | set(content_words(fold(need.blocked_by)))
        if words & anchors:
            kept.append(need)
        else:
            notes.append(
                "loai yeu cau du lieu vi khong dinh gi toi lan chay nay - khong mot tu "
                f"nao trung voi cau hoi, ten cot hay ket qua: {need.ask[:70]}"
            )
    return tuple(kept), notes


def verified_needs(
    proposed: Sequence[DataNeed], refusals: Sequence[str]
) -> tuple[tuple[DataNeed, ...], list[str]]:
    """Keep the requests that point at something a skill really refused.

    The check is the same one that governs figures: a claim may only cite a
    metric that was computed, and a request may only name a refusal that
    happened. Without it, "what would help" becomes a model listing data that
    sounds useful - and a plausible request is worse than none, because somebody
    goes and fetches it.

    Matched on folded text. A model asked to quote a sentence re-types it with
    different accents or trims it, and refusing a real request over a missing
    diacritic teaches nobody anything.

    Returns:
        The requests that hold up, and one note per request that did not - said
        out loud, because a request dropped in silence looks like a Manager that
        needed nothing.
    """
    known = {fold(note): note for note in refusals}
    kept: list[DataNeed] = []
    dropped: list[str] = []
    for need in proposed:
        quoted = fold(need.blocked_by)
        match = next((text for key, text in known.items() if quoted and quoted in key), None)
        if match is None:
            dropped.append(
                f"bo yeu cau {need.ask[:60]!r}: no dan mot han che khong he xay ra "
                f"({need.blocked_by[:60]!r})."
            )
            continue
        # Stored as the refusal really reads, not as the model re-typed it.
        kept.append(need.model_copy(update={"blocked_by": match}))
    return tuple(kept), dropped


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
        # Cung mot ngan sach nhu A7, va cung mot ly do: cang nhieu chi so thi
        # cang nhieu thu de can nhac, va model tieu het cho dau ra vao viec do.
        shown, left_out = choose(
            [
                {"key": metric.key, "value": metric.value, "unit": metric.unit}
                for metric in sorted(metrics.values(), key=lambda item: item.key)
            ],
            question,
        )
        if left_out:
            unanswered = [*unanswered, left_out]
        answer = self._llm.complete(
            build_answer_request(
                question,
                reports,
                shown,
                unanswered,
                feedback_from(request.scope.params),
                rankings(metrics),
                str(request.scope.params.get(CONTEXT_PARAM) or ""),
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

        # A question with two ends to it, answered at one end. The other half
        # was rejected - correctly - and nothing said the question was left
        # standing, so a confident answer arrived to something only half asked.
        half = unanswered_end(question, [claim.claim for claim in supported])
        if half:
            unanswered.insert(0, half)

        # Cot duoc goi ten trong cau hoi ma khong luan diem nao cham toi. Loi
        # that: hoi ve "muc tieu tiet kiem", ca cau tra loi dung cot `PPF` va
        # khong he cham `Objective`. So co that, dan nguon duoc, vuot moi lop
        # chan - vi moi lop deu hoi "so nay co that khong", khong lop nao hoi
        # "cot nay co phai thu duoc hoi khong".
        missed_column = untouched(
            question,
            [claim.metric_keys for claim in supported],
            list(metrics),
            str(request.scope.params.get(CONTEXT_PARAM) or ""),
        )
        if missed_column:
            unanswered.insert(0, missed_column)

        # Turned round: `unanswered` says what could not be established, and a
        # need says what would change that. Only refusals that really happened
        # may be asked about - a plausible request costs somebody a trip to
        # fetch data that changes nothing.
        needs, invented = verified_needs(answer.data.needs, unanswered)
        rejected.extend(invented)
        # And it must be attached to this run. Quoting a real refusal is not
        # enough on its own: asked which emotion label was commonest, the
        # Manager asked for "du lieu ban hang cua nam 2024" - a real refusal
        # underneath, and a request about nothing that was here.
        vocabulary = [question, *(claim.claim for claim in supported), *metrics]
        needs, unmoored = moored_needs(needs, vocabulary)
        rejected.extend(unmoored)
        needs, off_subject = self._needs_on_topic(question, needs)
        rejected.extend(off_subject)

        result = ManagerAnswer(
            question=question,
            claims=tuple(supported),
            unanswered=tuple(unanswered),
            warnings=risks(unanswered),
            rejected=tuple(rejected),
            needs=needs,
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
                # How many questions went back to the person. Worth its own
                # number: a run that asked for nothing and a run whose requests
                # were all refused look identical without it.
                "needs": float(len(needs)),
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
            report = (
                self._read_analysis(ref, text)
                or self._read_process_map(ref, text)
                or self._read_terms(ref, text)
            )
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

    def _read_terms(
        self, ref: DataRef, text: str
    ) -> tuple[dict[str, MetricValue], dict[str, Any], list[str]] | None:
        """A10's reading of a document, if that is what this artifact holds.

        Sent up as evidence rather than as a finding. Frequency cannot separate
        a term that matters from one that is merely common or merely rare, so
        each band travels with a plain statement of what that band means, and
        the figures near a term travel as candidates a person judges.

        The limit goes up too. Left unsaid, a Manager reading "machine learning:
        87%" beside each other would write that the model reached 87% - which
        the document may well say, and which this counting did not establish.
        """
        try:
            found = TermReport.model_validate_json(text)
        except ValueError:
            return None

        said: dict[str, Any] = {
            "tu": "doc van xuoi",
            "nguon": ref.path,
            "nguon_du_lieu": found.source,
            "tong_tu": found.total_words,
            "so_tu_khac_nhau": found.distinct_terms,
            "tu_ngu": [
                {
                    "tu": row.term,
                    "so_lan": row.count,
                    "ty_le_phan_tram": round(row.share * 100, 2),
                    "bang": row.band,
                    "y_nghia_cua_bang": row.meaning,
                    "so_o_gan": list(row.numbers),
                    "doc_o": list(row.where),
                }
                for row in found.terms
            ],
        }
        limits = [
            "So O GAN khong phai la so THUOC VE tu do. Hai thu nay chi trung nhau "
            "khi doan van noi vay, va phep dem khong doc duoc doan van - nguoi doc "
            "moi quyet dinh duoc.",
            "Tan suat mot minh khong phan biet duoc tu quan trong voi tu chi hay gap "
            "hoac chi hiem. Bang 'nen' la chu de chung nen khong phan biet duoc doan "
            "nao; bang 'hiem' la cho DANG HOI, khong phai cho dang ket luan.",
        ]
        return (
            {metric.key: metric for metric in found.metrics},
            said,
            [*found.declined, *limits],
        )

    def _needs_on_topic(
        self, question: str, needs: tuple[DataNeed, ...]
    ) -> tuple[tuple[DataNeed, ...], list[str]]:
        """Keep the data requests that are about what was asked.

        `verified_needs` already refuses a request that invents the refusal it
        claims to lift. This is the other half: a request may quote a genuine
        refusal and still ask for something unrelated. Measured on a live run -
        asked which emotion label was commonest, the Manager asked for "du lieu
        ban hang cua nam 2024".

        That is the worst shape a request can take. A plausible one costs
        somebody the work of going and fetching data that changes nothing, and
        they only find out afterwards.

        Judged the same way claims are, against the same line. When no scorer
        can be built nothing is filtered, because filtering with something
        unreliable would throw away real requests.
        """
        if not needs:
            return needs, []
        try:
            verdicts = judge(
                question, [need.ask for need in needs], SemanticScorer(), RELEVANCE_FLOOR
            )
        except Exception as error:  # noqa: BLE001 - an absent model is not a bad request
            return needs, [
                f"khong kiem duoc do lien quan cua yeu cau du lieu ({error}) - giu nguyen."
            ]
        kept = tuple(need for need, verdict in zip(needs, verdicts, strict=True) if verdict.kept)
        notes = [
            f"loai yeu cau du lieu vi khong lien quan toi cau hoi "
            f"(do lien quan {verdict.score:.2f} < {RELEVANCE_FLOOR}): {verdict.claim[:70]}"
            for verdict in verdicts
            if not verdict.kept
        ]
        return kept, notes

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
            for verdict in verdicts
            if verdict.checked and not verdict.kept
        ]
        # Giu, chu khong phai da qua. Truoc day moi luan diem chua kiem duoc di
        # mot dong rieng, nam lan giua `unanswered` - nguoi doc gap chung sau
        # khi da doc het so, tuc la sau khi da tin. Gop lai mot dong va dua len
        # dau trang.
        unchecked = sum(1 for verdict in verdicts if not verdict.checked)
        if unchecked:
            notes.insert(0, unchecked_note(question, unchecked))
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
