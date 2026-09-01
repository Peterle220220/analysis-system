"""Inferential statistics, as named metrics that a claim may cite.

The anti-hallucination machinery works on named values: the model writes
{key} and code substitutes. So adding inference means adding metrics, not
changing anything about how a claim is checked. A correlation coefficient is
just another number code computed and named.

**The refusals matter more than the tests.** Most tools will happily compute a
p-value from eleven rows, or from a group whose values are all identical, and
report it with three decimal places. Every test here states what it needs, and
declines when it does not have it - with a reason recorded, in the same way a
finding that types its own digits is rejected rather than repaired.

Two things are deliberately absent:

* **No prediction.** A predicted value traces back to a model, a training set
  and a random seed - not to rows of data. Criterion S4 asks a conclusion to be
  traceable, and that would need a different answer than the one this system
  gives, so it is a decision to be taken rather than a feature to slip in.
* **No causal claim.** Every key here says what was measured - `corr`, `ttest`,
  `anova` - and never says why. Turning association into cause is a judgement,
  and the guard in `findings.py` refuses to let a model make it in passing.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Final

import pandas as pd
from scipy import stats

from analysis_system.contracts.agents import MetricValue

# Below this a test is not weak, it is meaningless: three points can be fitted
# by anything, and a p-value computed from them says nothing about a population.
MIN_SAMPLE: Final[int] = 8
# A two-group comparison needs enough in *each* group, not enough overall.
MIN_GROUP: Final[int] = 5
# More groups than this and the categories are identifiers, not categories.
MAX_GROUPS: Final[int] = 20
DECIMALS: Final[int] = 4


class StatisticsError(ValueError):
    """A test was asked for in a way that cannot be carried out."""


@dataclass(frozen=True)
class StatisticsSpec:
    """Which tests to run, declared by the task rather than guessed at."""

    correlations: tuple[tuple[str, str], ...] = ()
    group_differences: tuple[tuple[str, str], ...] = ()

    @classmethod
    def from_params(cls, raw: Any) -> StatisticsSpec:
        """Read a spec out of scope params, refusing anything malformed.

        Raises:
            StatisticsError: the spec is not shaped like a spec. Guessing what
                was meant would mean running a test nobody asked for.
        """
        if not isinstance(raw, dict):
            raise StatisticsError("tham so 'tests' phai la mot object.")
        return cls(
            correlations=tuple(_pairs(raw.get("correlations"), "correlations")),
            group_differences=tuple(_pairs(raw.get("group_differences"), "group_differences")),
        )


def _pairs(raw: Any, field_name: str) -> list[tuple[str, str]]:
    """Read a list of two-name pairs."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise StatisticsError(f"'{field_name}' phai la mot danh sach cap.")
    found: list[tuple[str, str]] = []
    for entry in raw:
        if not isinstance(entry, list | tuple) or len(entry) != 2:
            raise StatisticsError(f"'{field_name}' moi muc phai la mot cap hai ten cot.")
        found.append((str(entry[0]), str(entry[1])))
    return found


@dataclass
class _Result:
    metrics: dict[str, MetricValue] = field(default_factory=dict)
    refused: list[str] = field(default_factory=list)

    def add(self, key: str, value: float, unit: str, source: str) -> None:
        self.metrics[key] = MetricValue(
            key=key, value=round(float(value), DECIMALS), unit=unit, source=source
        )


def compute_statistics(
    frame: pd.DataFrame, spec: StatisticsSpec
) -> tuple[dict[str, MetricValue], list[str]]:
    """Run the declared tests, and say which ones could not honestly be run.

    Returns:
        The metrics produced, and one line per test declined. A declined test is
        reported, never omitted in silence: an absent number and a number nobody
        was told about look identical from the outside.
    """
    result = _Result()
    for left, right in spec.correlations:
        _correlate(frame, left, right, result)
    for measure, dimension in spec.group_differences:
        _compare_groups(frame, measure, dimension, result)
    return result.metrics, result.refused


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series[Any] | None:
    """The column as numbers, or None when it is not one."""
    if column not in frame.columns:
        return None
    converted = pd.to_numeric(frame[column], errors="coerce")
    return None if converted.notna().sum() == 0 else converted


def _correlate(frame: pd.DataFrame, left: str, right: str, out: _Result) -> None:
    """Correlation between two numeric columns, when both hold enough numbers."""
    label = f"{left} ~ {right}"
    first, second = _numeric(frame, left), _numeric(frame, right)
    if first is None or second is None:
        out.refused.append(f"{label}: khong phai ca hai deu la cot so")
        return

    paired = pd.DataFrame({"a": first, "b": second}).dropna()
    if len(paired) < MIN_SAMPLE:
        out.refused.append(f"{label}: chi {len(paired)} cap du lieu, can it nhat {MIN_SAMPLE}")
        return
    if paired["a"].nunique() < 2 or paired["b"].nunique() < 2:
        out.refused.append(f"{label}: mot trong hai cot khong doi, khong co gi de tuong quan")
        return

    pearson = stats.pearsonr(paired["a"], paired["b"])
    spearman = stats.spearmanr(paired["a"], paired["b"])
    source = f"{left} va {right}"

    out.add(f"{left}.corr.with.{right}", float(pearson.statistic), "", source)
    out.add(f"{left}.corr.with.{right}.p_value", float(pearson.pvalue), "", source)
    # Spearman as well, because Pearson only sees straight lines and a monotone
    # relationship that bends would otherwise look weaker than it is.
    out.add(f"{left}.rank_corr.with.{right}", float(spearman.statistic), "", source)
    out.add(f"{left}.corr.with.{right}.n", float(len(paired)), "cap", source)
    out.add(
        f"{left}.r2.with.{right}",
        float(pearson.statistic) ** 2 * 100.0,
        "%",
        f"phan bien thien chung cua {left} va {right}",
    )


def _compare_groups(frame: pd.DataFrame, measure: str, dimension: str, out: _Result) -> None:
    """Whether a measure differs across the groups of a dimension."""
    label = f"{measure} theo {dimension}"
    numbers = _numeric(frame, measure)
    if numbers is None:
        out.refused.append(f"{label}: '{measure}' khong phai cot so")
        return
    if dimension not in frame.columns:
        out.refused.append(f"{label}: khong co cot '{dimension}'")
        return

    paired = pd.DataFrame({"value": numbers, "group": frame[dimension].astype(str)}).dropna()
    groups: list[tuple[str, pd.Series[Any]]] = [
        (str(name), subset["value"])
        for name, subset in paired.groupby("group", sort=True)
        if len(subset) >= MIN_GROUP
    ]
    dropped = paired["group"].nunique() - len(groups)
    if dropped > 0:
        out.refused.append(
            f"{label}: bo qua {dropped} nhom co duoi {MIN_GROUP} dong - qua it de noi gi"
        )
    if len(groups) < 2:
        out.refused.append(f"{label}: con duoi hai nhom du lon, khong so sanh duoc")
        return
    if len(groups) > MAX_GROUPS:
        out.refused.append(f"{label}: {len(groups)} nhom - day la dinh danh, khong phai phan loai")
        return

    samples = [values for _, values in groups]
    if any(values.nunique() < 2 for values in samples):
        out.refused.append(f"{label}: co nhom khong doi gia tri nao")
        return

    if len(groups) == 2:
        _two_groups(measure, dimension, groups, out)
    else:
        _many_groups(measure, dimension, samples, len(groups), out)


def _two_groups(
    measure: str,
    dimension: str,
    groups: Sequence[tuple[str, pd.Series[Any]]],
    out: _Result,
) -> None:
    """Two groups: Welch's t-test, plus the size of the gap it found."""
    (first_name, first), (second_name, second) = groups[0], groups[1]
    source = f"{measure} giua {first_name} va {second_name}"
    # Welch rather than Student: it does not assume the two groups vary equally,
    # and assuming that when it is untrue is the commonest way this test lies.
    outcome = stats.ttest_ind(first, second, equal_var=False)

    out.add(f"{measure}.ttest.by.{dimension}.p_value", float(outcome.pvalue), "", source)
    out.add(f"{measure}.ttest.by.{dimension}.t_stat", float(outcome.statistic), "", source)
    out.add(
        f"{measure}.diff.by.{dimension}",
        float(first.mean() - second.mean()),
        "",
        source,
    )
    out.add(f"{measure}.ttest.by.{dimension}.n", float(len(first) + len(second)), "dong", source)

    # Effect size, because with a thousand rows almost any gap is "significant"
    # and only its size says whether it matters.
    pooled = (
        ((len(first) - 1) * first.var() + (len(second) - 1) * second.var())
        / (len(first) + len(second) - 2)
    ) ** 0.5
    if pooled > 0:
        out.add(
            f"{measure}.effect_size.by.{dimension}",
            float((first.mean() - second.mean()) / pooled),
            "",
            source,
        )


def _many_groups(
    measure: str,
    dimension: str,
    samples: Sequence[pd.Series[Any]],
    count: int,
    out: _Result,
) -> None:
    """Three groups or more: one-way ANOVA, and how much of the spread it explains."""
    source = f"{measure} qua {count} nhom cua {dimension}"
    outcome = stats.f_oneway(*samples)
    out.add(f"{measure}.anova.by.{dimension}.p_value", float(outcome.pvalue), "", source)
    out.add(f"{measure}.anova.by.{dimension}.f_stat", float(outcome.statistic), "", source)
    out.add(f"{measure}.anova.by.{dimension}.groups", float(count), "nhom", source)

    combined = pd.concat(list(samples))
    grand = combined.mean()
    between = sum(len(values) * (values.mean() - grand) ** 2 for values in samples)
    total = float(((combined - grand) ** 2).sum())
    if total > 0:
        # eta squared: the share of the variation that lies between groups
        # rather than inside them. A tiny p-value with a tiny eta squared means
        # a real difference nobody should act on.
        out.add(f"{measure}.eta_sq.by.{dimension}", 100.0 * float(between) / total, "%", source)


__all__ = [
    "MAX_GROUPS",
    "MIN_GROUP",
    "MIN_SAMPLE",
    "StatisticsError",
    "StatisticsSpec",
    "compute_statistics",
]
