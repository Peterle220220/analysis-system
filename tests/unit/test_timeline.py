"""Đo theo thời gian: cái gì chết khi xáo trộn thứ tự, và cái gì bị từ chối.

The property that matters most is the one the old statistics failed: **a trend
must not survive shuffling**. A group comparison over twelve months gives the
same answer in any order, which is exactly why it was never an answer about
time. Two tests here check that directly.

The refusals get as much attention as the measurements, because a seasonal
figure computed from one cycle is the confident kind of wrong.
"""

from __future__ import annotations

import pandas as pd

from analysis_system.services.timeline import (
    MIN_CYCLES,
    MIN_PERIODS,
    as_periods,
    choose_grain,
    measure,
    temporal_columns,
)


def sales(
    years: tuple[int, ...] = (2025, 2026), peak_months: tuple[int, ...] = (6, 12)
) -> pd.DataFrame:
    """Monthly sales that climb year on year, with a repeating seasonal peak."""
    rows = [
        {
            "ngay": f"{year}-{month:02d}-15",
            "doanh_thu": 100 + (year - 2025) * 20 + month + (60 if month in peak_months else 0),
        }
        for year in years
        for month in range(1, 13)
    ]
    return pd.DataFrame(rows)


# --- finding the time axis --------------------------------------------------------


def test_a_date_column_is_recognised_however_it_was_stored() -> None:
    """Measured, not read off the dtype: out of a CSV a date is text."""
    assert as_periods(pd.Series(["2026-01-15", "2026-02-15"])) is not None
    assert as_periods(pd.Series(["2025-Q1", "2025-Q2"])) is not None
    assert as_periods(pd.Series([2024, 2025, 2026])) is not None


def test_things_that_are_not_time_are_not_mistaken_for_it() -> None:
    """A bare number column is the dangerous case: years look exactly like measures."""
    assert as_periods(pd.Series(["ha noi", "da nang"])) is None
    assert as_periods(pd.Series([1.5, 2.5, 3.5])) is None
    assert as_periods(pd.Series([12, 45, 88])) is None, "khong phai nam thi khong phai thoi gian"


def test_the_temporal_columns_of_a_table_are_listed() -> None:
    frame = sales()
    frame["ten"] = "x"
    assert temporal_columns(frame) == ["ngay"]


def test_the_grain_is_the_finest_one_still_readable() -> None:
    """Judged by how many periods it makes, not by how long the span is.

    Going by span turned two years of monthly rows into eight quarters, which
    threw away the very peaks the data was recorded to show.
    """
    monthly = as_periods(sales()["ngay"])
    assert monthly is not None
    assert choose_grain(monthly) == "month"

    long_run = as_periods(sales(years=tuple(range(2015, 2026)))["ngay"])
    assert long_run is not None
    assert choose_grain(long_run) in {"quarter", "year"}


# --- what dies when you shuffle ---------------------------------------------------


def test_a_climbing_series_is_reported_as_climbing() -> None:
    found = measure(sales(), "ngay", ["doanh_thu"])
    trend = found.metrics["doanh_thu.trend.with.ngay"]
    assert trend.value > 0.5


def test_a_falling_series_is_reported_as_falling() -> None:
    """The other direction, so a test cannot pass by always reporting a rise."""
    frame = pd.DataFrame(
        {
            "ngay": [f"2026-{month:02d}-01" for month in range(1, 13)],
            "doanh_thu": list(range(120, 0, -10)),
        }
    )
    assert measure(frame, "ngay", ["doanh_thu"]).metrics["doanh_thu.trend.with.ngay"].value < -0.9


def test_the_trend_does_not_survive_shuffling_the_periods() -> None:
    """The whole reason this exists.

    A group comparison over twelve months gives the same answer in any order,
    which is what made it useless for a question about time. Order is the
    measurement here, so scrambling it has to change the answer.
    """
    frame = sales()
    ordered = measure(frame, "ngay", ["doanh_thu"]).metrics["doanh_thu.trend.with.ngay"].value

    scrambled = frame.copy()
    scrambled["doanh_thu"] = list(reversed(frame["doanh_thu"].tolist()))
    reversed_trend = (
        measure(scrambled, "ngay", ["doanh_thu"]).metrics["doanh_thu.trend.with.ngay"].value
    )

    assert ordered > 0 > reversed_trend, "dao thu tu phai doi dau xu huong"


def test_each_period_is_measured_against_the_one_before_it() -> None:
    found = measure(sales(), "ngay", ["doanh_thu"])
    assert found.metrics["doanh_thu.change.by.ngay.2025-06"].value == 61.0
    assert found.metrics["doanh_thu.change.by.ngay.2025-07"].value == -59.0


def test_the_value_of_every_period_is_reported() -> None:
    found = measure(sales(), "ngay", ["doanh_thu"])
    assert found.metrics["doanh_thu.by.ngay.2025-01"].value == 101.0
    assert found.periods[0] == "2025-01"


# --- seasonality, and the refusal that guards it ----------------------------------


def test_a_season_that_repeats_is_measured() -> None:
    found = measure(sales(), "ngay", ["doanh_thu"])
    june = found.metrics["doanh_thu.seasonal.thang_06"].value
    may = found.metrics["doanh_thu.seasonal.thang_05"].value
    assert june > may * 1.4, "thang 6 lap lai o ca hai nam thi phai noi ra"


def test_one_cycle_cannot_speak_of_seasons() -> None:
    """The confident kind of wrong.

    With a single year, "June is high" and "it rose that June" fit identical
    data, and nothing in the data separates them.
    """
    found = measure(sales(years=(2025,)), "ngay", ["doanh_thu"])
    assert not any(".seasonal." in key for key in found.metrics)
    assert any("mot chu ky" in note for note in found.refused)
    assert MIN_CYCLES == 2


def test_too_few_periods_is_not_a_trend() -> None:
    """Three points make a line whichever way they fall."""
    frame = pd.DataFrame(
        {"ky": ["2026-01-01", "2026-02-01", "2026-03-01"], "doanh_thu": [100, 300, 200]}
    )
    found = measure(frame, "ky", ["doanh_thu"])
    assert not any(".trend." in key for key in found.metrics)
    assert any("chua phai xu huong" in note for note in found.refused)
    assert MIN_PERIODS == 5


def test_a_flat_series_says_so_rather_than_reporting_a_direction() -> None:
    frame = pd.DataFrame(
        {"ky": [f"2026-{month:02d}-01" for month in range(1, 9)], "doanh_thu": [100] * 8}
    )
    found = measure(frame, "ky", ["doanh_thu"])
    assert not any(".trend." in key for key in found.metrics)
    assert any("khong tinh duoc xu huong" in note for note in found.refused)


# --- and it refuses honestly ------------------------------------------------------


def test_a_column_that_is_not_time_is_refused_by_name() -> None:
    frame = pd.DataFrame({"ten": ["a", "b"], "x": [1, 2]})
    found = measure(frame, "ten", ["x"])
    assert found.metrics == {}
    assert any("khong doc duoc thanh moc thoi gian" in note for note in found.refused)


def test_a_measure_with_no_numbers_is_refused_by_name() -> None:
    frame = sales()
    frame["ghi_chu"] = "khong phai so"
    found = measure(frame, "ngay", ["ghi_chu"])
    assert any("khong co gia tri so nao" in note for note in found.refused)


def test_nothing_here_predicts_anything() -> None:
    """Deliberate, and worth a test so it stays deliberate.

    "Which month sells most" describes rows that exist. "What will next quarter
    sell" traces back to a model and a split rather than to any row - the same
    objection that kept per-row prediction out of Phase 6, unweakened by the
    axis being time.
    """
    found = measure(sales(), "ngay", ["doanh_thu"])
    assert all(
        word not in key
        for key in found.metrics
        for word in ("forecast", "predict", "du_bao", "next", "ky_sau")
    )
