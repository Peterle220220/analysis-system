"""Process mining, measured against logs whose answers are known by hand.

Two kinds of test here and both are needed.

The small hand-built logs pin down the arithmetic: a log with three cases taking
two paths has one answer and it can be written down in advance. Synthetic data is
good for that and bad for everything else, because it never contains the thing
that actually breaks a miner.

So the real BPI 2019 slice is used too. It already earned its place once: a role
guessed by pattern matching bound `case_id` to `case_company`, and every variant
number downstream was wrong in a way no generated log would have produced.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from analysis_system.domains.execution_engine.process_mining import (
    MIN_CASES,
    MIN_MEDIAN_OBSERVATIONS,
    EventLogSpec,
    ProcessMiningError,
    mine_process,
    slug_map,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "bpi19_slice.csv"

SPEC = EventLogSpec(case_id="case", activity="act", timestamp="ts", resource="who")


def log(rows: list[tuple[str, str, str, str]]) -> pd.DataFrame:
    """A log from (case, activity, timestamp, resource) tuples."""
    return pd.DataFrame(rows, columns=["case", "act", "ts", "who"])


def straight(cases: int, path: tuple[str, ...] = ("A", "B", "C")) -> pd.DataFrame:
    """`cases` cases all taking the same path, one hour apart."""
    rows = [
        (f"c{index}", step, f"2026-01-0{1 + position}T0{index % 8}:00:00Z", "u1")
        for index in range(cases)
        for position, step in enumerate(path)
    ]
    return log(rows)


def values(outcome: object) -> dict[str, float]:
    """Metric keys to their bare numbers, for readable assertions."""
    return {key: metric.value for key, metric in outcome.metrics.items()}  # type: ignore[attr-defined]


# --- the arithmetic, on logs whose answers are known ----------------------------


def test_it_counts_cases_events_and_activities() -> None:
    outcome = mine_process(straight(6), SPEC)
    numbers = values(outcome)
    assert numbers["process.cases"] == 6
    assert numbers["process.events"] == 18
    assert numbers["process.activities.distinct"] == 3
    assert numbers["process.events.per_case.mean"] == 3


def test_one_path_taken_by_everybody_is_one_variant_at_full_share() -> None:
    numbers = values(mine_process(straight(6), SPEC))
    assert numbers["process.variants"] == 1
    assert numbers["process.variant.1.share_pct"] == 100.0
    assert numbers["process.variant.1.cases"] == 6


def test_a_second_path_shows_up_with_its_own_share() -> None:
    rows = [
        *[
            (f"c{i}", step, f"2026-01-0{p + 1}T00:00:00Z", "u1")
            for i in range(6)
            for p, step in enumerate(("A", "B", "C"))
        ],
        *[
            (f"d{i}", step, f"2026-01-0{p + 1}T00:00:00Z", "u1")
            for i in range(2)
            for p, step in enumerate(("A", "C"))
        ],
    ]
    outcome = mine_process(log(rows), SPEC)
    numbers = values(outcome)
    assert numbers["process.cases"] == 8
    assert numbers["process.variants"] == 2
    assert numbers["process.variant.1.share_pct"] == 75.0
    assert numbers["process.variant.2.share_pct"] == 25.0
    assert outcome.variants[0].trace == ("A", "B", "C")
    assert outcome.variants[1].trace == ("A", "C")


def test_a_repeat_and_an_immediate_repeat_are_counted_apart() -> None:
    # They mean different things to whoever has to fix the process: a loop back
    # for correction is not the same problem as a step logged twice.
    rows = [
        ("c1", "A", "2026-01-01T00:00:00Z", "u1"),
        ("c1", "B", "2026-01-01T01:00:00Z", "u1"),
        ("c1", "A", "2026-01-01T02:00:00Z", "u1"),  # loop back
        *[
            (f"c{i}", step, f"2026-01-0{p + 1}T00:00:00Z", "u1")
            for i in range(2, 6)
            for p, step in enumerate(("A", "B"))
        ],
        ("c9", "A", "2026-01-01T00:00:00Z", "u1"),
        ("c9", "A", "2026-01-01T01:00:00Z", "u1"),  # same step twice in a row
    ]
    numbers = values(mine_process(log(rows), SPEC))
    assert numbers["process.rework.cases"] == 2
    assert numbers["process.selfloop.cases"] == 1


def test_the_handover_costing_the_most_time_is_reported_first() -> None:
    # Ranked by what the process loses, not by what one case waits. A real log
    # put three handovers seen three times each above one that happens 791
    # times and costs sixty times more delay in total.
    rows = []
    for index in range(12):
        rows.append((f"c{index}", "A", "2026-01-01T00:00:00Z", "u1"))
        rows.append((f"c{index}", "B", "2026-01-01T01:00:00Z", "u1"))  # 1 hour
        rows.append((f"c{index}", "C", "2026-01-02T01:00:00Z", "u1"))  # 24 hours
    outcome = mine_process(log(rows), SPEC)
    assert outcome.transitions[0].source == "B"
    assert outcome.transitions[0].target == "C"
    assert outcome.transitions[0].total_hours == 24.0 * 12
    assert outcome.transitions[0].median_hours == 24.0
    assert values(outcome)["process.wait.B__to__C.total_hours"] == 288.0


def test_a_rare_slow_step_does_not_outrank_a_frequent_costly_one() -> None:
    # The failure this exists for, in miniature. One handover waits ten times
    # longer but happens twice; the other is quick but happens on every case and
    # costs the process more in total. Ranking by typical wait put the first one
    # at the top of a real log's bottleneck list, on three observations.
    rows = []
    for index in range(30):
        rows.append((f"c{index}", "A", "2026-01-01T00:00:00Z", "u1"))
        rows.append((f"c{index}", "B", "2026-01-01T01:00:00Z", "u1"))  # 1h x 30
    for index in range(2):
        rows.append((f"r{index}", "A", "2026-01-01T00:00:00Z", "u1"))
        rows.append((f"r{index}", "Z", "2026-01-01T10:00:00Z", "u1"))  # 10h x 2
    outcome = mine_process(log(rows), SPEC)

    assert outcome.transitions[0].target == "B"
    assert outcome.transitions[0].total_hours == 30.0
    # The slower-per-case handover is still reported, just not first, and
    # without a typical wait because two observations cannot support one.
    rare = next(step for step in outcome.transitions if step.target == "Z")
    assert rare.total_hours == 20.0
    assert rare.median_hours is None


def test_case_duration_is_measured_end_to_end() -> None:
    numbers = values(mine_process(straight(6, ("A", "B", "C")), SPEC))
    # Days 1 -> 3 in the generator, so two days.
    assert numbers["process.duration.median_hours"] == 48.0


# --- what it refuses to say ------------------------------------------------------


def test_too_few_cases_gets_counts_but_no_shares() -> None:
    # A share computed from three cases is 33%, and 33% is what gets quoted on.
    outcome = mine_process(straight(MIN_CASES - 1), SPEC)
    numbers = values(outcome)
    assert numbers["process.cases"] == MIN_CASES - 1
    assert not [key for key in numbers if "share_pct" in key]
    assert not [key for key in numbers if "rework" in key]
    assert any(str(MIN_CASES) in reason for reason in outcome.refused)


def test_a_handover_seen_twice_gets_a_total_but_no_typical_wait() -> None:
    # Two different requirements for two different statistics. A sum of two
    # waits is exactly the delay those two cases suffered; a median of two is a
    # coincidence with a decimal point.
    rows = [
        *[
            (f"c{i}", step, f"2026-01-0{p + 1}T00:00:00Z", "u1")
            for i in range(6)
            for p, step in enumerate(("A", "B"))
        ],
        ("c0", "RARE", "2026-01-05T00:00:00Z", "u1"),
        ("c1", "RARE", "2026-01-05T00:00:00Z", "u1"),
    ]
    outcome = mine_process(log(rows), SPEC)
    numbers = values(outcome)
    assert numbers["process.activity.RARE.events"] == 2
    assert numbers["process.wait.B__to__RARE.total_hours"] > 0
    assert "process.wait.B__to__RARE.median_hours" not in numbers
    assert any("DIEN HINH" in reason for reason in outcome.refused)


def test_a_handover_seen_often_enough_does_get_a_typical_wait() -> None:
    rows = [
        (f"c{index}", step, f"2026-01-0{position + 1}T00:00:00Z", "u1")
        for index in range(MIN_MEDIAN_OBSERVATIONS + 2)
        for position, step in enumerate(("A", "B"))
    ]
    outcome = mine_process(log(rows), SPEC)
    assert "process.wait.A__to__B.median_hours" in values(outcome)


def test_without_a_timestamp_the_order_is_measured_but_no_timing_is() -> None:
    frame = straight(6).drop(columns=["ts"])
    outcome = mine_process(frame, EventLogSpec(case_id="case", activity="act", resource="who"))
    numbers = values(outcome)
    assert numbers["process.variants"] == 1  # sequence still measurable
    assert not [key for key in numbers if "hours" in key]
    assert any("thoi gian" in reason for reason in outcome.refused)


def test_timestamps_that_mostly_do_not_parse_stop_every_timing() -> None:
    frame = straight(6)
    frame.loc[frame.index[:12], "ts"] = "khong phai ngay"
    outcome = mine_process(frame, SPEC)
    numbers = values(outcome)
    assert numbers["process.cases"] == 6  # sequence work continues
    assert not [key for key in numbers if "hours" in key]
    assert any("doc duoc" in reason for reason in outcome.refused)


def test_a_missing_resource_column_is_said_out_loud() -> None:
    # Silence would read as "nothing to report" rather than "not checked".
    outcome = mine_process(
        straight(6), EventLogSpec(case_id="case", activity="act", timestamp="ts")
    )
    assert any("nguoi thuc hien" in reason for reason in outcome.refused)


def test_rows_with_no_case_id_are_dropped_and_counted() -> None:
    frame = straight(6)
    frame.loc[frame.index[0], "case"] = None
    outcome = mine_process(frame, SPEC)
    assert values(outcome)["process.events"] == 17
    assert any("bo 1 dong" in reason for reason in outcome.refused)


def test_a_clock_running_backwards_does_not_become_a_negative_wait() -> None:
    rows = [
        *[
            (f"c{i}", step, ts, "u1")
            for i in range(6)
            for step, ts in (("A", "2026-01-02T00:00:00Z"), ("B", "2026-01-01T00:00:00Z"))
        ],
    ]
    outcome = mine_process(log(rows), SPEC)
    assert all(
        transition.median_hours is None or transition.median_hours >= 0
        for transition in outcome.transitions
    )
    assert all(value >= 0 for key, value in values(outcome).items() if key.endswith("_hours"))


def test_a_column_the_spec_names_but_the_table_lacks_is_an_error_not_a_refusal() -> None:
    # Guessing which column was meant is how an analysis measures the wrong thing.
    with pytest.raises(ProcessMiningError, match="khong co cot"):
        mine_process(straight(6), EventLogSpec(case_id="khong_ton_tai", activity="act"))


# --- determinism, which criterion S1 depends on ----------------------------------


def test_the_same_log_twice_gives_the_same_numbers() -> None:
    frame = straight(8)
    assert values(mine_process(frame, SPEC)) == values(mine_process(frame, SPEC))


def test_rows_arriving_in_a_different_order_give_the_same_variants() -> None:
    # A log exported twice rarely comes back in the same row order. If that
    # changed the variant set, two runs of one analysis would disagree and the
    # cause would be invisible.
    frame = straight(8)
    shuffled = frame.iloc[::-1].reset_index(drop=True)
    assert values(mine_process(frame, SPEC)) == values(mine_process(shuffled, SPEC))


def test_events_sharing_a_timestamp_keep_the_order_they_arrived_in() -> None:
    # Systems write to the second, so ties are constant in real logs. Breaking
    # them by whatever the sort felt like would make S1 fail for a reason nobody
    # would think to look for.
    rows = [
        (f"c{index}", step, "2026-01-01T00:00:00Z", "u1")
        for index in range(6)
        for step in ("A", "B", "C")
    ]
    first = mine_process(log(rows), SPEC)
    assert first.variants[0].trace == ("A", "B", "C")
    assert values(first) == values(mine_process(log(rows), SPEC))


# --- metric keys stay usable -----------------------------------------------------


def test_two_activity_names_that_flatten_alike_do_not_share_a_key() -> None:
    # Without this one of them overwrites the other's number and nothing says so.
    mapping = slug_map(["Approve (A)", "Approve [A]", "Approve (A)"])
    assert len(set(mapping.values())) == 2


def test_an_activity_name_never_puts_a_dot_inside_a_metric_key() -> None:
    # Keys are parsed on dots. A name carrying one would split into segments
    # that mean nothing, and the placeholder would never resolve.
    rows = [
        (f"c{index}", step, f"2026-01-0{position + 1}T00:00:00Z", "u1")
        for index in range(6)
        for position, step in enumerate(("Step 1.0", "Step 2.0"))
    ]
    outcome = mine_process(log(rows), SPEC)
    for key in outcome.metrics:
        assert ".0" not in key.replace("_pct", "")


def test_durations_carry_their_unit_so_nobody_reads_hours_as_days() -> None:
    outcome = mine_process(straight(6), SPEC)
    assert outcome.metrics["process.duration.median_hours"].unit == "giờ"
    assert outcome.metrics["process.variant.1.share_pct"].unit == "%"


# --- what gets handed to the model ------------------------------------------------


def test_a_long_path_is_shortened_and_says_that_it_was() -> None:
    # Printing a sixty-step trace whole is unreadable; cutting it silently is
    # worse, because the reader believes the process has six steps.
    path = tuple(f"S{index}" for index in range(12))
    rows = [
        (f"c{index}", step, f"2026-01-01T{position:02d}:00:00Z", "u1")
        for index in range(6)
        for position, step in enumerate(path)
    ]
    outcome = mine_process(log(rows), SPEC)
    preview = outcome.variants[0].preview()
    assert preview.startswith("S0 -> S1")
    assert "+6 buoc" in preview


def test_a_short_path_is_printed_whole_with_no_ellipsis() -> None:
    outcome = mine_process(straight(6), SPEC)
    assert outcome.variants[0].preview() == "A -> B -> C"
    assert "..." not in outcome.variants[0].preview()


def test_the_context_names_the_paths_and_carries_no_figures() -> None:
    # This is what reaches the prompt. Every number in it would be a digit the
    # model could copy into a sentence, so the numbers stay behind keys and only
    # the names travel.
    outcome = mine_process(straight(6), SPEC)
    context = outcome.as_context()
    variants = [row for row in context if row["kind"] == "variant"]
    assert variants and variants[0]["path"] == "A -> B -> C"
    assert variants[0]["share_key"] == "process.variant.1.share_pct"
    for row in context:
        for name, value in row.items():
            if name.endswith("_key"):
                assert value in outcome.metrics


def test_every_waiting_step_in_the_context_points_at_a_real_metric() -> None:
    rows = []
    for index in range(12):
        rows.append((f"c{index}", "A", "2026-01-01T00:00:00Z", "u1"))
        rows.append((f"c{index}", "B", "2026-01-01T01:00:00Z", "u1"))
        rows.append((f"c{index}", "C", "2026-01-02T01:00:00Z", "u1"))
    outcome = mine_process(log(rows), SPEC)
    waits = [row for row in outcome.as_context() if row["kind"] == "wait"]
    assert waits
    assert waits[0]["from"] == "B"
    assert waits[0]["to"] == "C"
    assert outcome.metrics[waits[0]["total_hours_key"]].value > 0


# --- the spec itself -------------------------------------------------------------


def test_a_spec_without_the_two_required_roles_is_refused() -> None:
    with pytest.raises(ProcessMiningError, match="activity"):
        EventLogSpec.from_params({"case_id": "case"})


def test_a_spec_that_is_not_an_object_is_refused() -> None:
    with pytest.raises(ProcessMiningError, match="object"):
        EventLogSpec.from_params(["case", "act"])


def test_the_optional_roles_stay_optional() -> None:
    spec = EventLogSpec.from_params({"case_id": "case", "activity": "act"})
    assert spec.timestamp is None
    assert spec.resource is None
    assert spec.columns() == ("case", "act")


# --- the real log ----------------------------------------------------------------


@pytest.mark.skipif(not FIXTURE.exists(), reason="can fixture BPI19")
def test_the_real_purchase_to_pay_log_mines_end_to_end() -> None:
    frame = pd.read_csv(FIXTURE)
    outcome = mine_process(
        frame,
        EventLogSpec(
            case_id="case_id", activity="activity", timestamp="timestamp", resource="resource"
        ),
    )
    numbers = values(outcome)

    assert numbers["process.cases"] == 158
    assert numbers["process.events"] == 5000
    # Real processes fan out. A slice of 158 cases taking one path would mean
    # the roles were bound to the wrong columns - which is exactly what happened
    # once, when case_id was matched against case_company.
    assert numbers["process.variants"] > 20
    assert 0 < numbers["process.variant.1.share_pct"] < 100
    assert numbers["process.duration.median_hours"] > 0
    assert outcome.transitions, "log that phai co it nhat mot buoc ban giao do duoc"


@pytest.mark.skipif(not FIXTURE.exists(), reason="can fixture BPI19")
def test_the_real_log_gives_the_same_answer_twice() -> None:
    frame = pd.read_csv(FIXTURE)
    spec = EventLogSpec(
        case_id="case_id", activity="activity", timestamp="timestamp", resource="resource"
    )
    assert values(mine_process(frame, spec)) == values(mine_process(frame, spec))
