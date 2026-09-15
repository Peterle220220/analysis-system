"""Digging: comparing one part of a process against another.

Measuring a process tells you it takes 97 hours. It does not tell you anything
you can act on. The question that follows is always the same shape - *which
part of it is slow, and what does the fast part do differently* - and answering
it means splitting the cases and comparing.

This module does the splitting. Three pieces:

* **Which columns describe a case.** Discovered rather than declared. A column
  that holds one value throughout a case describes that case - a channel, a
  department, a responsible officer - and those are the things worth comparing
  by. A column that changes within a case describes an event, and grouping case
  durations by it means nothing. Nobody should have to write that list by hand:
  the system can see it, and a system that has to be told what its data contains
  is a system that only answers questions somebody already knew to ask.

* **Breaking every measurement down by one of them.** How long does each channel
  take, how much rework does each department have.

* **Decomposing the gap.** The part that actually answers "why". Knowing postal
  takes 97 hours and internet takes 0.5 says nothing about what to change;
  knowing that a third of the difference sits in one handover does.

What is deliberately absent is any statement about *why* a difference exists or
what to do about it. Both are judgements, and the numbers here support them
without making them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

import pandas as pd

from analysis_system.domains.execution_engine.process_mining import (
    DECIMALS,
    HOUR_SECONDS,
    EventLogSpec,
    ProcessMiningError,
    _slug,
    order_events,
)
from analysis_system.models.agents import MetricValue

# A cohort smaller than this cannot be compared with anything: the difference
# between two medians of four cases is noise wearing a decimal point.
MIN_COHORT: Final[int] = 15
# More values than this and the column identifies cases rather than grouping
# them. Breaking a process down by case id produces one group per case.
MAX_ATTRIBUTE_VALUES: Final[int] = 25
# How many handovers of the gap to report. Beyond this the tail is noise.
TOP_GAP_STEPS: Final[int] = 8


def _round(value: float) -> float:
    """One rounding rule, so two runs agree to the last digit."""
    return round(float(value), DECIMALS)


@dataclass(frozen=True)
class Attribute:
    """A column that describes a case rather than an event."""

    name: str
    values: int
    detail: str = ""

    @property
    def key(self) -> str:
        """The fragment this attribute contributes to a metric key."""
        return _slug(self.name)


def case_attributes(frame: pd.DataFrame, spec: EventLogSpec) -> list[Attribute]:
    """Columns that hold one value throughout a case, and so describe it.

    Discovered, not declared. A channel, a department, a responsible officer -
    each is constant for the whole case, and those are the things a process can
    meaningfully be compared by. An activity or a timestamp changes within the
    case; grouping case durations by one of those is arithmetic about nothing.

    Args:
        frame: the event log. It is never modified.
        spec: which columns already play a role.

    Returns:
        The comparable attributes, in a fixed order, most selective last.
    """
    if spec.case_id not in frame.columns:
        raise ProcessMiningError(f"khong co cot {spec.case_id!r} de xac dinh case.")

    taken = set(spec.columns())
    found: list[Attribute] = []
    grouped = frame.groupby(spec.case_id, sort=True)
    for name in sorted(str(column) for column in frame.columns):
        if name in taken:
            continue
        column = frame[name]
        if column.isna().all():
            continue
        # One value per case throughout, or it is describing events, not cases.
        if int(grouped[name].nunique(dropna=False).max()) > 1:
            continue
        distinct = int(column.nunique(dropna=True))
        if distinct < 2 or distinct > MAX_ATTRIBUTE_VALUES:
            # One value tells nothing apart; too many and it is an identifier.
            continue
        found.append(
            Attribute(
                name=name, values=distinct, detail=f"{distinct} gia tri, khong doi trong case"
            )
        )
    return found


def _case_table(frame: pd.DataFrame, spec: EventLogSpec) -> pd.DataFrame:
    """One row per case: how long it took, how many steps, whether it repeated."""
    ordered, _ = order_events(frame, spec)
    if ordered.empty:
        return ordered

    grouped = ordered.groupby(spec.case_id, sort=True)
    table = pd.DataFrame({"events": grouped.size()})
    if "_ts" in ordered.columns:
        spans = grouped["_ts"].agg(["min", "max"])
        table["hours"] = (spans["max"] - spans["min"]).dt.total_seconds() / HOUR_SECONDS
        table.loc[table["hours"] < 0, "hours"] = pd.NA

    traces = grouped[spec.activity].apply(lambda values: tuple(str(value) for value in values))
    table["repeated"] = traces.apply(lambda trace: len(set(trace)) < len(trace))
    table["trace"] = traces
    return table


@dataclass
class _Result:
    metrics: dict[str, MetricValue] = field(default_factory=dict)

    def add(self, key: str, value: float, unit: str, source: str) -> None:
        self.metrics[key] = MetricValue(key=key, value=_round(value), unit=unit, source=source)


@dataclass(frozen=True)
class GapStep:
    """One handover, and how much of the difference between two groups sits there."""

    rank: int
    source: str
    target: str
    focus_hours_per_case: float
    other_hours_per_case: float
    gap_hours_per_case: float
    share_of_gap_pct: float

    @property
    def key(self) -> str:
        """The metric key fragment for this step of the gap."""
        return f"{_slug(self.source)}__to__{_slug(self.target)}"


@dataclass(frozen=True)
class Comparison:
    """What separates one group of cases from another, and where."""

    attribute: str
    focus: str
    other: str
    focus_cases: int
    other_cases: int
    metrics: dict[str, MetricValue] = field(default_factory=dict)
    steps: tuple[GapStep, ...] = ()
    refused: tuple[str, ...] = ()

    def as_context(self) -> list[dict[str, Any]]:
        """The named differences, in the shape a prompt can carry.

        Numbers stay behind keys. What travels is which handover, so a claim can
        say where the difference is without typing how large it is.
        """
        return [
            {
                "kind": "gap",
                "rank": step.rank,
                "from": step.source,
                "to": step.target,
                "gap_key": f"process.gap.{step.key}.hours_per_case",
                "share_key": f"process.gap.{step.key}.share_pct",
            }
            for step in self.steps
        ]


def _waits(frame: pd.DataFrame, spec: EventLogSpec) -> pd.DataFrame:
    """Every handover with the hours the work waited there."""
    ordered, _ = order_events(frame, spec)
    if ordered.empty or "_ts" not in ordered.columns:
        return pd.DataFrame()

    work = ordered[[spec.case_id, spec.activity, "_ts"]].copy()
    grouped = work.groupby(spec.case_id, sort=True)
    work["_next"] = grouped[spec.activity].shift(-1)
    work["_next_ts"] = grouped["_ts"].shift(-1)
    steps = work.dropna(subset=["_next", "_next_ts"]).copy()
    if steps.empty:
        return pd.DataFrame()
    steps["_wait"] = (steps["_next_ts"] - steps["_ts"]).dt.total_seconds() / HOUR_SECONDS
    return steps[steps["_wait"] >= 0]


def compare_cohorts(
    frame: pd.DataFrame,
    spec: EventLogSpec,
    attribute: str,
    focus: str,
    against: str = "",
) -> Comparison:
    """Where the difference between two groups of cases actually sits.

    The question this exists for is the one that follows every comparison:
    postal takes 97 hours and internet takes half an hour - *so what do I
    change?* Knowing the totals answers nothing. Knowing that a third of the
    difference sits in one handover, and that another tenth sits in a correction
    step the fast group rarely reaches, is something a person can act on.

    Per case rather than in total, because the groups are different sizes and a
    bigger group waits more hours simply by being bigger.

    Args:
        frame: the event log. It is never modified.
        spec: which columns play which role.
        attribute: the case-level column to split on.
        focus: the value being investigated.
        against: what to compare it with. Empty means everything else.

    Returns:
        The comparison, including what it would not claim.

    Raises:
        ProcessMiningError: the column is not there.
    """
    if attribute not in frame.columns:
        raise ProcessMiningError(f"khong co cot {attribute!r} de so sanh.")

    values = frame.groupby(spec.case_id, sort=True)[attribute].first().astype(str)
    focus_cases = set(values[values == focus].index)
    other_cases = (
        set(values[values == against].index) if against else set(values.index) - focus_cases
    )
    other_name = against or f"con lai ({attribute})"

    refused: list[str] = []
    if len(focus_cases) < MIN_COHORT or len(other_cases) < MIN_COHORT:
        return Comparison(
            attribute=attribute,
            focus=focus,
            other=other_name,
            focus_cases=len(focus_cases),
            other_cases=len(other_cases),
            refused=(
                f"mot trong hai nhom duoi {MIN_COHORT} case "
                f"({focus}={len(focus_cases)}, {other_name}={len(other_cases)}) - "
                "chenh lech giua hai trung vi tren so nay la nhieu.",
            ),
        )

    steps = _waits(frame, spec)
    if steps.empty:
        return Comparison(
            attribute=attribute,
            focus=focus,
            other=other_name,
            focus_cases=len(focus_cases),
            other_cases=len(other_cases),
            refused=("khong do duoc thoi gian cho - khong co cot thoi gian dung duoc.",),
        )

    per_case: dict[str, pd.Series[Any]] = {}
    for label, cases in (("focus", focus_cases), ("other", other_cases)):
        part = steps[steps[spec.case_id].isin(cases)]
        totals = part.groupby([spec.activity, "_next"], sort=True)["_wait"].sum()
        per_case[label] = totals / max(len(cases), 1)

    combined = pd.DataFrame({"focus": per_case["focus"], "other": per_case["other"]}).fillna(0.0)
    combined["gap"] = combined["focus"] - combined["other"]
    positive = float(combined.loc[combined["gap"] > 0, "gap"].sum())

    out = _Result()
    out.add("process.gap.total_hours_per_case", positive, "giờ", "gap")
    out.add(f"process.cases.by.{_slug(attribute)}.{_slug(focus)}", len(focus_cases), "case", "gap")

    ranked = combined.sort_values(["gap"], ascending=False, kind="mergesort")
    found: list[GapStep] = []
    for rank, (pair, row) in enumerate(ranked.head(TOP_GAP_STEPS).iterrows(), start=1):
        if float(row["gap"]) <= 0:
            break
        # The index is the (activity, next activity) pair the group was built on.
        names: tuple[Any, ...] = pair  # type: ignore[assignment]
        source, target = str(names[0]), str(names[1])
        step = GapStep(
            rank=rank,
            source=source,
            target=target,
            focus_hours_per_case=_round(float(row["focus"])),
            other_hours_per_case=_round(float(row["other"])),
            gap_hours_per_case=_round(float(row["gap"])),
            share_of_gap_pct=_round(100.0 * float(row["gap"]) / positive) if positive else 0.0,
        )
        found.append(step)
        out.add(f"process.gap.{step.key}.hours_per_case", step.gap_hours_per_case, "giờ", "gap")
        out.add(f"process.gap.{step.key}.share_pct", step.share_of_gap_pct, "%", "gap")
        out.add(
            f"process.gap.{step.key}.focus_hours_per_case",
            step.focus_hours_per_case,
            "gio",
            "gap",
        )

    if not found:
        refused.append(f"{focus} khong cham hon {other_name} o buoc ban giao nao.")

    return Comparison(
        attribute=attribute,
        focus=focus,
        other=other_name,
        focus_cases=len(focus_cases),
        other_cases=len(other_cases),
        metrics=out.metrics,
        steps=tuple(found),
        refused=tuple(refused),
    )
