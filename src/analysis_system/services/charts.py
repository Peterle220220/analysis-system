"""Charts, drawn by code, from figures code computed.

A picture in a report is a claim like any other, so it is built from the same
metric set the text is - never from anything the model supplied.

Determinism matters here more than it looks. matplotlib stamps a creation date
into a PNG by default, which would make two identical runs produce two different
files and break criterion S1. The metadata is cleared explicitly, the figure
size and resolution are fixed, and the categorical order is sorted, so the same
numbers always draw the same bytes.
"""

from __future__ import annotations

import io
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

import matplotlib
import numpy as np
import pandas as pd

# A drawing backend that needs no display. Set before pyplot is imported.
matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402

FIGURE_SIZE: Final[tuple[float, float]] = (8.0, 4.5)
DPI: Final[int] = 110
BAR_COLOUR: Final[str] = "#4C72B0"
SECOND_COLOUR: Final[str] = "#DD8452"
# A diverging map, because a correlation heat map has a meaningful middle: zero
# is "no relationship", not "small relationship".
HEAT_MAP: Final[str] = "RdBu_r"
# Past this many bars the labels collide and the chart is unreadable upright.
HORIZONTAL_ABOVE: Final[int] = 8
# A label longer than this pushes a vertical chart off its own axis.
LONG_LABEL: Final[int] = 18
MAX_CATEGORIES: Final[int] = 25
# Below this a box plot draws a shape from too few points to have one.
MIN_BOX_POINTS: Final[int] = 5

KINDS: Final[tuple[str, ...]] = (
    "bar",
    "hbar",
    "grouped_bar",
    "line",
    "scatter",
    "box",
    "heatmap",
)

# Cleared so the file does not carry the moment it was drawn.
NO_TIMESTAMP: Final[dict[str, str | None]] = {"Software": None}


class ChartError(RuntimeError):
    """A chart could not be drawn from the values given."""


def bar_chart(
    labels: Sequence[str],
    values: Sequence[float],
    *,
    title: str,
    xlabel: str = "",
    ylabel: str = "",
) -> bytes:
    """Draw a bar chart and return it as PNG bytes.

    Raises:
        ChartError: there is nothing to draw, or the two lists disagree.
    """
    if not labels or not values:
        raise ChartError("Khong co gia tri nao de ve.")
    if len(labels) != len(values):
        raise ChartError(f"So nhan ({len(labels)}) khac so gia tri ({len(values)}).")

    figure, axes = plt.subplots(figsize=FIGURE_SIZE, dpi=DPI)
    try:
        axes.bar(list(labels), list(values), color=BAR_COLOUR)
        axes.set_title(title)
        if xlabel:
            axes.set_xlabel(xlabel)
        if ylabel:
            axes.set_ylabel(ylabel)
        axes.spines["top"].set_visible(False)
        axes.spines["right"].set_visible(False)
        figure.autofmt_xdate(rotation=30)
        figure.tight_layout()

        buffer = io.BytesIO()
        figure.savefig(buffer, format="png", metadata=NO_TIMESTAMP)
        return buffer.getvalue()
    finally:
        plt.close(figure)


def chart_from_metrics(
    metrics: dict[str, float], *, title: str, suffix: str, ylabel: str = ""
) -> bytes:
    """Draw every metric whose key ends with a given suffix.

    The label is what remains of the key once the suffix is removed, so
    city.Seattle.count and city.Renton.count become Seattle and Renton.

    Raises:
        ChartError: no metric matches the suffix.
    """
    selected = {key: value for key, value in metrics.items() if key.endswith(suffix)}
    if not selected:
        raise ChartError(f"Khong co chi so nao ket thuc bang {suffix!r}.")

    ordered = sorted(selected.items(), key=lambda item: (-item[1], item[0]))
    labels = [key[: -len(suffix)].rsplit(".", 1)[-1] for key, _ in ordered]
    values = [value for _, value in ordered]
    return bar_chart(labels, values, title=title, ylabel=ylabel)


@dataclass(frozen=True)
class ChartSpec:
    """What to draw, and from what.

    Deliberately says where its numbers come from. A chart whose source cannot
    be named is a picture, and a picture is not evidence - the same rule the
    findings live by, applied to the part people look at first.
    """

    kind: str
    title: str
    # Drawn from named metrics: the label is what remains of each key.
    metric_keys: tuple[str, ...] = ()
    # Drawn from the table: the columns it reads.
    columns: tuple[str, ...] = ()
    group_by: str = ""
    x_label: str = ""
    y_label: str = ""

    def sources(self) -> tuple[str, ...]:
        """Everything this chart is drawn from, for a reader to check."""
        return (*self.metric_keys, *self.columns, *((self.group_by,) if self.group_by else ()))


def _finish(figure: Any, axes: Any, spec: ChartSpec) -> bytes:
    """Label, tidy and serialise one figure, always the same way."""
    axes.set_title(spec.title)
    if spec.x_label:
        axes.set_xlabel(spec.x_label)
    if spec.y_label:
        axes.set_ylabel(spec.y_label)
    axes.spines["top"].set_visible(False)
    axes.spines["right"].set_visible(False)
    figure.tight_layout()
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", metadata=NO_TIMESTAMP)
    return buffer.getvalue()


def _short(label: str) -> str:
    """A label that fits, without pretending it was not shortened."""
    return label if len(label) <= 34 else label[:31] + "..."


def _pairs(spec: ChartSpec, metrics: Mapping[str, Any]) -> tuple[list[str], list[float]]:
    """The labelled values a metric-driven chart draws.

    Raises:
        ChartError: a key it was told to draw has nothing behind it. Drawing the
            rest would produce a chart quietly missing a bar.
    """
    missing = [key for key in spec.metric_keys if key not in metrics]
    if missing:
        raise ChartError(f"Khong co chi so {missing} de ve.")
    labels: list[str] = []
    values: list[float] = []
    for key in spec.metric_keys:
        metric = metrics[key]
        labels.append(_short(_label_of(key)))
        values.append(float(getattr(metric, "value", metric)))
    return labels, values


def _label_of(key: str) -> str:
    """What to call one metric on an axis.

    The last meaningful segment of the key, which is the part that differs
    between the bars being compared.
    """
    parts = [part for part in key.split(".") if part]
    for part in reversed(parts):
        if part not in {"share_pct", "mean", "median", "count", "cases", "value", "hours_per_case"}:
            return part.replace("_", " ")
    return key


def _column(frame: pd.DataFrame, name: str) -> pd.Series[Any]:
    """One column as numbers.

    Raises:
        ChartError: it is not there, or it does not hold numbers.
    """
    if name not in frame.columns:
        raise ChartError(f"Khong co cot {name!r} de ve.")
    values = pd.to_numeric(frame[name], errors="coerce")
    if values.notna().sum() == 0:
        raise ChartError(f"Cot {name!r} khong co gia tri so nao.")
    return values


def draw(
    spec: ChartSpec, *, metrics: Mapping[str, Any] | None = None, frame: pd.DataFrame | None = None
) -> bytes:
    """Draw one chart and return it as PNG bytes.

    Raises:
        ChartError: the kind is unknown, or the data it needs is not there.
    """
    if spec.kind not in KINDS:
        raise ChartError(f"Khong ve duoc loai bieu do {spec.kind!r}.")
    drawer = _DRAWERS[spec.kind]
    return drawer(spec, metrics or {}, frame)


def _draw_bar(spec: ChartSpec, metrics: Mapping[str, Any], _frame: pd.DataFrame | None) -> bytes:
    labels, values = _pairs(spec, metrics)
    figure, axes = plt.subplots(figsize=FIGURE_SIZE, dpi=DPI)
    try:
        axes.bar(labels, values, color=BAR_COLOUR)
        figure.autofmt_xdate(rotation=30)
        return _finish(figure, axes, spec)
    finally:
        plt.close(figure)


def _draw_hbar(spec: ChartSpec, metrics: Mapping[str, Any], _frame: pd.DataFrame | None) -> bytes:
    labels, values = _pairs(spec, metrics)
    figure, axes = plt.subplots(figsize=FIGURE_SIZE, dpi=DPI)
    try:
        # Largest at the top, which is where a reader looks first.
        order = sorted(range(len(values)), key=lambda index: values[index])
        axes.barh(
            [labels[index] for index in order], [values[index] for index in order], color=BAR_COLOUR
        )
        return _finish(figure, axes, spec)
    finally:
        plt.close(figure)


def _draw_grouped_bar(
    spec: ChartSpec, _metrics: Mapping[str, Any], frame: pd.DataFrame | None
) -> bytes:
    """Two series side by side, for comparing one group against another."""
    if frame is None or len(spec.columns) < 2 or not spec.group_by:
        raise ChartError("Bieu do cot ghep can bang, hai cot so va mot cot nhom.")
    groups = frame[spec.group_by].astype(str)
    order = sorted(groups.dropna().unique())[:MAX_CATEGORIES]
    positions = np.arange(len(order), dtype=float)
    width = 0.38

    figure, axes = plt.subplots(figsize=FIGURE_SIZE, dpi=DPI)
    try:
        for offset, (name, colour) in enumerate(
            zip(spec.columns[:2], (BAR_COLOUR, SECOND_COLOUR), strict=True)
        ):
            values = _column(frame, name)
            heights = [float(values[groups == group].mean()) for group in order]
            axes.bar(positions + offset * width, heights, width, label=name, color=colour)
        axes.set_xticks(positions + width / 2)
        axes.set_xticklabels([_short(group) for group in order], rotation=30, ha="right")
        axes.legend(frameon=False)
        return _finish(figure, axes, spec)
    finally:
        plt.close(figure)


def _draw_line(spec: ChartSpec, _metrics: Mapping[str, Any], frame: pd.DataFrame | None) -> bytes:
    """A measure over time, which is the one shape a bar chart cannot show."""
    if frame is None or len(spec.columns) < 2:
        raise ChartError("Bieu do duong can mot cot thoi gian va mot cot so.")
    when = pd.to_datetime(frame[spec.columns[0]], errors="coerce", utc=True, format="mixed")
    values = _column(frame, spec.columns[1])
    usable = pd.DataFrame({"when": when, "value": values}).dropna().sort_values("when")
    if usable.empty:
        raise ChartError("Khong con diem nao sau khi doc thoi gian.")

    figure, axes = plt.subplots(figsize=FIGURE_SIZE, dpi=DPI)
    try:
        axes.plot(usable["when"], usable["value"], color=BAR_COLOUR, linewidth=1.6)
        figure.autofmt_xdate(rotation=30)
        return _finish(figure, axes, spec)
    finally:
        plt.close(figure)


def _draw_scatter(
    spec: ChartSpec, _metrics: Mapping[str, Any], frame: pd.DataFrame | None
) -> bytes:
    """Two measures against each other.

    The only honest picture of a correlation: a coefficient of 0.3 is a weak
    straight line or a strong curved one, and the number cannot say which.
    """
    if frame is None or len(spec.columns) < 2:
        raise ChartError("Bieu do phan tan can hai cot so.")
    left = _column(frame, spec.columns[0])
    right = _column(frame, spec.columns[1])
    usable = pd.DataFrame({"x": left, "y": right}).dropna()
    if usable.empty:
        raise ChartError("Khong con cap diem nao sau khi loc.")

    figure, axes = plt.subplots(figsize=FIGURE_SIZE, dpi=DPI)
    try:
        axes.scatter(
            usable["x"], usable["y"], s=14, alpha=0.55, color=BAR_COLOUR, edgecolors="none"
        )
        return _finish(figure, axes, spec)
    finally:
        plt.close(figure)


def _draw_box(spec: ChartSpec, _metrics: Mapping[str, Any], frame: pd.DataFrame | None) -> bytes:
    """One measure across several groups, showing the spread and not only the middle.

    Two groups with the same mean can look nothing alike, and a comparison of
    means alone hides exactly that.
    """
    if frame is None or not spec.columns or not spec.group_by:
        raise ChartError("Bieu do hop can mot cot so va mot cot nhom.")
    values = _column(frame, spec.columns[0])
    groups = frame[spec.group_by].astype(str)
    order = sorted(groups.dropna().unique())[:MAX_CATEGORIES]

    data: list[list[float]] = []
    labels: list[str] = []
    for group in order:
        part = values[groups == group].dropna()
        if len(part) < MIN_BOX_POINTS:
            continue
        data.append([float(value) for value in part])
        labels.append(_short(group))
    if not data:
        raise ChartError(f"Khong nhom nao du {MIN_BOX_POINTS} diem de ve hop.")

    figure, axes = plt.subplots(figsize=FIGURE_SIZE, dpi=DPI)
    try:
        drawn = axes.boxplot(data, tick_labels=labels, patch_artist=True)
        for patch in drawn["boxes"]:
            patch.set_facecolor(BAR_COLOUR)
            patch.set_alpha(0.65)
        figure.autofmt_xdate(rotation=30)
        return _finish(figure, axes, spec)
    finally:
        plt.close(figure)


def _draw_heatmap(
    spec: ChartSpec, _metrics: Mapping[str, Any], frame: pd.DataFrame | None
) -> bytes:
    """How every measure moves with every other, in one picture."""
    if frame is None or len(spec.columns) < 2:
        raise ChartError("Bieu do nhiet can it nhat hai cot so.")
    usable = pd.DataFrame({name: _column(frame, name) for name in spec.columns}).dropna()
    if len(usable.index) < 2:
        raise ChartError("Khong du dong de tinh ma tran tuong quan.")
    matrix = usable.corr(numeric_only=True)

    figure, axes = plt.subplots(figsize=FIGURE_SIZE, dpi=DPI)
    try:
        image = axes.imshow(matrix.to_numpy(), cmap=HEAT_MAP, vmin=-1.0, vmax=1.0)
        names = [_short(str(name)) for name in matrix.columns]
        axes.set_xticks(range(len(names)), names, rotation=30, ha="right")
        axes.set_yticks(range(len(names)), names)
        for row in range(len(names)):
            for column in range(len(names)):
                axes.text(
                    column,
                    row,
                    f"{matrix.to_numpy()[row][column]:.2f}",
                    ha="center",
                    va="center",
                    fontsize=8,
                )
        figure.colorbar(image, ax=axes, shrink=0.8)
        return _finish(figure, axes, spec)
    finally:
        plt.close(figure)


Drawer = Callable[[ChartSpec, Mapping[str, Any], "pd.DataFrame | None"], bytes]

_DRAWERS: Final[dict[str, Drawer]] = {
    "bar": _draw_bar,
    "hbar": _draw_hbar,
    "grouped_bar": _draw_grouped_bar,
    "line": _draw_line,
    "scatter": _draw_scatter,
    "box": _draw_box,
    "heatmap": _draw_heatmap,
}
