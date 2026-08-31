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
from collections.abc import Sequence
from typing import Final

import matplotlib

# A drawing backend that needs no display. Set before pyplot is imported.
matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402

FIGURE_SIZE: Final[tuple[float, float]] = (8.0, 4.5)
DPI: Final[int] = 110
BAR_COLOUR: Final[str] = "#4C72B0"

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
