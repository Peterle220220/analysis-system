"""A2 Profiler: describe the data. Read-only, absolutely.

Every number in the report is computed here in code. The model is asked one
thing only - what the columns appear to mean - and its answer is merged in as
text. If no model is available the profile is still produced, just without the
commentary, because a profile with no opinions is still a profile.

This agent never writes anywhere but profile://, and never modifies what it
reads. The manifest denies it, pre-flight enforces it, and the scoped storage it
is handed cannot address anything else.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar, Final

import pandas as pd

from analysis_system.agents.base import BaseAgent, ManifestDir, first_of
from analysis_system.contracts.agents import (
    ColumnProfile,
    EventLogCandidates,
    ProfileInterpretation,
    ProfileReport,
    ValueCount,
)
from analysis_system.contracts.base import ErrorDetail, TaskRequest, TaskResult
from analysis_system.services.llm import LlmClient, LlmRequest
from analysis_system.services.pii import (
    STRONG_KINDS,
    build_llm_sample,
    find_pii_kinds,
    name_suggests_pii,
)
from analysis_system.services.prompts import load_prompt
from analysis_system.services.scoped_storage import ScopedStorage
from analysis_system.settings import Settings

PROFILE_URI: Final[str] = "profile://profile.json"
TARGET_PARAM: Final[str] = "target"


def profile_uri_for(run_id: str) -> str:
    """Where one run's profile goes.

    Named after the run, because a fixed name means the second run silently
    destroys the first one's evidence - and nothing in the system notices.
    """
    return f"profile://{run_id}_profile.json"


PII_SAMPLE_SIZE: Final[int] = 200
PII_HIT_RATIO: Final[float] = 0.2

# Column names that usually carry each event-log role. Only a starting guess:
# the model is asked to confirm or correct it.
ROLE_HINTS: Final[dict[str, tuple[str, ...]]] = {
    "case_id": ("case_id", "case", "caseid", "concept:name", "trace_id"),
    "activity": ("activity", "event", "action", "task", "operation"),
    "timestamp": ("timestamp", "time", "datetime", "event_time", "date"),
    "resource": ("resource", "user", "actor", "performer", "operator"),
}


def looks_like_pii(series: pd.Series[Any], column_name: str = "") -> bool:
    """True when a column genuinely appears to hold personal data.

    Two gates, both needed, for two different reasons.

    Enough of the sample must match, because one email inside a free-text column
    should not lock the whole column away.

    And the evidence must be strong enough. An email or phone number has a shape
    that identifies a person by itself. A run of digits does not: on the real BPI
    log, a purchase document number matched the bank-account pattern and got
    case_id flagged as personal data. For those weak patterns the column name has
    to agree before the column is withheld from the model.
    """
    sample = series.dropna().astype(str).head(PII_SAMPLE_SIZE)
    if sample.empty:
        return False

    strong_hits = 0
    weak_hits = 0
    for value in sample:
        kinds = find_pii_kinds(value)
        if not kinds:
            continue
        if kinds & STRONG_KINDS:
            strong_hits += 1
        else:
            weak_hits += 1

    if strong_hits / len(sample) >= PII_HIT_RATIO:
        return True
    if weak_hits / len(sample) >= PII_HIT_RATIO:
        return name_suggests_pii(column_name)
    return False


TOP_VALUE_COUNT: Final[int] = 5
NUMERIC_SHARE_FOR_OUTLIERS: Final[float] = 0.9
IQR_MULTIPLIER: Final[float] = 1.5


def top_values(series: pd.Series[Any], limit: int = TOP_VALUE_COUNT) -> tuple[ValueCount, ...]:
    """The most common values, ties broken by value so two runs agree."""
    counts = series.dropna().astype(str).value_counts()
    if counts.empty:
        return ()
    ordered = sorted(counts.items(), key=lambda item: (-int(item[1]), str(item[0])))
    return tuple(ValueCount(value=str(v), count=int(c)) for v, c in ordered[:limit])


def numeric_view(series: pd.Series[Any]) -> tuple[pd.Series[Any], float]:
    """Parse a column as numbers, and report what share actually parsed."""
    present = series.dropna()
    if present.empty:
        return present, 0.0
    parsed = pd.to_numeric(present, errors="coerce")
    share = float(parsed.notna().sum()) / float(len(present))
    return parsed.dropna(), round(share, 4)


def count_outliers(values: pd.Series[Any]) -> int:
    """Number of values outside the interquartile fence."""
    if len(values) < 4:
        return 0
    q1 = float(values.quantile(0.25))
    q3 = float(values.quantile(0.75))
    spread = q3 - q1
    if spread == 0:
        return 0
    low = q1 - IQR_MULTIPLIER * spread
    high = q3 + IQR_MULTIPLIER * spread
    return int(((values < low) | (values > high)).sum())


def profile_columns(frame: pd.DataFrame) -> tuple[ColumnProfile, ...]:
    """Measure every column, sorted by name so two runs agree."""
    total = len(frame.index)
    profiles: list[ColumnProfile] = []
    for name in sorted(str(column) for column in frame.columns):
        series = frame[name]
        non_null = int(series.notna().sum())
        lengths = series.dropna().astype(str).str.len()
        numbers, numeric_share = numeric_view(series)

        if numeric_share >= NUMERIC_SHARE_FOR_OUTLIERS and len(numbers):
            minimum: str | None = str(numbers.min())
            maximum: str | None = str(numbers.max())
            outliers = count_outliers(numbers)
        else:
            text = series.dropna().astype(str)
            minimum = str(text.min()) if len(text) else None
            maximum = str(text.max()) if len(text) else None
            outliers = 0

        profiles.append(
            ColumnProfile(
                name=name,
                dtype=str(series.dtype),
                non_null=non_null,
                null_pct=0.0 if total == 0 else round(100.0 * (total - non_null) / total, 2),
                distinct=int(series.nunique(dropna=True)),
                avg_length=round(float(lengths.mean()), 2) if len(lengths) else 0.0,
                numeric_share=numeric_share,
                min_value=minimum,
                max_value=maximum,
                top_values=top_values(series),
                outlier_count=outliers,
                is_pii_candidate=looks_like_pii(series, name),
            )
        )
    return tuple(profiles)


def _pick_role(
    names: list[str], lowered: dict[str, str], role: str, hints: tuple[str, ...]
) -> str | None:
    """Find the column playing one role, exact matches first.

    Order matters more than it looks. A plain substring search matches "case"
    inside "case_company" and would hand back the wrong column as the case id,
    which quietly corrupts every variant discovered later.
    """
    for name in names:
        if lowered[name] == role:
            return name
    for hint in hints:
        for name in names:
            if lowered[name] == hint:
                return name
    for hint in hints:
        for name in names:
            if hint in lowered[name]:
                return name
    return None


def guess_roles(columns: tuple[ColumnProfile, ...]) -> EventLogCandidates:
    """Guess which column plays which event-log role, by name alone."""
    names = [column.name for column in columns]
    lowered = {name: name.lower() for name in names}
    picks: dict[str, str | None] = {
        role: _pick_role(names, lowered, role, hints) for role, hints in ROLE_HINTS.items()
    }
    return EventLogCandidates(**picks)


def merge_profile(
    frame: pd.DataFrame,
    columns: tuple[ColumnProfile, ...],
    guessed: EventLogCandidates,
    interpretation: ProfileInterpretation | None,
) -> ProfileReport:
    """Combine measured facts with model commentary.

    Facts win. The model may supply a meaning and may flag a column as personal,
    but it can never change a count.
    """
    meanings = interpretation.column_meanings if interpretation else {}
    extra_pii = set(interpretation.pii_columns) if interpretation else set()

    enriched = tuple(
        column.model_copy(
            update={
                "meaning": meanings.get(column.name, column.meaning),
                "is_pii_candidate": column.is_pii_candidate or column.name in extra_pii,
            }
        )
        for column in columns
    )
    roles = guessed
    if interpretation is not None and interpretation.eventlog_candidates.is_complete:
        roles = interpretation.eventlog_candidates

    total = len(frame.index)
    duplicates = int(frame.duplicated(keep="first").sum())
    return ProfileReport(
        row_count=total,
        column_count=len(columns),
        columns=enriched,
        duplicate_rows=duplicates,
        duplicate_rows_pct=0.0 if total == 0 else round(100.0 * duplicates / total, 2),
        pii_flags=tuple(sorted(column.name for column in enriched if column.is_pii_candidate)),
        eventlog_candidates=roles,
        observations=tuple(interpretation.observations) if interpretation else (),
    )


def build_interpretation_request(
    frame: pd.DataFrame, columns: tuple[ColumnProfile, ...]
) -> LlmRequest:
    """Build the one question A2 is allowed to ask.

    The payload is whatever build_llm_sample permits and nothing more: schema,
    aggregate statistics, and at most twenty masked sample rows.
    """
    pii_columns = [column.name for column in columns if column.is_pii_candidate]
    sample = build_llm_sample(frame, pii_columns=pii_columns)
    return LlmRequest(
        purpose="a2_profiler_interpret",
        system=load_prompt("a2_profiler_interpret"),
        prompt=json.dumps(sample, ensure_ascii=False, indent=2, sort_keys=True),
        schema=ProfileInterpretation,
    )


class ProfilerAgent(BaseAgent):
    """Describes a staged table and writes the report into profile://."""

    agent_id: ClassVar[str] = "a2_profiler"

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

    def build_report(self, frame: pd.DataFrame) -> ProfileReport:
        """Profile a frame end to end, with commentary when a model is available."""
        columns = profile_columns(frame)
        guessed = guess_roles(columns)
        interpretation: ProfileInterpretation | None = None
        if self._llm is not None:
            answer = self._llm.complete(build_interpretation_request(frame, columns))
            if isinstance(answer.data, ProfileInterpretation):
                interpretation = answer.data
        return merge_profile(frame, columns, guessed, interpretation)

    def execute(self, request: TaskRequest, files: ScopedStorage) -> TaskResult:
        """Profile the input reference and write the report."""
        # By format, not by position: a plan may legitimately hand this agent
        # several inputs, and which one arrived first is not a fact about which
        # one is the table.
        source = first_of(request.input_refs, "parquet")
        if source is None:
            return TaskResult(
                task_id=request.scope.task_id,
                agent_id=self.agent_id,
                status="FAILED",
                error=ErrorDetail(
                    code="NO_INPUT",
                    message="A2 can mot bang (parquet) de mo ta.",
                ),
            )
        frame = files.load_parquet(source.path)
        report = self.build_report(frame)
        target = str(request.scope.params.get(TARGET_PARAM) or "") or profile_uri_for(
            request.scope.run_id
        )
        written = files.save_text(report.model_dump_json(indent=2), target)
        return TaskResult(
            task_id=request.scope.task_id,
            agent_id=self.agent_id,
            status="OK",
            output_refs=(written,),
            metrics={
                "rows_in": float(report.row_count),
                "columns": float(report.column_count),
                "pii_columns": float(len(report.pii_flags)),
            },
            payload=report.model_dump(mode="json"),
        )
