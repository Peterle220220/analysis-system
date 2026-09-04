"""Đo theo thời gian — nơi **thứ tự** là toàn bộ ý nghĩa.

The statistics already here treat a period column the way they treat any other
grouping: `thang` becomes a label, twelve months become twelve categories, and a
group comparison answers *"các tháng có khác nhau không"*. Shuffle the twelve
months and that answer does not change by a decimal - which is exactly the
problem, because a trend that survives shuffling was never a trend.

So this measures the things that **die when you shuffle the rows**:

* **Xu hướng** - does the series climb or fall across the periods, in order?
  Measured with Spearman's rho against the period's position. Rank-based, so a
  single enormous month cannot manufacture a slope, and no line is fitted -
  fitting a line is the first step towards extending it, and extending it is a
  forecast.
* **So với kỳ trước** - each period against the one before it. The question
  *"tháng này hơn tháng trước bao nhiêu"* has one right answer and it is
  arithmetic.
* **Mùa vụ** - is June always high, or was it high once? Only answerable with
  **at least two complete cycles**; below that, "June is high" and "it rose in
  June that year" fit the same data and nothing separates them.

**Không có dự báo, và đó là chủ ý.** *"Tháng nào bán nhiều"* describes rows that
exist and traces back to them like every other figure here. *"Quý sau bán được
bao nhiêu"* traces back to a model and a split, not to any row - the same
objection that kept per-row prediction out of Phase 6, and it does not weaken
because the axis is time.

Không dùng model nào.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final

import pandas as pd

from analysis_system.contracts.agents import MetricValue

# Below this many periods a direction is a coincidence with a name. Three points
# make a line whichever way they fall.
MIN_PERIODS: Final[int] = 5
# Seasonality needs a season to repeat. One cycle cannot tell "June is high"
# from "it went up that June" - the two fit identical data.
MIN_CYCLES: Final[int] = 2
# How much of a column has to parse as a date before it is treated as one. The
# same bar `_kinds` uses for numbers, and for the same reason: a stray footer
# row should not disqualify a column.
PARSE_SHARE: Final[float] = 0.9
# Periods reported individually. Beyond this the list stops being something a
# person reads.
MAX_PERIODS: Final[int] = 24
DECIMALS: Final[int] = 4

# Period strings a person types that pandas will not parse on its own.
QUARTER: Final[re.Pattern[str]] = re.compile(r"^\s*(\d{4})\s*[-/ ]?\s*[Qq]([1-4])\s*$")


@dataclass(frozen=True)
class Period:
    """One period, its position in the sequence, and the season it belongs to."""

    label: str
    order: int
    season: str = ""
    # The season as a number - month 1..12, quarter 1..4. Carried separately
    # because a claim may not type a digit, so "thang 12" can only be said by
    # citing a metric whose *value* is twelve. With the number only in the key,
    # the question "which month sells most" has no answer a claim may quote.
    season_number: int = 0


@dataclass
class Timeline:
    """What could be measured along the time axis, and what could not."""

    column: str = ""
    periods: tuple[str, ...] = ()
    metrics: dict[str, MetricValue] = field(default_factory=dict)
    # Every refusal, in the same shape every other service uses. A trend that
    # was not measured and a trend that was measured as flat look identical
    # from outside unless one of them says so.
    refused: tuple[str, ...] = field(default_factory=tuple)


def _quarters(series: pd.Series) -> pd.Series | None:
    """Parse `2026-Q3` and friends, which pandas does not read as dates."""
    matched = series.astype(str).str.match(QUARTER)
    if float(matched.mean()) < PARSE_SHARE:
        return None
    parts = series.astype(str).str.extract(QUARTER)
    months = parts[1].astype(float) * 3 - 2
    return pd.to_datetime(
        parts[0].astype(str) + "-" + months.astype("Int64").astype(str) + "-01",
        errors="coerce",
    )


def as_periods(series: pd.Series) -> pd.Series | None:
    """This column as points in time, or None when it is not one.

    Measured rather than read off the dtype, exactly as `_kinds` measures
    numbers: a period column arriving from a CSV is text until somebody looks.
    """
    cleaned = series.dropna()
    if cleaned.empty:
        return None

    quarterly = _quarters(cleaned)
    if quarterly is not None:
        return quarterly

    # Bare years look like numbers and would otherwise be read as a measure.
    if pd.api.types.is_numeric_dtype(cleaned):
        values = pd.to_numeric(cleaned, errors="coerce").dropna()
        if values.between(1900, 2200).all() and (values % 1 == 0).all():
            return pd.to_datetime(values.astype(int).astype(str), format="%Y", errors="coerce")
        return None

    parsed = pd.to_datetime(cleaned, errors="coerce", format="mixed")
    if float(parsed.notna().mean()) >= PARSE_SHARE:
        return parsed
    return None


def temporal_columns(frame: pd.DataFrame) -> list[str]:
    """Every column that holds points in time, in table order."""
    return [str(name) for name in frame.columns if as_periods(frame[name]) is not None]


def _label(moment: pd.Timestamp, grain: str) -> Period:
    """One timestamp as a period label, its order, and its season."""
    if grain == "year":
        return Period(label=f"{moment.year}", order=moment.year)
    if grain == "quarter":
        quarter = (moment.month - 1) // 3 + 1
        return Period(
            label=f"{moment.year}-Q{quarter}",
            order=moment.year * 4 + quarter,
            season=f"Q{quarter}",
            season_number=quarter,
        )
    return Period(
        label=f"{moment.year}-{moment.month:02d}",
        order=moment.year * 12 + moment.month,
        season=f"thang {moment.month:02d}",
        season_number=moment.month,
    )


def choose_grain(moments: pd.Series) -> str:
    """Month, quarter or year - the finest one a person can still read.

    Chosen from the data rather than declared, because the right grain is a
    property of what was recorded, and asking somebody to name it is asking them
    to know the answer first.

    Judged by **how many periods it produces**, not by how long the span is.
    Going by span coarsened two years of monthly rows into eight quarters -
    twenty-four months is a readable list, it is the grain the data was kept at,
    and the coarsening threw away the June and December peaks that were the
    entire point.
    """
    for grain in ("month", "quarter", "year"):
        periods = {_label(moment, grain).label for moment in moments}
        if len(periods) <= MAX_PERIODS:
            return grain
    return "year"


def measure(
    frame: pd.DataFrame, column: str, measures: Sequence[str], *, grain: str = ""
) -> Timeline:
    """Everything the time axis says about these measures, and everything it cannot.

    Args:
        frame: the table. It is never modified.
        column: which column holds the time.
        measures: the numeric columns to follow through it.
        grain: month, quarter or year. Chosen from the span when left empty.

    Returns:
        The metrics, in the same shape every other service emits, and one
        refusal per thing that could not be measured.
    """
    moments = as_periods(frame[column]) if column in frame.columns else None
    if moments is None:
        return Timeline(
            column=column,
            refused=(f"cot {column!r} khong doc duoc thanh moc thoi gian.",),
        )

    grain = grain or choose_grain(moments)
    labelled = [_label(moment, grain) for moment in moments]
    working = frame.loc[moments.index].copy()
    working["_ky"] = [period.label for period in labelled]
    working["_thu_tu"] = [period.order for period in labelled]
    working["_mua"] = [period.season for period in labelled]
    working["_so_mua"] = [period.season_number for period in labelled]

    result = Timeline(column=column)
    refused: list[str] = []
    periods = working[["_ky", "_thu_tu"]].drop_duplicates().sort_values("_thu_tu")
    result.periods = tuple(periods["_ky"])

    if len(periods) < MIN_PERIODS:
        refused.append(
            f"chi co {len(periods)} ky theo {grain} - duoi {MIN_PERIODS} thi mot huong "
            "di len hay di xuong chi la trung hop co ten goi, chua phai xu huong."
        )

    for name in measures:
        if name not in working.columns:
            continue
        values = pd.to_numeric(working[name], errors="coerce")
        if values.notna().sum() == 0:
            refused.append(f"{name}: khong co gia tri so nao de theo doi.")
            continue
        working[name] = values
        per_period = working.groupby("_ky", sort=False)[name].mean()
        ordered = per_period.reindex(result.periods).dropna()

        _record_periods(result, name, column, ordered)
        _record_trend(result, name, column, ordered, refused, grain)
        _record_change(result, name, column, ordered)
        _record_season(result, name, working, ordered, refused, grain)

    result.refused = tuple(refused)
    return result


def _put(result: Timeline, key: str, value: float, unit: str, source: str) -> None:
    result.metrics[key] = MetricValue(
        key=key, value=round(float(value), DECIMALS), unit=unit, source=source
    )


def _record_periods(result: Timeline, name: str, column: str, ordered: pd.Series) -> None:
    """The value at each period, in order."""
    for label, value in list(ordered.items())[:MAX_PERIODS]:
        _put(
            result,
            f"{name}.by.{column}.{label}",
            value,
            "",
            f"{name} trung binh trong ky {label}",
        )


def _record_trend(
    result: Timeline,
    name: str,
    column: str,
    ordered: pd.Series,
    refused: list[str],
    grain: str,
) -> None:
    """Whether the series climbs or falls across the periods, in order.

    Spearman against position, so a single enormous period cannot manufacture a
    slope. No line is fitted: fitting one is the first step towards extending
    it, and extending it is a forecast.
    """
    if len(ordered) < MIN_PERIODS:
        return
    position = pd.Series(range(len(ordered)))
    rho = float(position.corr(pd.Series(ordered.to_numpy()), method="spearman"))
    if pd.isna(rho):
        refused.append(f"{name}: khong tinh duoc xu huong (gia tri khong doi).")
        return
    _put(
        result,
        f"{name}.trend.with.{column}",
        rho,
        "",
        f"tuong quan hang cua {name} voi thu tu {len(ordered)} ky theo {grain}",
    )


def _record_change(result: Timeline, name: str, column: str, ordered: pd.Series) -> None:
    """Each period against the one before it."""
    previous: float | None = None
    for label, value in list(ordered.items())[:MAX_PERIODS]:
        if previous is not None:
            _put(
                result,
                f"{name}.change.by.{column}.{label}",
                float(value) - previous,
                "",
                f"{name} ky {label} so voi ky lien truoc",
            )
        previous = float(value)


def _record_season(
    result: Timeline,
    name: str,
    working: pd.DataFrame,
    ordered: pd.Series,
    refused: list[str],
    grain: str,
) -> None:
    """Whether a season repeats, or happened once.

    Refused below two complete cycles, because "June is high" and "it rose in
    June that year" fit identical data and nothing in one cycle separates them.
    A seasonal figure from a single year is the confident kind of wrong.
    """
    if grain == "year" or ordered.empty:
        return
    seasons = working.loc[working["_ky"].isin(ordered.index), ["_mua", "_so_mua", "_thu_tu", name]]
    if seasons.empty or not seasons["_mua"].any():
        return

    cycles = seasons.groupby("_mua")["_thu_tu"].nunique()
    if int(cycles.max() or 0) < MIN_CYCLES:
        refused.append(
            f"{name}: chi co mot chu ky nen khong noi duoc ve mua vu - "
            "'thang 6 luon cao' va 'thang 6 nam do cao' vua dung voi cung mot du lieu."
        )
        return

    repeated = cycles[cycles >= MIN_CYCLES].index
    kept = seasons[seasons["_mua"].isin(repeated)]
    averages = kept.groupby("_mua")[name].mean()
    for raw, value in averages.items():
        season = str(raw)
        _put(
            result,
            f"{name}.seasonal.{season.replace(' ', '_')}",
            value,
            "",
            f"{name} trung binh cua {season} qua {int(cycles.loc[season])} chu ky",
        )

    # Which season is highest, as a number a claim may quote. Without this the
    # answer to "thang nao ban nhieu nhat" lives only in a key name, and a key
    # name cannot go into a sentence: the digit rule forbids typing "12", so the
    # model reaches for the nearest figure and writes the revenue where the
    # month belongs.
    if averages.empty:
        return
    numbers = kept.drop_duplicates("_mua").set_index("_mua")["_so_mua"]
    for edge, found_at in (("peak", averages.idxmax()), ("trough", averages.idxmin())):
        season = str(found_at)
        _put(
            result,
            f"{name}.seasonal.{edge}_number",
            float(numbers.get(season, 0)),
            # No unit. A month index is not measured in months, it names one -
            # and a unit here gets pasted after the figure, turning "Thang {x}"
            # into "Thang 12 thang". What it is travels in the source instead.
            "",
            f"so thu tu cua {season} ({'thang' if grain == 'month' else 'quy'}) - "
            f"{'cao' if edge == 'peak' else 'thap'} nhat trong {len(averages)} mua da do",
        )
        _put(
            result,
            f"{name}.seasonal.{edge}_value",
            float(averages.loc[season]),
            "",
            f"{name} trung binh cua {season}",
        )
