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
from analysis_system.core.scoped_storage import ScopedStorage
from analysis_system.core.settings import Settings
from analysis_system.domains.data_ingestion.glossary_store import glossary_of
from analysis_system.domains.execution_engine.data_scope import SCOPE_RULE, scope_text
from analysis_system.domains.execution_engine.group_means import GROUP_MEANS_RULE
from analysis_system.domains.execution_engine.metrics import compute_metrics, metric_catalogue
from analysis_system.domains.execution_engine.modelling import (
    ModellingError,
    find_clusters,
    measure_importance,
)
from analysis_system.domains.execution_engine.point_values import point_comparison
from analysis_system.domains.execution_engine.statistics import (
    StatisticsError,
    StatisticsSpec,
    compute_statistics,
    suggest_spec,
    without_relationships,
)
from analysis_system.domains.execution_engine.timeline import (
    measure as measure_over_time,
)
from analysis_system.domains.execution_engine.timeline import (
    temporal_columns,
)
from analysis_system.models.agents import (
    AnalysisResult,
    FindingProposal,
    MetricValue,
    ProcessMap,
    RenderedFinding,
)
from analysis_system.models.base import (
    DataRef,
    ErrorDetail,
    RetryFeedback,
    TaskRequest,
    TaskResult,
)
from analysis_system.services.asked_columns import asked_question
from analysis_system.services.findings import rankings, render_all
from analysis_system.services.llm import LlmClient, LlmRequest
from analysis_system.services.prompts import load_prompt
from analysis_system.services.shortlist import choose

ARTIFACT_PREFIX: Final[str] = "artifacts://"
QUESTION_PARAM: Final[str] = "question"
CONTEXT_PARAM: Final[str] = "boi_canh"
DIMENSIONS_PARAM: Final[str] = "dimensions"

# A column with this many distinct values or fewer is something you can group
# by. Above it the groups stop being groups - the statistics layer already
# refuses a breakdown past twenty, so offering more would only be offering
# refusals.
MAX_GROUPS: Final[int] = 20


def groupable_columns(frame: pd.DataFrame) -> tuple[str, ...]:
    """Columns worth breaking the numbers down by, when nobody said which.

    `dimensions` decides whether any per-group metric exists at all, and it is
    explained nowhere in the planning prompt - so the Manager never set it, and
    a run that was asked to compare two labels computed no per-label number of
    any kind. It could not answer, and nothing said why.

    Empty is the wrong default. The obvious set is the categorical columns, and
    working them out from the table is arithmetic, not judgement: few enough
    distinct values to be groups, more than one so there is something to
    compare, and each group holding more than one row - a column of 16,000
    different sentences is not six groups, it is 16,000 groups of one.
    """
    groupable: list[str] = []
    for name in frame.columns:
        column = frame[name]
        if pd.api.types.is_numeric_dtype(column) or pd.api.types.is_datetime64_any_dtype(column):
            continue
        distinct = int(column.nunique(dropna=True))
        if 2 <= distinct <= MAX_GROUPS and distinct * 2 <= len(frame):
            groupable.append(str(name))
    return tuple(groupable)


MEASURES_PARAM: Final[str] = "measures"
TESTS_PARAM: Final[str] = "tests"
# Which models to fit. Declared, never derived: choosing what might
# account for an outcome is a claim, not a measurement.
MODELS_PARAM: Final[str] = "models"
MAX_FINDINGS: Final[int] = 10


def build_analysis_request(
    metrics_view: list[dict[str, Any]],
    question: str,
    max_findings: int,
    feedback: RetryFeedback | None = None,
    source: str = "",
    process: list[dict[str, Any]] | None = None,
    ranked: list[dict[str, str]] | None = None,
    context: str = "",
    scope: str = "",
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
        # Mot con so chi co nghia khi biet no do cai gi, va nguoi biet dieu do
        # la nguoi tai tep len - khong phai mot nhan do may doan.
        "boi_canh": context,
        # The table every metric was measured from. Demanding a citation while
        # withholding what to cite leaves the model guessing, and it guessed
        # mart://frame.parquet - twice, on two different runs.
        "source_table": source,
        "metrics": metrics_view,
        # The names behind the process metric keys. A model cannot say which
        # path is the common one without being told what the path is, and the
        # path is text - the numbers stay behind their keys.
        "process_paths": process or [],
        # Which group is top and bottom of each breakdown, worked out by code.
        # Same division as process_paths: the name travels as text, the figure
        # stays behind its key. Without this the model is asked which group is
        # highest while holding only numbers, and it answered by putting a
        # metric where the name belonged.
        "xep_hang_nhom": ranked or [],
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
            "Chi so co '.trend.with.' la TUONG QUAN HANG giua gia tri va thu tu "
            "cac ky: duong la di len dan, am la di xuong dan, gan 0 la khong co "
            "huong ro rang. Do KHONG phai du bao - he thong nay khong du bao gi.",
            "Muon noi THANG NAO cao nhat thi dung '.seasonal.peak_number' "
            "(la so thu tu thang hoac quy), va '.seasonal.peak_value' cho muc do. "
            "Vi du: 'Thang {x.seasonal.peak_number} ban nhieu nhat, dat "
            "{x.seasonal.peak_value}'. Thap nhat thi dung 'trough_'. "
            "TUYET DOI khong dat gia tri doanh thu vao cho so thang.",
            "Chi so '.seasonal.' chi co khi du IT NHAT HAI chu ky. Neu khong "
            "thay chung, nghia la du lieu chi co mot chu ky va khong the noi ve mua vu.",
            "Chi so bat dau bang 'process.' do QUY TRINH da chay ra sao. "
            "'.median_hours' la thoi gian cho, don vi gio - he thong tu chen don vi. "
            "Muon noi ve mot duong di thi dung ten trong 'process_paths', dung go so buoc.",
            "Chi so '.coef.' la he so hoi quy: gia tri thay doi bao nhieu khi bien do "
            "tang mot don vi VA CAC BIEN KHAC GIU NGUYEN. Neu dan he so thi phai noi ro "
            "dieu kien 'giu nguyen cac yeu to khac'.",
            "Muon GOI TEN mot nhom thi dung placeholder '{ten:<khoa>}' - no in ra "
            "TEN nhom, khong phai con so. Dung '{<khoa>}' o cho can mot cai ten: "
            "no in ra so, va cau se thanh 'Nhom van de 4 gia tri'. "
            # The names here are angle-bracketed on purpose. An earlier version
            # spelled out a real-looking key and the model grafted it onto this
            # table's columns - citing gio_xu_ly.mean.by.cot_2.anger on a
            # dataset with no such column. A shape cannot be copied; a name can.
            "Dang khoa: '<do_luong>.mean.by.<cot_nhom>.<ten_nhom>'. Thay ca ba phan "
            "bang ten THAT lay tu danh sach metrics o tren - dung lay ten tu vi du.",
            "Muon noi NHOM NAO cao nhat / thap nhat thi lay khoa trong "
            "'xep_hang_nhom' - code da so sanh san, khong phai tu doan. "
            "He thong KIEM TRA lai, noi sai nhom se bi loai ca cau.",
            GROUP_MEANS_RULE,
            *([RETRY_RULE] if feedback else []),
        ],
    }
    if scope:
        # Cac chi so do tren mot tap DA LOC. Khong noi ra thi model tu doan pham
        # vi: tren luot chay that no goi trung binh cua tap loc la "trung binh
        # chung", va gan ty le cua 381 dong cho "toan bo du lieu".
        payload["pham_vi_du_lieu"] = scope
        payload["rules"].append(SCOPE_RULE)
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
        modelled, model_notes = self._models(frame, request.scope.params)
        metrics.update(modelled)
        declined = [*self._unknown_columns(frame, request.scope.params), *declined, *model_notes]

        if self._llm is None:
            return self._failed(
                request, "NO_MODEL", "A7 can mot model de dien giai. Chi so da tinh xong."
            )

        question = str(request.scope.params.get(QUESTION_PARAM) or request.instruction)
        # Ngan sach cho prompt, khong phai hy vong no vua. Mot bang 25 cot sinh
        # ra 73.096 token dau vao va lan chay chet voi content=null: model tieu
        # het cho vao viec can nhac roi bi cat truoc khi kip tra loi.
        # Chon chi so theo cau hoi GOC va bang chu giai. Loi dan cua Manager co
        # the da doi cot: hoi "bien loi nhuan gop", loi dan viet ca 'Operating
        # Gross Margin' lan 'Gross Profit to Sales', va phep khop theo chu giu
        # lai cot sai.
        shown, left_out = choose(
            metric_catalogue(metrics),
            asked_question(request.scope.params, question),
            glossary=glossary_of(request.scope.params, CONTEXT_PARAM),
        )
        if left_out:
            declined.append(left_out)
        answer = self._llm.complete(
            build_analysis_request(
                shown,
                question,
                MAX_FINDINGS,
                feedback_from(request.scope.params),
                source.path,
                process_context,
                rankings(metrics),
                str(request.scope.params.get(CONTEXT_PARAM) or ""),
                scope=scope_text(files.load_text, source.path),
            )
        )
        if not isinstance(answer.data, FindingProposal):
            return self._failed(request, "BAD_PROPOSAL", "Model khong tra ve dung FindingProposal.")

        # The citation is set here, not asked for. There is exactly one legal
        # value - the table these metrics were computed from - and this code
        # handed it to the model in the first place, so asking for it back can
        # only introduce error.
        #
        # It did. Filling in only the blanks (the first attempt at this) missed
        # the way it actually fails: the models do not omit the field, they copy
        # the example URI out of the prompt and cite `mart://r1_case_total`, a
        # table that exists in an illustration and nowhere else. Three retries,
        # every one citing the same fiction.
        #
        # Overriding whatever the model wrote is the stricter choice, not the
        # looser one: a copied or invented URI can look entirely plausible and
        # point at a real table that has nothing to do with the claim, and
        # citation_exists would pass it. Now the citation cannot be wrong,
        # because nobody is guessing it.
        cited = [
            finding.model_copy(update={"evidence_ref": source.path})
            for finding in answer.data.findings
        ]
        rendered, rejected = render_all(cited, metrics, source.content_hash)

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
            metrics=tuple(metrics[key] for key in sorted(metrics)),
            # Tests that could not honestly be run are reported beside the
            # findings, never dropped: an absent number and a number nobody was
            # told about look identical from the outside.
            rejected=(*rejected, *declined),
        )
        target = f"{ARTIFACT_PREFIX}{request.scope.run_id}_{request.scope.task_id}_findings.json"
        written = files.save_text(result.model_dump_json(indent=2), target)

        return TaskResult(
            task_id=request.scope.task_id,
            agent_id=self.agent_id,
            status="OK",
            output_refs=(written,),
            declined=result.rejected,
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
        # Absent and empty are different answers. Saying nothing means "work it
        # out"; saying `dimensions: []` is a person choosing no breakdown, and
        # overriding that would be ignoring them.
        if DIMENSIONS_PARAM in params:
            dimensions = tuple(str(name) for name in (params[DIMENSIONS_PARAM] or []))
        else:
            dimensions = groupable_columns(frame)
        measures = tuple(str(name) for name in (params.get(MEASURES_PARAM) or []))
        return compute_metrics(frame, dimensions=dimensions, measures=measures)

    @staticmethod
    def _unknown_columns(frame: pd.DataFrame, params: dict[str, Any]) -> list[str]:
        """Names in `dimensions` or `measures` that the table does not have.

        A run asked for `measures: ["count"]` on a table whose numeric column is
        `word_count`. Nothing matched, so no measure was computed, and the only
        thing said about it was "bang khong co du cot so" - which blames the
        table for a table that was fine. The parameter was wrong, and the
        message pointed somewhere else entirely.
        """
        columns = {str(name) for name in frame.columns}
        missing: list[str] = []
        for param in (DIMENSIONS_PARAM, MEASURES_PARAM):
            for name in params.get(param) or []:
                if str(name) not in columns:
                    missing.append(f"'{param}' co ten {str(name)!r} nhung bang khong co cot do")
        return missing

    def _models(
        self, frame: pd.DataFrame, params: dict[str, Any]
    ) -> tuple[dict[str, Any], list[str]]:
        """Fit the models the task declared, if it declared any.

        Declared rather than guessed. Fitting a forest on every analysis would
        cost minutes and produce a ranking nobody asked for, and a ranking
        nobody asked for is a ranking somebody will quote.
        """
        raw = params.get(MODELS_PARAM)
        if not isinstance(raw, dict):
            return {}, []

        metrics: dict[str, Any] = {}
        notes: list[str] = []
        for entry in raw.get("importance") or []:
            if not isinstance(entry, dict) or "outcome" not in entry:
                notes.append("moi muc 'importance' phai co 'outcome' va 'features'.")
                continue
            try:
                found = measure_importance(
                    frame,
                    str(entry["outcome"]),
                    [str(name) for name in (entry.get("features") or [])],
                )
            except ModellingError as error:
                notes.append(str(error))
                continue
            metrics.update(found.metrics)
            notes.extend(found.refused)

        for entry in raw.get("cluster") or []:
            columns = entry if isinstance(entry, list) else (entry or {}).get("columns")
            if not columns:
                notes.append("moi muc 'cluster' phai neu ro cac cot so de nhom theo.")
                continue
            try:
                grouped = find_clusters(frame, [str(name) for name in columns])
            except ModellingError as error:
                notes.append(str(error))
                continue
            metrics.update(grouped.metrics)
            notes.extend(grouped.refused)

        return metrics, notes

    def _statistics(
        self, frame: pd.DataFrame, params: dict[str, Any]
    ) -> tuple[dict[str, Any], list[str]]:
        """Run the statistical tests the task declared, if it declared any.

        Declared rather than guessed: running a test nobody asked for produces a
        number somebody will quote.
        """
        raw = params.get(TESTS_PARAM)
        question = asked_question(params)
        if raw is not None:
            # Phep kiem planner tu khai cung chiu luat: khong hoi ve moi quan he thi
            # khong do tuong quan hay hoi quy.
            declared, banned = without_relationships(StatisticsSpec.from_params(raw), question)
            found, refused = compute_statistics(frame, declared)
            point, point_notes = point_comparison(frame, question)
            found.update(point)
            return found, [*banned, *refused, *point_notes]

        # Nobody said which tests to run. Deriving them from the table beats
        # running none: requiring the pair to be named up front asks the person
        # to name the relationship they already suspect, and the answer they
        # were looking for is usually the one they did not think to ask about.
        spec, notes = suggest_spec(
            frame,
            dimensions=[str(name) for name in (params.get(DIMENSIONS_PARAM) or [])],
            measures=[str(name) for name in (params.get(MEASURES_PARAM) or [])],
            question=question,
            context=glossary_of(params, CONTEXT_PARAM),
        )
        metrics, declined = compute_statistics(frame, spec)
        # Loc & Tinh: gia tri tai moc cau hoi goi ten va chenh lech, bang code. Tang
        # thong ke khong co phep nay, va "LNST Q2 so voi Q1" la mot phep loc va mot
        # phep tru, khong phai mot phep kiem (bo MBB, 2026-09-15).
        point, point_notes = point_comparison(frame, question)
        metrics.update(point)

        # Time gets its own pass, because the tests above are the wrong shape
        # for it. A group comparison over twelve months answers "are the months
        # different" the same way in any order - so it was never an answer
        # about time, and shuffling the rows proves it. What this adds are the
        # measurements that die when the order goes.
        along_time, time_notes = self._over_time(frame, spec)
        metrics.update(along_time)

        # The choices travel with the results. A test nobody asked for is fine;
        # a test nobody was told about is not.
        return metrics, [*notes, *declined, *time_notes, *point_notes]

    def _over_time(
        self, frame: pd.DataFrame, spec: StatisticsSpec
    ) -> tuple[dict[str, MetricValue], list[str]]:
        """Follow the measures through time, when the table has a time axis.

        Run without being asked, like the other suggestions, because asking for
        a trend means suspecting one already - and the trend nobody suspected is
        the one worth having.

        Only the measures already chosen for the other tests are followed. A
        column nobody thought worth correlating is not made interesting by
        putting a date beside it.
        """
        columns = temporal_columns(frame)
        if not columns:
            return {}, []

        measures = sorted(
            {name for pair in spec.correlations for name in pair}
            | {measure for measure, _ in spec.group_differences}
        )
        if not measures:
            return {}, []

        found: dict[str, MetricValue] = {}
        notes: list[str] = []
        # One axis only. Two date columns usually mean a start and an end, and
        # measuring against both says the same thing twice in words that look
        # like two findings.
        column = columns[0]
        if len(columns) > 1:
            notes.append(
                f"co {len(columns)} cot thoi gian ({', '.join(columns)}), chi theo doi "
                f"theo {column!r} - do theo ca hai se ra hai lan cung mot dieu."
            )
        line = measure_over_time(frame, column, measures)
        found.update(line.metrics)
        notes.extend(line.refused)
        return found, notes

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
