"""Which chart suits this data, ranked, with the reason for each.

Choosing a chart is not decoration. The wrong shape hides the thing worth seeing:
two groups with the same average look identical as bars and nothing alike as
boxes; a correlation of 0.3 is a weak straight line or a strong curved one and
only a scatter plot can tell you which. A system that picks a bar chart for
everything is not illustrating an argument, it is decorating one.

So the choice is made from what the data *is* - what was measured, what shape the
columns have - and every suggestion carries the reason it was made. A ranking
without reasons is an opinion; with them it is something a person can disagree
with, which is the point.

Code, not a model. Which column holds numbers and how many groups a category has
are measurements, and a model asked to rank charts would produce a plausible
ranking that varies between runs.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

import pandas as pd

from analysis_system.domains.visualization.charts import (
    HORIZONTAL_ABOVE,
    LONG_LABEL,
    MAX_CATEGORIES,
    ChartSpec,
)

# How well each shape fits, before the data adjusts it. A scatter plot for a
# correlation is the only honest picture of one, so it starts highest.
BASE_SCORE: Final[dict[str, float]] = {
    "scatter": 0.90,
    "box": 0.85,
    "hbar": 0.80,
    "grouped_bar": 0.78,
    "heatmap": 0.75,
    "line": 0.72,
    "bar": 0.70,
}
# Below this a suggestion is not worth making.
MIN_SCORE: Final[float] = 0.35
MAX_SUGGESTIONS: Final[int] = 6
# How many of any single kind may appear. The point of ranking chart types
# is to offer different ways of seeing; six views of the same shape is one
# view, and the shapes that would have shown something else never appear.
MAX_PER_KIND: Final[int] = 2
# Fewer correlated pairs than this and a heat map is a table with colours.
MIN_HEATMAP_COLUMNS: Final[int] = 3


@dataclass(frozen=True)
class Suggestion:
    """One chart worth drawing, and why it is worth drawing."""

    rank: int
    kind: str
    score: float
    reason: str
    spec: ChartSpec

    def as_row(self) -> dict[str, Any]:
        """The suggestion in the shape a listing or a prompt can carry."""
        return {
            "rank": self.rank,
            "kind": self.kind,
            "title": self.spec.title,
            "reason": self.reason,
            "sources": list(self.spec.sources()),
        }


def _numeric_columns(frame: pd.DataFrame | None) -> list[str]:
    """Columns holding numbers that vary, in a fixed order."""
    if frame is None:
        return []
    found: list[str] = []
    for name in sorted(str(column) for column in frame.columns):
        values = pd.to_numeric(frame[name], errors="coerce").dropna()
        if len(values) > 1 and int(values.nunique()) > 1:
            found.append(name)
    return found


def _grouping_columns(frame: pd.DataFrame | None) -> list[str]:
    """Columns holding a handful of repeated values, in a fixed order."""
    if frame is None:
        return []
    rows = len(frame.index)
    found: list[str] = []
    for name in sorted(str(column) for column in frame.columns):
        values = frame[name].dropna()
        if values.empty or pd.to_numeric(values, errors="coerce").notna().all():
            continue
        distinct = int(values.nunique())
        if 2 <= distinct <= MAX_CATEGORIES and distinct < rows:
            found.append(name)
    return found


def _families(metrics: Mapping[str, Any], marker: str) -> list[str]:
    """Every metric key belonging to one family, sorted."""
    return sorted(key for key in metrics if marker in key)


def _bar_or_hbar(labels: int, longest: int) -> tuple[str, str]:
    """Upright or on its side, and why.

    Past a certain number of bars, or with labels past a certain length, an
    upright chart puts its own labels on top of each other. That is not a matter
    of taste - the chart stops being readable.
    """
    if labels > HORIZONTAL_ABOVE:
        return "hbar", f"co {labels} cot, dung dung thi nhan chong len nhau"
    if longest > LONG_LABEL:
        return "hbar", "nhan dai, de nam ngang thi doc duoc"
    return "bar", "it cot va nhan ngan, de dung cho de so sanh chieu cao"


def suggest_charts(
    metrics: Mapping[str, Any],
    frame: pd.DataFrame | None = None,
    *,
    limit: int = MAX_SUGGESTIONS,
    diverse: bool = True,
) -> list[Suggestion]:
    """Which charts suit what was measured here, best first.

    Args:
        metrics: the named values that were computed.
        frame: the table, when a chart needs the values behind the numbers -
            a scatter plot and a box plot cannot be drawn from summaries.
        limit: how many suggestions to return.

    Returns:
        Suggestions ranked by how well the shape fits, each carrying its reason.
        Empty when nothing measured here suits a picture, which is a real answer
        and better than a bar chart of one bar.
    """
    numeric = _numeric_columns(frame)
    grouping = _grouping_columns(frame)
    found: list[tuple[float, str, str, ChartSpec]] = []

    # A correlation, shown the only honest way.
    for key in _families(metrics, ".corr.with."):
        if key.endswith((".p_value", ".n", ".r2")):
            continue
        left, _, rest = key.partition(".corr.with.")
        right = rest.split(".")[0]
        if left in numeric and right in numeric:
            found.append(
                (
                    BASE_SCORE["scatter"],
                    "scatter",
                    "he so tuong quan mot minh khong noi duoc quan he la thang hay cong - "
                    "phai nhin dam may diem",
                    ChartSpec(
                        kind="scatter",
                        title=f"{left} va {right}",
                        columns=(left, right),
                        x_label=left,
                        y_label=right,
                    ),
                )
            )

    # A group comparison, showing the spread rather than two averages.
    # Keyed on the p-value alone: a t-test contributes several metrics and each
    # would otherwise suggest the same box plot over again.
    for key in _families(metrics, ".ttest.by."):
        if not key.endswith(".p_value"):
            continue
        measure = key.split(".")[0]
        dimension = key.split(".ttest.by.")[-1].split(".")[0]
        if measure in numeric and dimension in grouping:
            found.append(
                (
                    BASE_SCORE["box"],
                    "box",
                    "hai nhom cung trung binh van co the khac han nhau - hop cho thay do tan",
                    ChartSpec(
                        kind="box",
                        title=f"{measure} theo {dimension}",
                        columns=(measure,),
                        group_by=dimension,
                        y_label=measure,
                    ),
                )
            )

    # How every measure moves with every other, at a glance.
    if len(numeric) >= MIN_HEATMAP_COLUMNS and _families(metrics, ".corr.with."):
        found.append(
            (
                BASE_SCORE["heatmap"],
                "heatmap",
                f"co {len(numeric)} cot so - ma tran nhiet cho thay tat ca cac cap cung luc, "
                "thay vi tung bieu do roi",
                ChartSpec(
                    kind="heatmap",
                    title="Tuong quan giua cac chi so",
                    columns=tuple(numeric[:8]),
                ),
            )
        )

    # Shares of a whole, and gaps between two groups: both are one number per
    # label, which is what a bar chart is for.
    for marker, title, why in (
        (".share_pct", "Ty trong", "ty trong theo nhom la mot so tren moi nhan"),
        (".hours_per_case", "Khoang cach theo buoc", "khoang cach chia theo tung buoc"),
    ):
        keys = [
            key for key in _families(metrics, marker) if not key.endswith(".total_hours_per_case")
        ]
        if len(keys) < 2:
            continue
        longest = max(len(key) for key in keys)
        kind, why_shape = _bar_or_hbar(len(keys), longest)
        found.append(
            (
                BASE_SCORE[kind],
                kind,
                f"{why}; {why_shape}",
                ChartSpec(kind=kind, title=title, metric_keys=tuple(keys[:MAX_CATEGORIES])),
            )
        )

    ranked = sorted(found, key=lambda item: (-item[0], item[1], item[3].title))

    # Best first, but no kind may crowd the others out. A second scatter plot is
    # worth more than a third; a first box plot is worth more than either.
    taken: dict[str, int] = {}
    chosen: list[tuple[float, str, str, ChartSpec]] = []
    for entry in ranked:
        score, kind, _, _ = entry
        if score < MIN_SCORE or (diverse and taken.get(kind, 0) >= MAX_PER_KIND):
            continue
        taken[kind] = taken.get(kind, 0) + 1
        chosen.append(entry)
        if len(chosen) >= limit:
            break

    return [
        Suggestion(rank=rank, kind=kind, score=round(score, 2), reason=reason, spec=spec)
        for rank, (score, kind, reason, spec) in enumerate(chosen, start=1)
    ]


def _all_candidates(metrics: Mapping[str, Any], frame: pd.DataFrame | None) -> list[Suggestion]:
    """Every chart that could be drawn, without the variety cap."""
    return suggest_charts(metrics, frame, limit=10_000, diverse=False)


def suggestion_for(
    metric_keys: tuple[str, ...],
    metrics: Mapping[str, Any],
    frame: pd.DataFrame | None = None,
) -> Suggestion | None:
    """The best chart for one particular claim, if any suits it.

    A claim resting on a single number has no picture worth drawing, and forcing
    one would produce a bar chart of one bar - which shows nothing and looks like
    it does.
    """
    wanted = set(metric_keys)
    # Every part of every key the claim rests on. Whole segments, not substrings:
    # `grade` must not match `previous_grade`.
    named: set[str] = set()
    for key in wanted:
        named.update(part for part in key.split(".") if part)

    # Every candidate, not the diverse shortlist: the chart that backs *this*
    # claim may well be the third scatter plot, which the shortlist drops for
    # variety. Variety is right when offering choices and wrong when finding
    # evidence for one particular sentence.
    for suggestion in _all_candidates(metrics, frame):
        if wanted & set(suggestion.spec.metric_keys):
            return suggestion
        # ALL of what the chart draws, not any of it. A scatter of attendance
        # against score shares `score` with a claim about study time and score,
        # and matching on that put a chart of neither beside both.
        drawn = {
            *suggestion.spec.columns,
            *((suggestion.spec.group_by,) if suggestion.spec.group_by else ()),
        }
        if drawn and drawn <= named:
            return suggestion
    return None
