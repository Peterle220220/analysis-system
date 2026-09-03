"""A10: đọc văn xuôi đã trích ra và nói xem nó thật sự nói về cái gì.

Extracted text is not analysable data. A PDF that yields a table becomes a table
and the pipeline carries on; a PDF that yields only prose used to stop here, with
the text sitting in `extracted://` and nothing able to use it.

This is the step that gets past that, and it starts where the person asking has
to start: **which words is this document about?** Every term is counted, both
ends of the range are reported with a plain statement of what that end means,
and the figures standing beside each term are captured while reading.

That last part is what turns prose into a table later. When the reader picks a
term and asks *"từ này đi với những số nào"*, the answer was measured on the way
past rather than hunted for afterwards.

**Không dùng model nào.** Đếm từ, ghép cụm và nhặt số là số học. A model asked to
say which words matter would answer confidently and unrepeatably, and there would
be nothing to check it against - while the counts themselves can simply be
recomputed. Which term is worth pursuing is a judgement, and that judgement
belongs to the person reading, not to this agent.
"""

from __future__ import annotations

import json
import re
from typing import ClassVar, Final

import pandas as pd

from analysis_system.agents.base import BaseAgent, ManifestDir
from analysis_system.contracts.agents import (
    ExtractionResult,
    MetricValue,
    TermMention,
    TermReport,
    TermRow,
)
from analysis_system.contracts.base import DataRef, ErrorDetail, TaskRequest, TaskResult
from analysis_system.services.salience import Reading, fold, read
from analysis_system.services.scoped_storage import ScopedStorage
from analysis_system.settings import Settings

ARTIFACT_PREFIX: Final[str] = "artifacts://"
EXTRACTED_PREFIX: Final[str] = "extracted://"
# Which terms the reader wants a table for. Absent means no table is written:
# which term deserves one is a judgement about what somebody is trying to find
# out, and counting words cannot reach it.
TERMS_PARAM: Final[str] = "terms"
# How many terms reach the report. Enough to see the shape of a document,
# few enough that a person reads it rather than scrolls past it.
MAX_TERMS: Final[int] = 40
# Metrics are emitted only for the terms a reader might actually pursue. Every
# term still appears in the report; this is about what a claim may cite.
MAX_METRIC_TERMS: Final[int] = 20
# Characters that cannot appear in a metric key without breaking the placeholder
# machinery, which splits on dots and braces.
UNSAFE_IN_KEY: Final[re.Pattern[str]] = re.compile(r"[^a-z0-9]+")


def metric_name(term: str) -> str:
    """A metric key for this term.

    Spaces and punctuation are folded to underscores because the placeholder
    machinery splits keys on dots and reads braces - a term arriving with either
    in it would produce a claim nobody could substitute into.
    """
    return UNSAFE_IN_KEY.sub("_", term).strip("_")


def to_metrics(found: Reading, limit: int = MAX_METRIC_TERMS) -> tuple[MetricValue, ...]:
    """The counting, in the shape every other skill emits.

    Emitted as `MetricValue` rather than as a private report format so that a
    claim about a term goes through the same placeholder check, the same
    relevance check and the same chart code as a claim about a column. A second
    number format would need all of that built again, and the second copy is
    where the guarantees quietly diverge.
    """
    metrics: list[MetricValue] = [
        MetricValue(
            key="text.words.total",
            value=float(found.total_words),
            unit="tu",
            source="dem tu van ban",
        ),
        MetricValue(
            key="text.terms.distinct",
            value=float(found.distinct_terms),
            unit="tu khac nhau",
            source="dem tu van ban",
        ),
    ]
    for term in found.terms[:limit]:
        name = metric_name(term.term)
        if not name:
            continue
        where = f"tu {term.term!r} trong van ban"
        metrics.append(
            MetricValue(key=f"term.{name}.count", value=float(term.count), unit="lan", source=where)
        )
        metrics.append(
            MetricValue(
                key=f"term.{name}.share",
                value=round(term.share * 100, 2),
                unit="%",
                source=where,
            )
        )
    return tuple(metrics)


class TextMinerAgent(BaseAgent):
    """Counts what a document talks about. Decides nothing about it."""

    agent_id: ClassVar[str] = "a10_text_miner"

    def __init__(self, settings: Settings, manifest_dir: ManifestDir = None) -> None:
        """No model: this agent counts, and counting is arithmetic."""
        super().__init__(settings, manifest_dir)

    def execute(self, request: TaskRequest, files: ScopedStorage) -> TaskResult:
        """Read the extracted text and report what it is about."""
        source = self._extraction_ref(request)
        if source is None:
            return self._failed(
                request,
                "NO_TEXT",
                "A10 can mot ket qua trich xuat (extracted://...json) de doc.",
            )

        try:
            extraction = ExtractionResult.model_validate_json(files.load_text(source.path))
        except (ValueError, OSError) as error:
            return self._failed(request, "BAD_TEXT", f"Khong doc duoc {source.path}: {error}")

        # One locator per line, so a term traces back to the page it was read
        # from. Spans can hold several lines each, which is why this is built
        # line by line rather than span by span.
        lines: list[str] = []
        locators: list[str] = []
        for span in extraction.spans:
            for line in span.text.splitlines() or [""]:
                lines.append(line)
                locators.append(_describe(span.locator))

        found = read("\n".join(lines), locators=locators, max_terms=MAX_TERMS)
        if not found.terms:
            return self._failed(
                request,
                "NOTHING_TO_COUNT",
                "; ".join(found.declined) or "Van ban khong co tu nao mang noi dung.",
            )

        report = TermReport(
            source=source.path,
            total_words=found.total_words,
            distinct_terms=found.distinct_terms,
            terms=tuple(
                TermRow(
                    term=term.term,
                    count=term.count,
                    share=term.share,
                    band=term.band,
                    meaning=term.note,
                    numbers=term.numbers,
                    where=term.where,
                    mentions=tuple(
                        TermMention(where=m.where, numbers=m.numbers) for m in term.mentions
                    ),
                    is_phrase=term.is_phrase,
                )
                for term in found.terms
            ),
            metrics=to_metrics(found),
            declined=found.declined,
        )
        target = f"{ARTIFACT_PREFIX}{request.scope.run_id}_terms.json"
        written = [files.save_text(report.model_dump_json(indent=2), target)]

        # Only when asked. A table nobody requested would be a table built
        # around whichever term is most frequent - which is, by this agent's own
        # reckoning, the term that distinguishes nothing.
        wanted = _wanted_terms(request)
        table_rows = 0
        notes = list(found.declined)
        if wanted:
            frame = mentions_table(report, wanted)
            table_rows = len(frame)
            if table_rows:
                written.append(
                    files.save_parquet(
                        frame, f"{EXTRACTED_PREFIX}{request.scope.run_id}_bang_tu.parquet"
                    )
                )
            else:
                notes.append(
                    f"khong lap duoc bang: khong thay tu nao trong {sorted(wanted)} "
                    "o danh sach da doc duoc."
                )

        bands = {band: len(found.band(band)) for band in ("nen", "vua", "hiem")}
        return TaskResult(
            task_id=request.scope.task_id,
            agent_id=self.agent_id,
            status="OK",
            output_refs=tuple(written),
            declined=tuple(notes),
            metrics={
                "words": float(found.total_words),
                "terms": float(len(found.terms)),
                "terms_wallpaper": float(bands["nen"]),
                "terms_rare": float(bands["hiem"]),
                # How many terms have a figure beside them - the ones a table
                # could actually be built from.
                "terms_with_numbers": float(sum(1 for term in found.terms if term.numbers)),
                # Zero unless a table was asked for, so a run that produced none
                # is distinguishable from one where nobody wanted one.
                "table_rows": float(table_rows),
            },
            payload=json.loads(report.model_dump_json()),
        )

    def _failed(self, request: TaskRequest, code: str, message: str) -> TaskResult:
        """Report an honest failure, with nothing written.

        Nothing here is retryable: this agent counts words, so a second attempt
        at the same text counts them the same way. What can be missing is the
        text itself, and that is a problem with the plan rather than with the
        attempt.
        """
        return TaskResult(
            task_id=request.scope.task_id,
            agent_id=self.agent_id,
            status="FAILED",
            error=ErrorDetail(
                code=code,
                message=message,
                retryable=False,
                replannable=code == "NO_TEXT",
            ),
        )

    def _extraction_ref(self, request: TaskRequest) -> DataRef | None:
        """The extraction result among the inputs, chosen by what it is.

        By type rather than by position: an extractor hands over its tables and
        its report together, and taking `input_refs[0]` has already cost this
        system one silent failure.
        """
        for ref in request.input_refs:
            if ref.path.endswith(".json"):
                return ref
        return None


def _wanted_terms(request: TaskRequest) -> set[str]:
    """Which terms the reader asked for a table about, folded for comparison."""
    asked = request.scope.params.get(TERMS_PARAM)
    if isinstance(asked, str):
        asked = [asked]
    if not isinstance(asked, list | tuple):
        return set()
    return {fold(str(item)).strip() for item in asked if str(item).strip()}


def mentions_table(report: TermReport, wanted: set[str]) -> pd.DataFrame:
    """Một dòng cho mỗi lần từ được yêu cầu xuất hiện: ở đâu, và có số nào bên cạnh.

    This is the answer to *"mỗi lần từ đó xuất hiện thì có những số liệu gì"*,
    laid out so it can be analysed like any other table in this system.

    The column is called `so_o_gan` for a reason. Naming it "số của từ này" would
    make the claim the counting cannot make: figures beside a term may describe
    it, may describe its neighbour, or may describe neither, and only the
    paragraph settles which.
    """
    rows: list[dict[str, object]] = []
    for term in report.terms:
        if fold(term.term).strip() not in wanted:
            continue
        # Per mention, so `doc_o` and `so_o_gan` describe the same place. Built
        # from the whole-term list, this row would name page 1 and then list
        # figures from page 3 - a reader following it finds nothing, and a
        # reader not following it believes something false.
        for mention in term.mentions or (TermMention(),):
            rows.append(
                {
                    "tu": term.term,
                    "doc_o": mention.where,
                    "so_o_gan": ", ".join(mention.numbers),
                    "so_lan_toan_van_ban": term.count,
                    "ty_le_phan_tram": round(term.share * 100, 2),
                    "bang": term.band,
                    "la_cum_tu": term.is_phrase,
                }
            )
    return pd.DataFrame(rows)


def _describe(locator: object) -> str:
    """Where a span came from, in the terms the original uses."""
    kind = str(getattr(locator, "kind", "") or "vi tri")
    page = int(getattr(locator, "page", 0) or 0)
    if page:
        return f"{kind} {page}"
    start = getattr(locator, "start_s", None)
    if start is not None:
        return f"giay {start}"
    return kind
