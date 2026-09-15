"""A8 Reporter: turn findings into a deliverable.

The model writes the prose around the numbers and never the numbers themselves,
exactly as in A7 and for the same reason. It receives the findings already
rendered by code and the metric set, and returns an executive summary written
with placeholders. Code substitutes.

The report is assembled by a template. Charts are drawn from the metric set.
Nothing in the finished document originates as a figure the model typed.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar, Final

from analysis_system.agents.base import BaseAgent, ManifestDir, first_of
from analysis_system.agents.feedback import RETRY_RULE, as_prompt_fields, feedback_from
from analysis_system.core.scoped_storage import ScopedStorage
from analysis_system.core.settings import Settings
from analysis_system.domains.visualization.charts import ChartError, chart_from_metrics
from analysis_system.models.agents import (
    AnalysisResult,
    MetricValue,
    NarrativeProposal,
    RenderedFinding,
    ReportResult,
)
from analysis_system.models.base import DataRef, ErrorDetail, TaskRequest, TaskResult
from analysis_system.services.findings import (
    PLACEHOLDER,
    causal_overreach,
    placeholders,
    strip_known_labels,
)
from analysis_system.services.llm import LlmClient, LlmRequest
from analysis_system.services.prompts import load_prompt

REPORT_DIR: Final[str] = "artifacts://report"
CHART_SUFFIX: Final[str] = ".share_pct"
APPROVED_FINDINGS_PARAM: Final[str] = "approved_findings"


def select_findings(analysis: AnalysisResult, approved: list[str]) -> AnalysisResult:
    """Keep only the findings HUMAN GATE 2 approved.

    Findings are addressed by position - f1 is the first one A7 produced - which
    is what lets a decision be applied without re-running the analysis and
    getting a different set of candidates to decide about.

    Raises:
        ValueError: an approved id names no finding. That means the decision and
            the analysis disagree about what was on the table, and quietly
            dropping the id would report something nobody approved.
    """
    wanted: list[int] = []
    for option_id in approved:
        text = option_id[1:] if option_id.startswith("f") else option_id
        if not text.isdigit() or not 1 <= int(text) <= len(analysis.findings):
            raise ValueError(
                f"Gate duyet {option_id!r} nhung phan tich chi co "
                f"{len(analysis.findings)} ket luan."
            )
        wanted.append(int(text) - 1)

    kept = tuple(analysis.findings[index] for index in sorted(set(wanted)))
    return analysis.model_copy(update={"findings": kept})


def render_narrative(template: str, metrics: dict[str, MetricValue]) -> tuple[str, list[str]]:
    """Substitute metric values into narrative prose.

    Held to the same rules as a finding, and for a better reason: the summary is
    the part a reader actually reads. A guard that covers the careful prose and
    not the readable prose protects nothing.

    Returns:
        The rendered text, and any problems found. A summary carrying a digit
        the model typed itself is a problem, not something to tidy up.
    """
    problems: list[str] = []
    used = placeholders(template)
    stripped = strip_known_labels(PLACEHOLDER.sub("", template), metrics)
    if any(character.isdigit() for character in stripped):
        problems.append("phan tom tat chua con so go truc tiep")
    unknown = [key for key in used if key not in metrics]
    if unknown:
        problems.append(f"tom tat tro toi chi so khong ton tai: {unknown}")

    overreach = causal_overreach(template, used)
    if overreach is not None:
        problems.append(
            f"tom tat dung tu chi nhan qua {overreach!r} trong khi chi so chi do MOI "
            "LIEN HE. Viet lai theo kieu mo ta: 'di kem voi', 'tuong quan voi'."
        )
    if problems:
        return "", problems

    def substitute(match: Any) -> str:
        metric = metrics[match.group(1)]
        number = (
            f"{metric.value:,.0f}" if float(metric.value).is_integer() else f"{metric.value:,.2f}"
        )
        return f"{number} {metric.unit}".strip() if metric.unit else number

    return PLACEHOLDER.sub(substitute, template), []


def render_markdown(
    title: str,
    summary: str,
    findings: tuple[RenderedFinding, ...],
    metrics: dict[str, MetricValue],
    charts: tuple[str, ...],
    sources: tuple[str, ...],
) -> str:
    """Assemble the report. Every figure comes from the metric set."""
    lines: list[str] = [f"# {title}", ""]

    if summary:
        lines += ["## Tóm tắt", "", summary, ""]

    lines += ["## Kết luận", ""]
    if findings:
        for index, finding in enumerate(findings, start=1):
            lines.append(f"{index}. {finding.claim}")
            lines.append(f"   - Nguồn: `{finding.evidence_ref}`")
            if finding.evidence_hash:
                # So the citation says which content, not only which path.
                lines.append(f"   - Hash nguồn: `{finding.evidence_hash[:16]}`")
            lines.append(f"   - Chỉ số dùng: {', '.join(sorted(finding.metrics))}")
            lines.append(f"   - Độ tin cậy: {finding.confidence:.2f}")
            lines.append("")
    else:
        lines += ["Không có kết luận nào vượt qua kiểm tra.", ""]

    if charts:
        lines += ["## Biểu đồ", ""]
        lines += [f"![{name}]({name})" for name in charts]
        lines.append("")

    lines += ["## Chỉ số", "", "| Chỉ số | Giá trị | Đơn vị |", "|---|---:|---|"]
    for metric in sorted(metrics.values(), key=lambda item: item.key):
        number = (
            f"{metric.value:,.0f}" if float(metric.value).is_integer() else f"{metric.value:,.2f}"
        )
        lines.append(f"| `{metric.key}` | {number} | {metric.unit} |")
    lines.append("")

    lines += ["## Nguồn dữ liệu", ""]
    lines += [f"- `{source}`" for source in sources]
    lines.append("")
    return "\n".join(lines)


def render_html(markdown_text: str, title: str) -> str:
    """Wrap the report in minimal HTML.

    Deliberately plain: no external stylesheet, no script, nothing that needs a
    network to render. A report that only displays when online is not a report.
    """
    escaped = markdown_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="vi"><head><meta charset="utf-8">',
            f"<title>{title}</title>",
            "<style>body{font-family:system-ui,sans-serif;max-width:860px;"
            "margin:2rem auto;padding:0 1rem;line-height:1.6}"
            "pre{white-space:pre-wrap}</style>",
            "</head><body>",
            f"<pre>{escaped}</pre>",
            "</body></html>",
        ]
    )


PLAN_PROBLEM_CODES: Final[frozenset[str]] = frozenset({"NO_INPUT"})


class ReporterAgent(BaseAgent):
    """Writes the deliverable from findings that already passed their checks."""

    agent_id: ClassVar[str] = "a8_reporter"

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
        """Build the report from the analysis result it was given."""
        if not request.input_refs:
            return self._failed(request, "NO_INPUT", "A8 can ket qua phan tich cua A7.")

        # The analysis result, which is JSON. A8 may also be handed the mart
        # table for context, and taking whichever came first meant reading a
        # Parquet file as JSON.
        source = first_of(request.input_refs, "json")
        if source is None:
            return self._failed(request, "NO_INPUT", "A8 can ket qua phan tich cua A7.")
        try:
            analysis = AnalysisResult.model_validate_json(files.load_text(source.path))
        except Exception as error:  # noqa: BLE001 - any malformed input is the same failure
            return self._failed(request, "BAD_INPUT", f"Khong doc duoc ket qua phan tich: {error}")

        approved = request.scope.params.get(APPROVED_FINDINGS_PARAM)
        if approved is not None:
            if not isinstance(approved, list | tuple):
                return self._failed(
                    request, "BAD_PARAMS", f"{APPROVED_FINDINGS_PARAM} phai la mot danh sach."
                )
            try:
                analysis = select_findings(analysis, [str(item) for item in approved])
            except ValueError as error:
                return self._failed(request, "BAD_PARAMS", str(error))

        metrics = self._metrics_from(analysis)
        title = str(request.scope.params.get("title") or "Báo cáo phân tích dữ liệu")

        summary, problems, attempted = self._summary(analysis, metrics, request)
        if problems:
            # The model can write this again without a typed digit, once told
            # that is what was wrong. A different plan cannot help it.
            return self._failed(
                request,
                "SUMMARY_REJECTED",
                "; ".join(problems),
                retryable=True,
                payload={"summary_template": attempted},
            )

        run_id = request.scope.run_id
        charts = self._charts(metrics, run_id, files)

        markdown_text = render_markdown(
            title=title,
            summary=summary,
            findings=analysis.findings,
            metrics=metrics,
            charts=tuple(name.rsplit("/", 1)[-1] for name in charts),
            sources=(analysis.source, source.path),
        )
        markdown_ref = files.save_text(
            markdown_text, f"{REPORT_DIR}/{run_id}.md", data_format="blob"
        )
        html_ref = files.save_text(
            render_html(markdown_text, title), f"{REPORT_DIR}/{run_id}.html", data_format="blob"
        )

        result = ReportResult(
            title=title,
            markdown=markdown_ref.path,
            html=html_ref.path,
            charts=tuple(charts),
            findings=len(analysis.findings),
            metrics=len(metrics),
        )
        return TaskResult(
            task_id=request.scope.task_id,
            agent_id=self.agent_id,
            status="OK",
            output_refs=(markdown_ref, html_ref),
            metrics={
                "findings": float(len(analysis.findings)),
                "charts": float(len(charts)),
                "metrics": float(len(metrics)),
            },
            payload=result.model_dump(mode="json"),
        )

    def _metrics_from(self, analysis: AnalysisResult) -> dict[str, MetricValue]:
        """Rebuild the metric set from the findings that used it.

        A8 quotes only what A7 already stood behind, so the report cannot
        contain a figure no finding rested on.
        """
        metrics: dict[str, MetricValue] = {}
        for finding in analysis.findings:
            for key, value in finding.metrics.items():
                metrics[key] = MetricValue(key=key, value=value, source=analysis.source)
        return metrics

    def _summary(
        self,
        analysis: AnalysisResult,
        metrics: dict[str, MetricValue],
        request: TaskRequest,
    ) -> tuple[str, list[str], str]:
        """Ask the model for an executive summary, then check it.

        Returns:
            The rendered text, the problems found, and the template exactly as
            written - the last so a retry can be shown what was rejected.
        """
        if self._llm is None:
            return "", [], ""
        feedback = feedback_from(request.scope.params)
        payload: dict[str, Any] = {
            "question": analysis.question,
            "findings": [finding.claim for finding in analysis.findings],
            "metrics": [
                {"key": metric.key, "value": metric.value, "unit": metric.unit}
                for metric in sorted(metrics.values(), key=lambda item: item.key)
            ],
            **as_prompt_fields(feedback),
            "rules": [
                "Moi con so phai la placeholder {ten_chi_so}.",
                "TUYET DOI khong go con so truc tiep.",
                "Viet cho nguoi ra quyet dinh doc, khong viet cho ky thuat.",
                "KHONG viet don vi sau placeholder - he thong tu chen.",
                "Chi so co '.corr.', '.ttest.', '.anova.' chi do MOI LIEN HE. TUYET DOI "
                "khong viet 'tac dong den', 'anh huong den', 'lam tang', 'cai thien'. "
                "Viet 'di kem voi', 'tuong quan voi', 'cao hon o nhom...'.",
                *([RETRY_RULE] if feedback else []),
            ],
        }
        answer = self._llm.complete(
            LlmRequest(
                purpose="a8_reporter_summary",
                system=load_prompt("a8_reporter_summary"),
                prompt=json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
                schema=NarrativeProposal,
            )
        )
        if not isinstance(answer.data, NarrativeProposal):
            return "", ["Model khong tra ve dung NarrativeProposal."], ""
        template = answer.data.summary_template
        text, problems = render_narrative(template, metrics)
        return text, problems, template

    def _charts(
        self, metrics: dict[str, MetricValue], run_id: str, files: ScopedStorage
    ) -> list[str]:
        """Draw whatever the metric set supports. No chart is not a failure."""
        values = {key: metric.value for key, metric in metrics.items()}
        try:
            png = chart_from_metrics(
                values, title="Ty trong theo nhom", suffix=CHART_SUFFIX, ylabel="%"
            )
        except ChartError:
            return []
        reference: DataRef = files.save_bytes(png, f"{REPORT_DIR}/{run_id}_share.png")
        return [reference.path]

    def _failed(
        self,
        request: TaskRequest,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        payload: dict[str, Any] | None = None,
    ) -> TaskResult:
        """Report an honest failure, with no document written.

        A rejected draft travels in the payload so the next attempt can be shown
        what was wrong with it. Nothing downstream reads it: only the Manager,
        and only to build the next question.
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
