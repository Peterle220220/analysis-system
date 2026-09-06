"""Every number the analysis is allowed to state, computed here in code.

The spec forbids A7 from producing a figure that is not in its input metrics,
and leaves open how to enforce that. Extracting numbers back out of prose and
comparing them is the obvious approach and a bad one: 4.8 and 4,8 and 4.80 are
the same number written three ways, a rounded figure is neither equal nor wrong,
and a derived number like "12% of total" appears nowhere in the inputs.

So the numbers never enter the prose in the first place. This module computes a
named set of values; the model writes sentences containing placeholders like
{price.mean}; code substitutes the real figures afterwards. A number the model
invented has nowhere to live, because a claim carrying a bare digit is rejected
before it is ever rendered.

Keys are built from column and value names and are stable across runs, so the
same table always produces the same key set.
"""

from __future__ import annotations

import math
from typing import Any, Final

import pandas as pd

from analysis_system.contracts.agents import MetricValue

# How many values of a dimension get their own metrics.
#
# This was five, and a question that asked for a count of every emotion label
# got five of the six back - `surprise`, the smallest at 572 rows, had no
# metric at all, so no claim could mention it and nothing said it was missing.
# A list that silently omits a member is worse than a refusal.
#
# Twenty, because that is already what the rest of the system calls a grouping:
# the statistics layer refuses a breakdown past twenty groups, and the analyst
# only offers a column as a dimension below the same line. A column that counts
# as groupable everywhere else should not be summarised down to its top five
# here.
TOP_VALUES: Final[int] = 20
NUMERIC_SHARE_REQUIRED: Final[float] = 0.9
ROUNDING: Final[int] = 4


def _clean_key(text: str) -> str:
    """Make a value safe to use inside a metric key."""
    return "".join(char if char.isalnum() or char in "_-" else "_" for char in str(text))[:40]


def _numeric(series: pd.Series[Any]) -> pd.Series[Any] | None:
    """The column as numbers, when nearly all of it parses as one."""
    present = series.dropna()
    if present.empty:
        return None
    parsed = pd.to_numeric(present, errors="coerce")
    if float(parsed.notna().sum()) / float(len(present)) < NUMERIC_SHARE_REQUIRED:
        return None
    return parsed.dropna()


def _round(value: float) -> float:
    """Round to a fixed precision so two runs agree to the last digit."""
    return 0.0 if math.isnan(value) else round(float(value), ROUNDING)


def compute_metrics(
    frame: pd.DataFrame,
    *,
    dimensions: tuple[str, ...] = (),
    measures: tuple[str, ...] = (),
    top_values: int = TOP_VALUES,
) -> dict[str, MetricValue]:
    """Compute the full set of values an analysis may quote.

    Args:
        frame: the mart table.
        dimensions: columns to break measures down by, such as city or vendor.
        measures: numeric columns to summarise. Empty means every column that
            looks numeric.
        top_values: how many values of each dimension to break down by.

    Returns:
        Metric key to value, in a stable order.
    """
    metrics: dict[str, MetricValue] = {}
    total = len(frame.index)
    metrics["rows.total"] = MetricValue(
        key="rows.total", value=float(total), unit="dòng", source="frame"
    )

    numeric_columns: dict[str, pd.Series[Any]] = {}
    for name in sorted(str(column) for column in frame.columns):
        numbers = _numeric(frame[name])
        if numbers is not None and (not measures or name in measures):
            numeric_columns[name] = numbers

    for name in sorted(str(column) for column in frame.columns):
        series = frame[name]
        non_null = int(series.notna().sum())
        metrics[f"{name}.distinct"] = MetricValue(
            key=f"{name}.distinct",
            value=float(series.nunique(dropna=True)),
            unit="gia tri",
            source=name,
        )
        metrics[f"{name}.null_pct"] = MetricValue(
            key=f"{name}.null_pct",
            value=_round(0.0 if total == 0 else 100.0 * (total - non_null) / total),
            unit="%",
            source=name,
        )

    for name, numbers in numeric_columns.items():
        for label, value in (
            ("sum", float(numbers.sum())),
            ("mean", float(numbers.mean())),
            ("median", float(numbers.median())),
            ("min", float(numbers.min())),
            ("max", float(numbers.max())),
        ):
            key = f"{name}.{label}"
            metrics[key] = MetricValue(key=key, value=_round(value), unit="", source=name)

    for dimension in dimensions:
        if dimension not in frame.columns:
            continue
        counts = frame[dimension].dropna().astype(str).value_counts()
        ordered = sorted(
            ((str(name), int(number)) for name, number in counts.items()),
            key=lambda item: (-item[1], item[0]),
        )
        # Past the cap the list is a top-N, not a breakdown. Say so as a metric
        # rather than leaving the reader to notice the tail is missing - which
        # is precisely what nobody did when it was five.
        left_out = max(0, len(ordered) - top_values)
        if left_out:
            key = f"{dimension}.categories_omitted"
            metrics[key] = MetricValue(
                key=key, value=float(left_out), unit="nhóm", source=dimension
            )

        for category, count in ordered[:top_values]:
            slug = _clean_key(category)
            metrics[f"{dimension}.{slug}.count"] = MetricValue(
                key=f"{dimension}.{slug}.count",
                value=float(count),
                unit="dòng",
                source=dimension,
            )
            metrics[f"{dimension}.{slug}.share_pct"] = MetricValue(
                key=f"{dimension}.{slug}.share_pct",
                value=_round(0.0 if total == 0 else 100.0 * count / total),
                unit="%",
                source=dimension,
            )
            for measure, numbers in numeric_columns.items():
                matching = frame[dimension].astype(str).reindex(numbers.index) == category
                subset = numbers[matching]
                if subset.empty:
                    continue
                key = f"{measure}.mean.by.{dimension}.{slug}"
                metrics[key] = MetricValue(
                    key=key,
                    value=_round(float(subset.mean())),
                    unit="",
                    source=f"{measure} theo {dimension}",
                )

    return metrics


def metric_catalogue(metrics: dict[str, MetricValue]) -> list[dict[str, Any]]:
    """The metric set as the model is shown it: keys, values and units."""
    return [
        {"key": metric.key, "value": metric.value, "unit": metric.unit, "source": metric.source}
        for metric in sorted(metrics.values(), key=lambda item: item.key)
    ]
