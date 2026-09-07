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

import numpy as np
import pandas as pd
from scipy import stats

from analysis_system.contracts.agents import MetricValue
from analysis_system.services.shortlist import named_in

# Below this a test is not weak, it is meaningless: three points can be fitted
# by anything, and a p-value computed from them says nothing about a population.
MIN_SAMPLE: Final[int] = 8
# A two-group comparison needs enough in *each* group, not enough overall.
MIN_GROUP: Final[int] = 5
# More groups than this and the categories are identifiers, not categories.
MAX_GROUPS: Final[int] = 20
# Ten dong moi bien giai thich. Duoi muc nay he so la so hoc chu khong phai
# thong tin: no se nhay lung tung tren mot bo du lieu chi khac di mot chut.
MIN_PER_PREDICTOR: Final[int] = 10
# Tren nguong nay mot bien da duoc cac bien khac ke gan het.
MAX_VIF: Final[float] = 10.0
# How many tests to propose when nobody declared any. Ten numeric columns make
# forty-five pairs, and forty-five p-values contain two below 0.05 by arithmetic
# alone. Capped, and the cap is always reported.
MAX_SUGGESTED: Final[int] = 8
# A column with more distinct values than this is not a grouping, it is a label.
MAX_SUGGESTED_GROUPS: Final[int] = 12
# How completely a whole-number column has to fill its own range before it is
# read as a counter rather than a measurement. An id runs 1, 2, 3 and fills its
# range; an exam score between 46.8 and 100 does not come close.
#
# "Nearly every value is different" would be the obvious rule and it is wrong
# here: a price, a duration, a temperature are all different on every row. That
# rule identifies a *text* column, not a numeric one.
IDENTIFIER_DENSITY: Final[float] = 0.95
DECIMALS: Final[int] = 4


class StatisticsError(ValueError):
    """A test was asked for in a way that cannot be carried out."""


@dataclass(frozen=True)
class StatisticsSpec:
    """Which tests to run, declared by the task rather than guessed at."""

    correlations: tuple[tuple[str, str], ...] = ()
    group_differences: tuple[tuple[str, str], ...] = ()
    regressions: tuple[tuple[str, tuple[str, ...]], ...] = ()

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
            regressions=tuple(_models(raw.get("regressions"))),
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


def _models(raw: Any) -> list[tuple[str, tuple[str, ...]]]:
    """Read the declared regressions: one outcome, several explanations."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise StatisticsError("'regressions' phai la mot danh sach.")
    found: list[tuple[str, tuple[str, ...]]] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict) or "outcome" not in entry or "predictors" not in entry:
            raise StatisticsError("'regressions' moi muc phai co 'outcome' va 'predictors'.")
        outcome = str(entry["outcome"])
        predictors = entry["predictors"]
        if not isinstance(predictors, list) or not predictors:
            raise StatisticsError(f"'predictors' cua {outcome!r} phai la danh sach khong rong.")
        if outcome in seen:
            # Two models for one outcome would write to the same metric keys and
            # the second would silently replace the first.
            raise StatisticsError(f"co hai mo hinh cung du doan {outcome!r}.")
        seen.add(outcome)
        found.append((outcome, tuple(str(name) for name in predictors)))
    return found


@dataclass
class _Result:
    metrics: dict[str, MetricValue] = field(default_factory=dict)
    refused: list[str] = field(default_factory=list)

    def add(self, key: str, value: float, unit: str, source: str) -> None:
        self.metrics[key] = MetricValue(
            key=key, value=round(float(value), DECIMALS), unit=unit, source=source
        )


def _is_counter(values: pd.Series[Any]) -> bool:
    """True when a numeric column looks like a row counter rather than a measure.

    Whole numbers, all different, and packed so tightly into their own range
    that there is almost nothing missing between the smallest and the largest.
    An id does that; a measurement does not.
    """
    numbers = values.dropna()
    if len(numbers) < 2 or int(numbers.nunique()) != len(numbers):
        return False
    if not bool((numbers % 1 == 0).all()):
        return False
    span = float(numbers.max()) - float(numbers.min()) + 1.0
    return span > 0 and len(numbers) / span >= IDENTIFIER_DENSITY


def _kinds(frame: pd.DataFrame) -> tuple[list[str], list[str]]:
    """Which columns hold numbers, and which hold a handful of repeated values.

    Measured rather than taken from the dtype: a column staged as text can still
    be a number, which is the usual case straight out of a CSV.
    """
    numeric: list[str] = []
    grouping: list[str] = []
    rows = len(frame.index)
    for name in sorted(str(column) for column in frame.columns):
        series = frame[name].dropna()
        if series.empty:
            continue
        parsed = pd.to_numeric(series, errors="coerce")
        if float(parsed.notna().sum()) / float(len(series)) >= 0.9:
            # A number that never changes explains nothing and correlates with
            # nothing; and a counter correlated with anything produces a figure
            # that means nothing but looks exactly like one that does.
            if int(parsed.nunique()) > 1 and not _is_counter(parsed):
                numeric.append(name)
            continue
        distinct = int(series.nunique())
        if 2 <= distinct <= MAX_SUGGESTED_GROUPS and distinct < rows:
            grouping.append(name)
    return numeric, grouping


def suggest_spec(
    frame: pd.DataFrame,
    *,
    dimensions: Sequence[str] = (),
    measures: Sequence[str] = (),
    question: str = "",
) -> tuple[StatisticsSpec, list[str]]:
    """Which tests are worth running here, when nobody said which.

    Asking a person to name the pair they want tested asks them to name the
    relationship they already suspect, and a tool that only measures what you
    already guessed is a calculator.

    Args:
        frame: the table. It is never modified.
        dimensions: groupings the task chose, if any. Narrows the search.
        measures: measures the task chose, if any. Narrows the search.
        question: what was actually asked. Pairs naming a column the question
            names go first, so the cap keeps the tests somebody wanted rather
            than the ones that happened to sort early. `Invest_Monitor` by
            `Avenue` and `Duration` by `Expect` were both asked for and both
            fell outside the first eight - so the number never existed, and the
            Manager honestly reported it could not compare them.

    Returns:
        The proposed tests, and one note per decision that shaped the list -
        including the cap, because a truncated search that does not say it was
        truncated is worse than a small one.
    """
    numeric, grouping = _kinds(frame)
    if measures:
        numeric = [name for name in numeric if name in set(measures)]
    if dimensions:
        grouping = [name for name in grouping if name in set(dimensions)]

    notes: list[str] = []
    # Ordered by how far apart the two columns sit, not alphabetically. Sorting
    # by name meant the cap took every pair beginning with the first column and
    # nothing else - one column tested against everything, every other column
    # tested against nothing. Spacing them spreads the cap across the table
    # while staying completely deterministic.
    correlations = [
        (numeric[index], numeric[index + step])
        for step in range(1, len(numeric))
        for index in range(len(numeric) - step)
    ]
    differences = (
        [
            (numeric[measure], grouping[(measure + step) % len(grouping)])
            for step in range(len(grouping))
            for measure in range(len(numeric))
        ]
        if numeric and grouping
        else []
    )

    # Cai cau hoi nhac toi thi len truoc. Tran khong doi - chay het 156 phep
    # kiem la p-hacking, va ~8 ket qua "co y nghia" se ra tu ngau nhien thuan
    # tuy. Doi cai duoc chon, khong doi so luong.
    wanted = named_in(question, [*numeric, *grouping]) if question else set()
    if wanted:
        correlations = _asked_first(correlations, wanted)
        differences = _asked_first(differences, wanted)

    if len(correlations) > MAX_SUGGESTED:
        notes.append(
            f"Có {len(correlations)} cặp số có thể đo tương quan, chỉ chạy "
            f"{MAX_SUGGESTED} cặp — càng nhiều phép kiểm thì càng dễ có "
            "p_value nhỏ ra do ngẫu nhiên."
            + (f" Ưu tiên các cột câu hỏi nhắc tới: {', '.join(sorted(wanted))}." if wanted else "")
        )
        correlations = correlations[:MAX_SUGGESTED]
    if len(differences) > MAX_SUGGESTED:
        notes.append(
            f"Có {len(differences)} cặp (số, nhóm) có thể so sánh, chỉ chạy "
            f"{MAX_SUGGESTED} cặp."
            + (f" Ưu tiên các cột câu hỏi nhắc tới: {', '.join(sorted(wanted))}." if wanted else "")
        )
        differences = differences[:MAX_SUGGESTED]

    if not correlations and not differences:
        notes.append(
            "Không tự đề xuất được phép kiểm nào: bảng không có đủ cột số, "
            "hoặc không có cột nhóm nào đủ ít giá trị để so sánh."
        )
    else:
        notes.append(
            "Không ai khai 'tests' nên hệ thống tự chọn phép kiểm từ chính dữ "
            f"liệu: {len(correlations)} tương quan, {len(differences)} so sánh nhóm."
        )
    # No regression unasked. Choosing a set of explanations for an outcome is a
    # claim about how the world works, and making it because nobody said
    # otherwise would be the system deciding what the analysis is about.
    if len(numeric) > 1:
        notes.append(
            "Không tự chạy hồi quy — chọn biến giải thích là một nhận định, "
            "phải được khai rõ trong 'tests.regressions'."
        )

    return StatisticsSpec(
        correlations=tuple(correlations), group_differences=tuple(differences)
    ), notes


def _asked_first(pairs: list[tuple[str, str]], wanted: set[str]) -> list[tuple[str, str]]:
    """Xếp lại: cặp mà câu hỏi nhắc tới lên trước, phần còn lại giữ nguyên thứ tự.

    Cặp có **cả hai** cột được hỏi lên đầu, rồi tới cặp có một cột. Thứ tự cũ
    làm mốc phá hoà, nên hàm vẫn tất định - hỏi lại cùng một câu trên cùng một
    bảng thì chạy đúng những phép kiểm đó.
    """
    return sorted(
        pairs,
        key=lambda pair: (
            -sum(1 for name in pair if name in wanted),
            pairs.index(pair),
        ),
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
    for outcome, predictors in spec.regressions:
        _regress(frame, outcome, predictors, result)
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
        out.refused.append(f"{label}: không phải cả hai đều là cột số")
        return

    paired = pd.DataFrame({"a": first, "b": second}).dropna()
    if len(paired) < MIN_SAMPLE:
        out.refused.append(f"{label}: chỉ có {len(paired)} cặp dữ liệu, cần ít nhất {MIN_SAMPLE}")
        return
    if paired["a"].nunique() < 2 or paired["b"].nunique() < 2:
        out.refused.append(f"{label}: một trong hai cột không đổi, không có gì để tương quan")
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
        out.refused.append(f"{label}: '{measure}' không phải cột số")
        return
    if dimension not in frame.columns:
        out.refused.append(f"{label}: không có cột '{dimension}'")
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
            f"{label}: bỏ qua {dropped} nhóm có dưới {MIN_GROUP} dòng — quá ít để nói gì"
        )
    if len(groups) < 2:
        out.refused.append(f"{label}: còn dưới hai nhóm đủ lớn, không so sánh được")
        return
    if len(groups) > MAX_GROUPS:
        out.refused.append(
            f"{label}: {len(groups)} nhóm — đây là mã định danh, không phải phân loại"
        )
        return

    samples = [values for _, values in groups]
    if any(values.nunique() < 2 for values in samples):
        out.refused.append(f"{label}: có nhóm không đổi giá trị nào")
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
    out.add(f"{measure}.ttest.by.{dimension}.n", float(len(first) + len(second)), "dòng", source)

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
    out.add(f"{measure}.anova.by.{dimension}.groups", float(count), "nhóm", source)

    combined = pd.concat(list(samples))
    grand = combined.mean()
    between = sum(len(values) * (values.mean() - grand) ** 2 for values in samples)
    total = float(((combined - grand) ** 2).sum())
    if total > 0:
        # eta squared: the share of the variation that lies between groups
        # rather than inside them. A tiny p-value with a tiny eta squared means
        # a real difference nobody should act on.
        out.add(f"{measure}.eta_sq.by.{dimension}", 100.0 * float(between) / total, "%", source)


def _regress(frame: pd.DataFrame, outcome: str, predictors: Sequence[str], out: _Result) -> None:
    """Ordinary least squares: what each explanation is worth on its own.

    Every coefficient is reported with the uncertainty around it and with a VIF,
    because a coefficient from predictors that overlap heavily is arithmetic
    rather than information - it will swing wildly on data that differs only a
    little.
    """
    label = f"{outcome} ~ {' + '.join(predictors)}"
    target = _numeric(frame, outcome)
    if target is None:
        out.refused.append(f"{label}: '{outcome}' không phải cột số")
        return

    columns: dict[str, pd.Series[Any]] = {"__y__": target}
    for name in predictors:
        values = _numeric(frame, name)
        if values is None:
            out.refused.append(f"{label}: '{name}' không phải cột số")
            return
        columns[name] = values

    paired = pd.DataFrame(columns).dropna()
    count, width = len(paired), len(predictors)
    if count < MIN_PER_PREDICTOR * width:
        out.refused.append(
            f"{label}: {count} dòng cho {width} biến giải thích — "
            f"cần ít nhất {MIN_PER_PREDICTOR} dòng mỗi biến"
        )
        return

    flat = [name for name in predictors if paired[name].nunique() < 2]
    if flat:
        out.refused.append(f"{label}: biến {flat} không đổi giá trị nào")
        return

    design = _with_intercept(paired[list(predictors)])
    try:
        coefficients, standard_errors, residual_df = _least_squares(design, paired["__y__"])
    except _SingularModelError:
        # Two explanations that are the same explanation. The fit has no unique
        # answer, and printing one anyway would be inventing it.
        out.refused.append(
            f"{label}: các biến giải thích trùng lặp hoàn toàn, không có lời giải duy nhất"
        )
        return

    source = f"hoi quy {label}"
    out.add(f"{outcome}.intercept", coefficients[0], "", source)
    for index, name in enumerate(predictors, start=1):
        out.add(f"{outcome}.coef.{name}", coefficients[index], "", source)
        if standard_errors[index] > 0:
            t_stat = coefficients[index] / standard_errors[index]
            p_value = 2.0 * float(stats.t.sf(abs(t_stat), residual_df))
            out.add(f"{outcome}.coef.{name}.p_value", p_value, "", source)

    predicted = design @ coefficients
    residual = paired["__y__"].to_numpy() - predicted
    total = float(((paired["__y__"] - paired["__y__"].mean()) ** 2).sum())
    if total > 0:
        r_squared = 1.0 - float((residual**2).sum()) / total
        out.add(f"{outcome}.regression.r2", 100.0 * r_squared, "%", source)
        # Adjusted, because adding any column at all raises the plain R squared.
        adjusted = 1.0 - (1.0 - r_squared) * (count - 1) / max(residual_df, 1)
        out.add(f"{outcome}.regression.r2_adj", 100.0 * adjusted, "%", source)
    out.add(f"{outcome}.regression.n", float(count), "dòng", source)
    out.add(f"{outcome}.regression.predictors", float(width), "bien", source)

    _report_collinearity(paired, outcome, predictors, out, label)


class _SingularModelError(RuntimeError):
    """The design matrix has no unique solution."""


def _with_intercept(frame: pd.DataFrame) -> np.ndarray[Any, Any]:
    """The design matrix, with a leading column of ones."""
    values = frame.to_numpy(dtype=float)
    return np.column_stack([np.ones(len(values)), values])


def _least_squares(
    design: np.ndarray[Any, Any], target: pd.Series[Any]
) -> tuple[np.ndarray[Any, Any], np.ndarray[Any, Any], int]:
    """Fit, and say how uncertain each coefficient is.

    Raises:
        _SingularModelError: the explanations are linearly dependent, so there is no
            single answer to report.
    """
    rows, columns = design.shape
    residual_df = rows - columns
    if residual_df <= 0:
        raise _SingularModelError
    gram = design.T @ design
    if np.linalg.matrix_rank(gram) < columns:
        raise _SingularModelError

    coefficients, *_ = np.linalg.lstsq(design, target.to_numpy(dtype=float), rcond=None)
    residual = target.to_numpy(dtype=float) - design @ coefficients
    variance = float((residual**2).sum()) / residual_df
    covariance = variance * np.linalg.inv(gram)
    return coefficients, np.sqrt(np.abs(np.diag(covariance))), residual_df


def _report_collinearity(
    paired: pd.DataFrame,
    outcome: str,
    predictors: Sequence[str],
    out: _Result,
    label: str,
) -> None:
    """How much each explanation is already told by the others.

    A high VIF does not stop the fit, so it is reported rather than refused -
    but it is said out loud, because a coefficient standing on a variance
    inflation of twelve is not something to quote in a report.
    """
    if len(predictors) < 2:
        return
    source = f"trung lap giua cac bien trong {label}"
    for name in predictors:
        others = [other for other in predictors if other != name]
        design = _with_intercept(paired[others])
        column = paired[name].to_numpy(dtype=float)
        try:
            coefficients, _, _ = _least_squares(design, paired[name])
        except _SingularModelError:
            out.refused.append(f"{label}: '{name}' là tổ hợp tuyến tính của các biến khác")
            continue
        residual = column - design @ coefficients
        total = float(((column - column.mean()) ** 2).sum())
        if total <= 0:
            continue
        explained = 1.0 - float((residual**2).sum()) / total
        if explained >= 1.0:
            out.refused.append(f"{label}: '{name}' trùng lặp hoàn toàn với các biến khác")
            continue
        inflation = 1.0 / (1.0 - explained)
        out.add(f"{outcome}.vif.{name}", inflation, "", source)
        if inflation > MAX_VIF:
            out.refused.append(
                f"Cảnh báo — {label}: '{name}' có VIF {inflation:.1f} (> {MAX_VIF}). "
                "Hệ số của nó không diễn giải riêng lẻ được"
            )


__all__ = [
    "MAX_GROUPS",
    "MAX_VIF",
    "MIN_GROUP",
    "MIN_PER_PREDICTOR",
    "MIN_SAMPLE",
    "StatisticsError",
    "StatisticsSpec",
    "compute_statistics",
]
