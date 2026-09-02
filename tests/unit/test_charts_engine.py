"""Charts: drawing them, and choosing which one to draw.

The choosing matters more than the drawing. A wrong shape hides the thing worth
seeing - two groups with the same average look identical as bars and nothing
alike as boxes - so a system that picks a bar chart for everything is decorating
an argument rather than illustrating one.

The test that earns its place is the last one: a chart backs a claim only when it
draws what that claim is about. It was written after two different claims in a
real answer came back with byte-identical pictures of neither.
"""

from __future__ import annotations

import hashlib

import pandas as pd
import pytest

from analysis_system.contracts.agents import MetricValue
from analysis_system.services.chart_choice import (
    MAX_PER_KIND,
    suggest_charts,
    suggestion_for,
)
from analysis_system.services.charts import KINDS, ChartError, ChartSpec, draw


def table(rows: int = 60) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "score": [round(50 + (index * 7) % 40 + 0.5, 1) for index in range(rows)],
            "hours": [round((index * 3) % 11 + 0.5, 1) for index in range(rows)],
            "sleep": [round((index * 5) % 9 + 0.5, 1) for index in range(rows)],
            "grade": ["A", "B", "C"] * (rows // 3),
            "when": pd.date_range("2026-01-01", periods=rows, freq="D").astype(str),
        }
    )


def metric(key: str, value: float, unit: str = "") -> MetricValue:
    return MetricValue(key=key, value=value, unit=unit, source="test")


def measured() -> dict[str, MetricValue]:
    return {
        "score.corr.with.hours": metric("score.corr.with.hours", 0.62),
        "score.corr.with.sleep": metric("score.corr.with.sleep", 0.11),
        "hours.corr.with.sleep": metric("hours.corr.with.sleep", 0.05),
        "score.ttest.by.grade.p_value": metric("score.ttest.by.grade.p_value", 0.01),
        "grade.A.share_pct": metric("grade.A.share_pct", 33.3, "%"),
        "grade.B.share_pct": metric("grade.B.share_pct", 33.3, "%"),
        "grade.C.share_pct": metric("grade.C.share_pct", 33.4, "%"),
    }


# --- drawing ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "spec"),
    [
        (
            "bar",
            ChartSpec(
                kind="bar", title="t", metric_keys=("grade.A.share_pct", "grade.B.share_pct")
            ),
        ),
        (
            "hbar",
            ChartSpec(
                kind="hbar", title="t", metric_keys=("grade.A.share_pct", "grade.B.share_pct")
            ),
        ),
        ("scatter", ChartSpec(kind="scatter", title="t", columns=("hours", "score"))),
        ("box", ChartSpec(kind="box", title="t", columns=("score",), group_by="grade")),
        ("line", ChartSpec(kind="line", title="t", columns=("when", "score"))),
        ("heatmap", ChartSpec(kind="heatmap", title="t", columns=("score", "hours", "sleep"))),
        (
            "grouped_bar",
            ChartSpec(kind="grouped_bar", title="t", columns=("score", "hours"), group_by="grade"),
        ),
    ],
)
def test_every_kind_draws_a_png(kind: str, spec: ChartSpec) -> None:
    assert spec.kind == kind
    png = draw(spec, metrics=measured(), frame=table())
    assert png.startswith(b"\x89PNG")
    assert len(png) > 1000


def test_every_kind_is_reachable() -> None:
    # A kind nobody can draw is a name in a list.
    assert set(KINDS) == {"bar", "hbar", "grouped_bar", "line", "scatter", "box", "heatmap"}


def test_the_same_data_draws_the_same_bytes_twice() -> None:
    # matplotlib stamps a creation date into a PNG by default, which would make
    # two identical runs produce two different files and break criterion S1.
    spec = ChartSpec(kind="scatter", title="t", columns=("hours", "score"))
    first = draw(spec, metrics=measured(), frame=table())
    second = draw(spec, metrics=measured(), frame=table())
    assert hashlib.md5(first).hexdigest() == hashlib.md5(second).hexdigest()


def test_an_unknown_kind_is_refused() -> None:
    with pytest.raises(ChartError, match="Khong ve duoc"):
        draw(ChartSpec(kind="pie", title="t"), metrics=measured(), frame=table())


def test_a_missing_metric_stops_the_chart_rather_than_leaving_a_gap() -> None:
    # Drawing the rest would produce a chart quietly missing a bar, which reads
    # as a smaller number rather than an absent one.
    with pytest.raises(ChartError, match="Khong co chi so"):
        draw(
            ChartSpec(kind="bar", title="t", metric_keys=("grade.A.share_pct", "khong_co")),
            metrics=measured(),
        )


def test_a_box_plot_needs_enough_points_to_have_a_shape() -> None:
    frame = pd.DataFrame({"score": [1.0, 2.0], "grade": ["A", "B"]})
    with pytest.raises(ChartError, match="du"):
        draw(ChartSpec(kind="box", title="t", columns=("score",), group_by="grade"), frame=frame)


# --- choosing -----------------------------------------------------------------------


def test_a_correlation_is_offered_as_a_scatter_plot() -> None:
    top = suggest_charts(measured(), table())[0]
    assert top.kind == "scatter"
    assert "dam may diem" in top.reason


def test_every_suggestion_says_why() -> None:
    # A ranking without reasons is an opinion; with them it is something a
    # person can disagree with, which is the point.
    for suggestion in suggest_charts(measured(), table()):
        assert suggestion.reason.strip()
        assert suggestion.spec.sources()


def test_one_kind_cannot_take_the_whole_ranking() -> None:
    # Six suggestions came back once and all six were scatter plots, so the box
    # plot and the heat map never appeared - and the whole point of ranking
    # chart types is to offer different ways of seeing.
    kinds = [suggestion.kind for suggestion in suggest_charts(measured(), table())]
    for kind in set(kinds):
        assert kinds.count(kind) <= MAX_PER_KIND
    assert len(set(kinds)) > 1


def test_the_ranking_is_the_same_twice() -> None:
    first = [(s.kind, s.spec.title) for s in suggest_charts(measured(), table())]
    second = [(s.kind, s.spec.title) for s in suggest_charts(measured(), table())]
    assert first == second


def test_nothing_worth_drawing_is_an_empty_list_not_a_bar_chart_of_one_bar() -> None:
    assert suggest_charts({"rows.total": metric("rows.total", 300.0)}, None) == []


# --- a chart is evidence for one claim, or it is decoration --------------------------


def test_a_claim_gets_a_chart_of_what_it_is_actually_about() -> None:
    # Two claims in a real answer came back with byte-identical pictures of
    # neither, because the match was "any column of the chart appears anywhere
    # in the claim's keys" and they shared one column.
    frame, metrics = table(), measured()
    first = suggestion_for(("score.corr.with.hours",), metrics, frame)
    second = suggestion_for(("score.corr.with.sleep",), metrics, frame)
    assert first is not None and second is not None
    assert set(first.spec.columns) == {"score", "hours"}
    assert set(second.spec.columns) == {"score", "sleep"}


def test_two_different_claims_do_not_get_the_same_picture() -> None:
    frame, metrics = table(), measured()
    first = suggestion_for(("score.corr.with.hours",), metrics, frame)
    second = suggestion_for(("score.corr.with.sleep",), metrics, frame)
    assert first is not None and second is not None
    left = draw(first.spec, metrics=metrics, frame=frame)
    right = draw(second.spec, metrics=metrics, frame=frame)
    assert hashlib.md5(left).hexdigest() != hashlib.md5(right).hexdigest()


def test_a_column_name_matches_whole_or_not_at_all() -> None:
    # `grade` must not match `previous_grade`.
    frame = table().rename(columns={"grade": "previous_grade"})
    metrics = {
        "score.ttest.by.previous_grade.p_value": metric(
            "score.ttest.by.previous_grade.p_value", 0.01
        )
    }
    found = suggestion_for(("score.ttest.by.previous_grade.p_value",), metrics, frame)
    assert found is not None
    assert found.spec.group_by == "previous_grade"


def test_a_claim_resting_on_one_number_gets_no_chart() -> None:
    # A bar chart of one bar shows nothing while looking as though it does.
    assert (
        suggestion_for(("rows.total",), {"rows.total": metric("rows.total", 300.0)}, table())
        is None
    )
