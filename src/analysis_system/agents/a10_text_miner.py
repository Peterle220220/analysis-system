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
from analysis_system.core.scoped_storage import ScopedStorage
from analysis_system.core.settings import Settings
from analysis_system.models.agents import (
    ExtractionResult,
    MetricValue,
    TermMention,
    TermReport,
    TermRow,
)
from analysis_system.models.base import DataRef, ErrorDetail, TaskRequest, TaskResult
from analysis_system.services.salience import Reading, fold, lift, read

ARTIFACT_PREFIX: Final[str] = "artifacts://"
EXTRACTED_PREFIX: Final[str] = "extracted://"
# Which terms the reader wants a table for. Absent means no table is written:
# which term deserves one is a judgement about what somebody is trying to find
# out, and counting words cannot reach it.
TERMS_PARAM: Final[str] = "terms"
# Which column of a table holds the prose. Naming it is what turns this agent
# from a reader of extracted documents into a reader of the ordinary case: a
# CSV of reviews, tickets or labelled sentences.
TEXT_COLUMN_PARAM: Final[str] = "text_column"
# Which rows to read, as {cot: gia tri}. Lets "what do the sadness sentences
# say" be asked without building a separate table to ask it of.
FILTER_PARAM: Final[str] = "where"
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


def to_metrics(
    found: Reading,
    limit: int = MAX_METRIC_TERMS,
    against: dict[str, float] | None = None,
) -> tuple[MetricValue, ...]:
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
            unit="từ",
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
            MetricValue(key=f"term.{name}.count", value=float(term.count), unit="lần", source=where)
        )
        metrics.append(
            MetricValue(
                key=f"term.{name}.share",
                value=round(term.share * 100, 2),
                unit="%",
                source=where,
            )
        )
        if against and term.term in against:
            metrics.append(
                MetricValue(
                    key=f"term.{name}.lift",
                    value=against[term.term],
                    unit="lần",
                    source=f"ty le cua {term.term!r} trong nhom nay so voi ngoai nhom",
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
        """Read the text and report what it is about.

        The text can arrive two ways. A PDF or an image becomes an
        `extracted://` document; a CSV of reviews, tickets or labelled
        sentences arrives as a table with the prose sitting in one column, and
        that second case is the ordinary one for this kind of work. Until this
        agent could read a column, the most common shape of text in the whole
        system was the one shape it could not see.
        """
        table = self._table_ref(request)
        if table is not None:
            return self._from_column(request, files, table)

        source = self._extraction_ref(request)
        if source is None:
            return self._failed(
                request,
                "NO_TEXT",
                "A10 can mot ket qua trich xuat (extracted://...json), hoac mot bang "
                f"kem tham so {TEXT_COLUMN_PARAM!r} chi ra cot chua van ban.",
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

        return self._report(request, files, found, source.path)

    def _report(
        self,
        request: TaskRequest,
        files: ScopedStorage,
        found: Reading,
        source: str,
        against: dict[str, float] | None = None,
    ) -> TaskResult:
        """Write the term report and answer with it.

        Shared by both ways in. Two copies of this would be the fourth time a
        duplicated decision in this codebase drifted apart, and the previous
        three each cost a real bug.
        """
        report = TermReport(
            source=source,
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
            metrics=to_metrics(found, against=against),
            declined=found.declined,
        )
        target = f"{ARTIFACT_PREFIX}{request.scope.run_id}_{request.scope.task_id}_terms.json"
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
                        frame,
                        f"{EXTRACTED_PREFIX}{request.scope.run_id}"
                        f"_{request.scope.task_id}_bang_tu.parquet",
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

    def _table_ref(self, request: TaskRequest) -> DataRef | None:
        """The table to mine, when the task named a text column in one."""
        if not request.scope.params.get(TEXT_COLUMN_PARAM):
            return None
        return next((ref for ref in request.input_refs if ref.format == "parquet"), None)

    def _from_column(
        self, request: TaskRequest, files: ScopedStorage, table: DataRef
    ) -> TaskResult:
        """Count terms in one column of a table.

        One row, one line, so a term traces back to the row it was read in -
        the same relationship a page gives an extracted document. A second
        column may narrow the rows first, which is how "what do the `sadness`
        sentences say" gets asked without building a separate table for it.
        """
        column = str(request.scope.params[TEXT_COLUMN_PARAM])
        whole = files.load_parquet(table.path)
        frame = whole
        if column not in frame.columns:
            known = ", ".join(str(name) for name in frame.columns)
            return self._failed(request, "NO_COLUMN", f"Bang khong co cot {column!r}. Co: {known}.")

        where = request.scope.params.get(FILTER_PARAM) or {}
        for name, value in where.items():
            if str(name) not in frame.columns:
                return self._failed(
                    request, "NO_COLUMN", f"Khong loc duoc: bang khong co cot {str(name)!r}."
                )
            # A list means any of them. Asked about sadness and fear the
            # Manager sent {"cot_2": ["sadness", "fear"]}, which is the natural
            # way to say it, and a straight equality compared every row against
            # the string "['sadness', 'fear']" and matched nothing.
            values = frame[str(name)].astype(str)
            wanted = value if isinstance(value, list | tuple) else [value]
            frame = frame[values.isin([str(item) for item in wanted])]

        # The rows this filter left out. Counting only the group answers "what
        # does it talk about"; the question asked is "what is characteristic of
        # it", and that needs something to be characteristic against.
        rest = whole.drop(frame.index) if where else whole.iloc[0:0]

        texts = [str(value) for value in frame[column].dropna()]
        if not texts:
            return self._failed(
                request,
                "NOTHING_TO_COUNT",
                f"Khong con dong nao trong cot {column!r} sau khi loc {where!r}.",
            )

        locators = [f"dong {index}" for index in frame.index]
        found = read("\n".join(texts), locators=locators, max_terms=MAX_TERMS)
        if not found.terms:
            return self._failed(
                request,
                "NOTHING_TO_COUNT",
                "; ".join(found.declined) or "Van ban khong co tu nao mang noi dung.",
            )
        described = f"{table.path}#{column}" + (f" ({where})" if where else "")
        against = None
        if len(rest.index):
            outside = read(
                "\n".join(str(value) for value in rest[column].dropna()), max_terms=MAX_TERMS * 4
            )
            against = lift(found, outside)
        return self._report(request, files, found, described, against)

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
