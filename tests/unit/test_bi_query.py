"""Keo tha -> SQL DuckDB -> ket qua: dung nhu pandas tinh, va khong chay duoc gi la."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from pydantic import ValidationError

from analysis_system.services.bi_query import (
    MAX_CATEGORIES,
    MAX_SERIES,
    OTHER,
    BiQuery,
    BiQueryError,
    field_values,
    run_query,
)
from analysis_system.services.bi_schema import schema_of


def companies() -> pd.DataFrame:
    rows = 40
    return pd.DataFrame(
        {
            "Bankrupt?": [index % 2 for index in range(rows)],
            "Debt ratio %": [0.1 + index / 100 for index in range(rows)],
            "Region": [["Bắc", "Trung", "Nam"][index % 3] for index in range(rows)],
            "Day": pd.to_datetime("2024-01-01")
            + pd.to_timedelta([index % 5 for index in range(rows)], unit="D"),
        }
    )


def saved(tmp_path: Path, frame: pd.DataFrame) -> Path:
    path = tmp_path / "t.parquet"
    frame.to_parquet(path)
    return path


@pytest.fixture
def source(tmp_path: Path) -> Path:
    return saved(tmp_path, companies())


def run(source: Path, **spec: Any) -> dict[str, Any]:
    return run_query(source, BiQuery.model_validate(spec), schema_of(pd.read_parquet(source)))


def test_mean_by_a_flag_matches_pandas(source: Path) -> None:
    result = run(source, x="Bankrupt?", y="Debt ratio %", aggregation="mean")
    expected = companies().groupby("Bankrupt?")["Debt ratio %"].mean()
    assert result["kind"] == "bar"
    assert result["categories"] == ["0", "1"]
    assert result["series"][0]["values"] == pytest.approx(expected.tolist())
    assert result["rows_used"] == 40
    assert result["title"] == "Trung bình Debt ratio % theo Bankrupt?"


def test_legend_splits_each_bar_by_group(source: Path) -> None:
    result = run(source, x="Bankrupt?", y="Debt ratio %", aggregation="sum", color="Region")
    expected = companies().groupby(["Bankrupt?", "Region"])["Debt ratio %"].sum()
    assert sorted(series["name"] for series in result["series"]) == ["Bắc", "Nam", "Trung"]
    for series in result["series"]:
        for category, value in zip(result["categories"], series["values"], strict=True):
            assert value == pytest.approx(expected[(int(category), series["name"])])


def test_filters_narrow_the_rows_before_grouping(source: Path) -> None:
    result = run(
        source,
        y="Debt ratio %",
        aggregation="mean",
        filters=[{"field": "Region", "values": ["Nam"]}, {"field": "Debt ratio %", "min": 0.2}],
    )
    frame = companies()
    kept = frame[(frame["Region"] == "Nam") & (frame["Debt ratio %"] >= 0.2)]
    assert result["kind"] == "single"
    assert result["rows_used"] == len(kept)
    assert result["series"][0]["values"][0] == pytest.approx(kept["Debt ratio %"].mean())


def test_a_filter_with_nothing_chosen_does_not_filter(source: Path) -> None:
    result = run(source, y="Debt ratio %", filters=[{"field": "Region", "values": []}])
    assert result["rows_used"] == 40


def test_groups_past_the_eighth_colour_fold_into_other(tmp_path: Path) -> None:
    frame = pd.DataFrame(
        {
            "Kind": [f"k{index % 12}" for index in range(120)],
            "Flag": [index % 2 for index in range(120)],
            "Value": [float(index) for index in range(120)],
        }
    )
    result = run(saved(tmp_path, frame), x="Flag", y="Value", aggregation="mean", color="Kind")
    names = [series["name"] for series in result["series"]]
    assert len(names) == MAX_SERIES
    assert names[-1] == OTHER
    assert result["other_series"] is True
    rest = frame[~frame["Kind"].isin(names[:-1])]
    expected = rest.groupby("Flag")["Value"].mean()
    assert result["series"][-1]["values"] == pytest.approx(expected.tolist())


def test_a_text_axis_keeps_the_largest_groups_and_says_how_many_were_left_out(
    tmp_path: Path,
) -> None:
    frame = pd.DataFrame(
        {"Name": [f"c{index}" for index in range(100)], "Value": [float(i) for i in range(100)]}
    )
    result = run(saved(tmp_path, frame), x="Name", y="Value", aggregation="sum")
    assert len(result["categories"]) == MAX_CATEGORIES
    assert result["dropped"] == 100 - MAX_CATEGORIES
    assert result["categories"][:2] == ["c99", "c98"]


def test_a_date_axis_is_a_line_in_time_order(source: Path) -> None:
    result = run(source, x="Day", aggregation="count")
    assert result["kind"] == "line"
    assert result["categories"] == [f"2024-01-0{day}" for day in range(1, 6)]
    assert result["series"][0]["values"] == [8, 8, 8, 8, 8]
    assert result["value_label"] == "Số dòng"


def test_legend_alone_becomes_the_axis(source: Path) -> None:
    result = run(source, y="Debt ratio %", aggregation="max", color="Region")
    assert result["kind"] == "bar"
    assert sorted(result["categories"]) == ["Bắc", "Nam", "Trung"]


def test_counting_a_dimension_is_allowed(source: Path) -> None:
    result = run(source, x="Region", y="Region", aggregation="count_distinct")
    assert result["series"][0]["values"] == [1, 1, 1]


@pytest.mark.parametrize(
    ("spec", "said"),
    [
        ({"x": "Debt ratio %", "aggregation": "count"}, "Dimension"),
        ({"x": "Region", "y": "Region", "aggregation": "sum"}, "không phải cột số"),
        ({"x": "Khong co", "y": "Debt ratio %"}, "không có cột"),
        ({"x": "Region", "y": "Debt ratio %", "aggregation": "drop"}, "phép gộp"),
        ({"aggregation": "mean"}, "ít nhất"),
        ({"x": "Region", "filters": [{"field": "Khong co", "values": ["a"]}]}, "không có cột"),
    ],
)
def test_what_cannot_run_is_refused_in_words(source: Path, spec: dict[str, Any], said: str) -> None:
    with pytest.raises(BiQueryError, match=said):
        run(source, **spec)


def test_an_unknown_key_is_refused_before_anything_runs() -> None:
    with pytest.raises(ValidationError):
        BiQuery.model_validate({"x": "Region", "sql": "DROP TABLE t"})


def test_names_and_values_cannot_become_sql(tmp_path: Path) -> None:
    path = saved(tmp_path, pd.DataFrame({'a"b': ["x", "y"], "v": [1.0, 2.0]}))
    result = run(path, x='a"b', y="v", aggregation="sum")
    assert result["categories"] == ["y", "x"]
    injected = [{"field": 'a"b', "values": ["x'; DROP TABLE t; --"]}]
    hostile = run(path, y="v", aggregation="sum", filters=injected)
    assert hostile["rows_used"] == 0
    assert run(path, y="v", aggregation="sum")["series"][0]["values"] == [3.0]


def test_filter_choices_list_common_values_first_and_measure_bounds(source: Path) -> None:
    fields = {field.name: field for field in schema_of(companies())}
    listed = field_values(source, fields["Region"])
    assert [item["value"] for item in listed["values"]] == ["Bắc", "Nam", "Trung"]
    assert listed["more"] is False
    bounds = field_values(source, fields["Debt ratio %"])
    assert bounds["min"] == pytest.approx(0.1)
    assert bounds["max"] == pytest.approx(0.49)
