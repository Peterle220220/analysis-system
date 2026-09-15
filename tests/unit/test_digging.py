"""Digging: finding which part of a process is slow, and where the difference sits.

The tests that matter most here are about what the module *discovers*. A system
that has to be told which columns describe a case only answers questions somebody
already knew to ask - and the whole point is that nobody knows in advance what
the data will contain.

The real permit log is used at the end because it has the shape that makes this
worth building: five intake channels, one of them two hundred times slower than
another, and the difference concentrated in three handovers out of twenty-seven.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pandas as pd
import pytest

from analysis_system.services.digging import (
    MAX_ATTRIBUTE_VALUES,
    MIN_COHORT,
    case_attributes,
    compare_cohorts,
)
from analysis_system.services.process_mining import EventLogSpec

# The two tests at the bottom of this file need a real permit event log, in XES
# column naming: `case:concept:name`, `concept:name`, `time:timestamp`,
# `org:resource`, plus `case:channel` and `case:department`.
#
# It is the BPI Challenge **2020** permit log - a different dataset from the
# 2019 one `scripts/make_fixture.py` cuts from - and it lives outside the repo
# because it is data. Where it came from was written down nowhere, and the file
# was deleted during a clean-up on the strength of that: nobody could say what
# it was, so it looked like clutter. It was not. It was the only real event log
# these two tests had.
#
# To bring them back: put a permit log with those columns at the path below.
# Until then they skip, and say why.
PERMIT = Path("/home/phongle/analysis-data/raw/permit_receipt.csv")

SPEC = EventLogSpec(case_id="case", activity="act", timestamp="ts", resource="who")


def log(
    cases: int,
    *,
    channel_of: Callable[[int], str] | None = None,
    slow_of: Callable[[int], int] | None = None,
) -> pd.DataFrame:
    """A three-step log where each case can be given a channel and a pace."""
    rows = []
    for index in range(cases):
        channel = channel_of(index) if channel_of else "web"
        hours = slow_of(index) if slow_of else 1
        for position, step in enumerate(("A", "B", "C")):
            rows.append(
                {
                    "case": f"c{index}",
                    "act": step,
                    "ts": pd.Timestamp("2026-01-01T00:00:00Z")
                    + pd.Timedelta(hours=hours * position),
                    "who": f"u{index % 3}",
                    "channel": channel,
                    "region": "bac",
                    "note": f"ghi chu {index}",
                }
            )
    frame = pd.DataFrame(rows)
    frame["ts"] = frame["ts"].astype(str)
    return frame


# --- what the system works out for itself ----------------------------------------


def test_it_finds_the_columns_that_describe_a_case() -> None:
    # Discovered, not declared. A system that has to be told what its data
    # contains only answers questions somebody already knew to ask.
    frame = log(40, channel_of=lambda i: "post" if i % 2 else "web")
    found = {attribute.name for attribute in case_attributes(frame, SPEC)}
    assert "channel" in found


def test_a_column_that_changes_within_a_case_is_not_one_of_them() -> None:
    # Grouping case durations by the activity is arithmetic about nothing: the
    # activity changes three times inside every case.
    frame = log(40, channel_of=lambda i: "post" if i % 2 else "web")
    found = {attribute.name for attribute in case_attributes(frame, SPEC)}
    assert "act" not in found
    assert "ts" not in found


def test_a_column_with_one_value_everywhere_tells_nothing_apart() -> None:
    frame = log(40, channel_of=lambda i: "post" if i % 2 else "web")
    assert "region" not in {attribute.name for attribute in case_attributes(frame, SPEC)}


def test_a_column_with_a_value_per_case_is_an_identifier_not_a_grouping() -> None:
    # One group per case is the log again, with extra steps.
    frame = log(MAX_ATTRIBUTE_VALUES + 10, channel_of=lambda _: "web")
    assert "note" not in {attribute.name for attribute in case_attributes(frame, SPEC)}


# --- where the difference actually sits --------------------------------------------


def test_it_says_which_handover_holds_the_difference() -> None:
    # The question that follows every comparison: postal is slower - so what do
    # I change? The totals answer nothing; this does.
    rows = []
    for index in range(4 * MIN_COHORT):
        slow = index % 2 == 0
        start = pd.Timestamp("2026-01-01T00:00:00Z")
        rows.extend(
            [
                {
                    "case": f"c{index}",
                    "act": "A",
                    "ts": str(start),
                    "who": "u",
                    "channel": "post" if slow else "web",
                },
                {
                    "case": f"c{index}",
                    "act": "B",
                    "ts": str(start + pd.Timedelta(hours=1)),
                    "who": "u",
                    "channel": "post" if slow else "web",
                },
                # Only the postal cases wait a long time between B and C.
                {
                    "case": f"c{index}",
                    "act": "C",
                    "ts": str(start + pd.Timedelta(hours=101 if slow else 2)),
                    "who": "u",
                    "channel": "post" if slow else "web",
                },
            ]
        )
    frame = pd.DataFrame(rows)
    spec = EventLogSpec(case_id="case", activity="act", timestamp="ts")

    found = compare_cohorts(frame, spec, "channel", "post", "web")
    assert found.steps
    assert found.steps[0].source == "B"
    assert found.steps[0].target == "C"
    assert found.steps[0].share_of_gap_pct > 95.0


def test_the_shares_of_the_gap_add_up_to_the_whole_gap() -> None:
    frame = log(
        4 * MIN_COHORT,
        channel_of=lambda i: "post" if i % 2 else "web",
        slow_of=lambda i: 10 if i % 2 else 1,
    )
    found = compare_cohorts(frame, SPEC, "channel", "post", "web")
    assert round(sum(step.share_of_gap_pct for step in found.steps), 1) == 100.0


def test_a_cohort_too_small_to_compare_is_refused() -> None:
    frame = log(4 * MIN_COHORT, channel_of=lambda i: "post" if i < 3 else "web")
    found = compare_cohorts(frame, SPEC, "channel", "post", "web")
    assert not found.steps
    assert any(str(MIN_COHORT) in reason for reason in found.refused)


def test_without_a_clock_there_is_no_difference_to_decompose() -> None:
    frame = log(4 * MIN_COHORT, channel_of=lambda i: "post" if i % 2 else "web")
    spec = EventLogSpec(case_id="case", activity="act")
    found = compare_cohorts(frame, spec, "channel", "post", "web")
    assert not found.steps
    assert any("thoi gian" in reason for reason in found.refused)


def test_a_group_that_is_not_slower_is_said_so_rather_than_ranked() -> None:
    frame = log(4 * MIN_COHORT, channel_of=lambda i: "post" if i % 2 else "web")
    found = compare_cohorts(frame, SPEC, "channel", "post", "web")
    assert not found.steps
    assert any("khong cham hon" in reason for reason in found.refused)


def test_comparing_against_everything_else_needs_no_second_value() -> None:
    frame = log(
        4 * MIN_COHORT,
        channel_of=lambda i: "post" if i % 2 else "web",
        slow_of=lambda i: 10 if i % 2 else 1,
    )
    found = compare_cohorts(frame, SPEC, "channel", "post")
    assert found.steps


def test_the_context_names_the_steps_and_carries_no_figures() -> None:
    # A number in front of the model is a number it can copy into a sentence.
    frame = log(
        4 * MIN_COHORT,
        channel_of=lambda i: "post" if i % 2 else "web",
        slow_of=lambda i: 10 if i % 2 else 1,
    )
    found = compare_cohorts(frame, SPEC, "channel", "post", "web")
    for row in found.as_context():
        for name, value in row.items():
            if name.endswith("_key"):
                assert value in found.metrics
            else:
                assert not isinstance(value, float)


def test_the_same_log_compares_the_same_way_twice() -> None:
    frame = log(
        4 * MIN_COHORT,
        channel_of=lambda i: "post" if i % 2 else "web",
        slow_of=lambda i: 10 if i % 2 else 1,
    )
    first = compare_cohorts(frame, SPEC, "channel", "post", "web")
    second = compare_cohorts(frame, SPEC, "channel", "post", "web")
    assert {key: metric.value for key, metric in first.metrics.items()} == {
        key: metric.value for key, metric in second.metrics.items()
    }


# --- the real log ------------------------------------------------------------------


@pytest.mark.skipif(not PERMIT.exists(), reason="can log cap phep that")
def test_the_real_log_finds_its_own_comparable_attributes() -> None:
    frame = pd.read_csv(PERMIT)
    spec = EventLogSpec(
        case_id="case:concept:name",
        activity="concept:name",
        timestamp="time:timestamp",
        resource="org:resource",
    )
    found = {attribute.name for attribute in case_attributes(frame, spec)}
    assert "case:channel" in found
    assert "case:department" in found
    # Event-level and identifier-like columns stay out.
    assert "concept:name" not in found
    assert "case:enddate" not in found


@pytest.mark.skipif(not PERMIT.exists(), reason="can log cap phep that")
def test_the_real_log_puts_the_postal_gap_in_a_few_handovers() -> None:
    # The finding this module exists to produce: postal intake is roughly two
    # hundred times slower, and a third of that sits in one handover.
    frame = pd.read_csv(PERMIT)
    spec = EventLogSpec(
        case_id="case:concept:name",
        activity="concept:name",
        timestamp="time:timestamp",
        resource="org:resource",
    )
    found = compare_cohorts(frame, spec, "case:channel", "Post", "Internet")
    assert found.steps
    assert found.steps[0].share_of_gap_pct > 25.0
    assert sum(step.share_of_gap_pct for step in found.steps[:3]) > 50.0
