"""Conformance: rules about sequences, judged by the referee.

Every other check in validation.py looks at a row. These two look at a case, and
that difference is where the interesting failures live: each row can be perfectly
valid and the case still wrong.

The tests that matter most here are the ones about *not being able to check*. A
control that silently passes when it could not run is worse than no control at
all, because somebody has now been told the process is clean.
"""

from __future__ import annotations

import pandas as pd
import pytest

from analysis_system.agents.a5_validator import build_checks, count_checks
from analysis_system.services.process_mining import EventLogSpec
from analysis_system.services.validation import (
    ValidationSpecError,
    check_segregation_of_duties,
    check_sequence_order,
)

SPEC = EventLogSpec(case_id="case", activity="act", timestamp="ts", resource="who")


def log(rows: list[tuple[str, str, str, str]]) -> pd.DataFrame:
    """A log from (case, activity, timestamp, resource) tuples."""
    return pd.DataFrame(rows, columns=["case", "act", "ts", "who"])


CLEAN = log(
    [
        ("c1", "Nhan hang", "2026-01-01T00:00:00Z", "an"),
        ("c1", "Nhan hoa don", "2026-01-02T00:00:00Z", "binh"),
        ("c2", "Nhan hang", "2026-01-01T00:00:00Z", "an"),
        ("c2", "Nhan hoa don", "2026-01-03T00:00:00Z", "binh"),
    ]
)

ORDER_RULE = [("Nhan hang", "Nhan hoa don")]


# --- mandatory order -------------------------------------------------------------


def test_a_log_that_respects_the_order_reports_nothing() -> None:
    assert check_sequence_order(CLEAN, SPEC, ORDER_RULE) == []


def test_the_later_step_happening_first_is_caught() -> None:
    frame = log(
        [
            ("c1", "Nhan hoa don", "2026-01-01T00:00:00Z", "binh"),
            ("c1", "Nhan hang", "2026-01-02T00:00:00Z", "an"),
        ]
    )
    failures = check_sequence_order(frame, SPEC, ORDER_RULE)
    assert len(failures) == 1
    assert failures[0].count == 1
    assert failures[0].sample_rows


def test_the_earlier_step_never_happening_at_all_is_caught_and_named() -> None:
    # The same defect from a control point of view - the step meant to authorise
    # the next one did not - but a reader needs to know which of the two it was.
    frame = log([("c1", "Nhan hoa don", "2026-01-01T00:00:00Z", "binh")])
    failures = check_sequence_order(frame, SPEC, ORDER_RULE)
    assert len(failures) == 1
    assert "khong he co" in failures[0].detail


def test_a_case_missing_the_later_step_entirely_is_not_a_violation() -> None:
    # Nothing happened that needed authorising. Flagging this would train people
    # to ignore the check.
    frame = log([("c1", "Nhan hang", "2026-01-01T00:00:00Z", "an")])
    assert check_sequence_order(frame, SPEC, ORDER_RULE) == []


def test_only_the_offending_cases_are_counted_not_the_whole_log() -> None:
    frame = pd.concat(
        [CLEAN, log([("c9", "Nhan hoa don", "2026-01-01T00:00:00Z", "binh")])],
        ignore_index=True,
    )
    failures = check_sequence_order(frame, SPEC, ORDER_RULE)
    assert failures[0].count == 1


def test_order_comes_from_the_timestamp_not_from_the_row_order() -> None:
    # An export ordered by insertion would otherwise pass a log that violates
    # the rule, and the reason would be invisible.
    frame = log(
        [
            ("c1", "Nhan hang", "2026-01-09T00:00:00Z", "an"),
            ("c1", "Nhan hoa don", "2026-01-01T00:00:00Z", "binh"),
        ]
    )
    assert check_sequence_order(frame, SPEC, ORDER_RULE)


# --- separation of duties ---------------------------------------------------------

SOD_RULE = [("Tao don", "Duyet don")]


def test_two_different_people_doing_the_two_steps_is_fine() -> None:
    frame = log(
        [
            ("c1", "Tao don", "2026-01-01T00:00:00Z", "an"),
            ("c1", "Duyet don", "2026-01-02T00:00:00Z", "binh"),
        ]
    )
    assert check_segregation_of_duties(frame, SPEC, SOD_RULE) == []


def test_one_person_doing_both_is_caught_and_named() -> None:
    frame = log(
        [
            ("c1", "Tao don", "2026-01-01T00:00:00Z", "an"),
            ("c1", "Duyet don", "2026-01-02T00:00:00Z", "an"),
        ]
    )
    failures = check_segregation_of_duties(frame, SPEC, SOD_RULE)
    assert len(failures) == 1
    # "Somebody did both" is not something anyone can act on.
    assert "an" in failures[0].detail


def test_the_same_person_doing_both_in_two_different_cases_is_fine() -> None:
    # The control is about one case. A buyer who raises orders and approves
    # other people's is doing their job.
    frame = log(
        [
            ("c1", "Tao don", "2026-01-01T00:00:00Z", "an"),
            ("c1", "Duyet don", "2026-01-02T00:00:00Z", "binh"),
            ("c2", "Tao don", "2026-01-01T00:00:00Z", "binh"),
            ("c2", "Duyet don", "2026-01-02T00:00:00Z", "an"),
        ]
    )
    assert check_segregation_of_duties(frame, SPEC, SOD_RULE) == []


def test_separation_of_duties_still_works_without_a_usable_timestamp() -> None:
    # Doing both is the violation whichever came first, so this check does not
    # need order - and refusing it for want of a clock would be a control lost
    # for no reason.
    frame = log(
        [
            ("c1", "Tao don", "khong phai ngay", "an"),
            ("c1", "Duyet don", "khong phai ngay", "an"),
        ]
    )
    spec = EventLogSpec(case_id="case", activity="act", resource="who")
    assert check_segregation_of_duties(frame, spec, SOD_RULE)


# --- what happens when the check cannot be carried out ----------------------------


def test_a_check_that_cannot_run_fails_rather_than_passing_quietly() -> None:
    # The whole point. A5 halts on any failure, and refusing to analyse a
    # process whose order nobody can establish is the right thing to halt on.
    frame = log(
        [
            ("c1", "Nhan hang", "khong phai ngay", "an"),
            ("c1", "Nhan hoa don", "cung khong phai", "binh"),
        ]
    )
    failures = check_sequence_order(frame, SPEC, ORDER_RULE)
    assert len(failures) == 1
    assert failures[0].test.endswith(":unverifiable")
    assert "KHONG KIEM DUOC" in failures[0].detail


def test_an_unverifiable_result_is_not_dressed_up_as_a_violation() -> None:
    # It says the check did not run; it does not claim the data broke the rule.
    frame = log([("c1", "Nhan hang", "khong phai ngay", "an")])
    failure = check_sequence_order(frame, SPEC, ORDER_RULE)[0]
    assert failure.count == 0
    assert failure.sample_rows == ()


def test_separation_of_duties_without_a_resource_column_says_so() -> None:
    spec = EventLogSpec(case_id="case", activity="act", timestamp="ts")
    failures = check_segregation_of_duties(CLEAN, spec, SOD_RULE)
    assert failures[0].test.endswith(":unverifiable")
    assert "nguoi thuc hien" in failures[0].detail


def test_a_column_the_spec_names_but_the_log_lacks_is_unverifiable() -> None:
    spec = EventLogSpec(case_id="khong_ton_tai", activity="act")
    assert check_sequence_order(CLEAN, spec, ORDER_RULE)[0].test.endswith(":unverifiable")


# --- how A5 takes them in ----------------------------------------------------------


def test_a5_runs_the_conformance_rules_from_its_spec() -> None:
    spec = {
        "event_log": {"case_id": "case", "activity": "act", "timestamp": "ts", "resource": "who"},
        "sequence_order": [{"before": "Nhan hang", "after": "Nhan hoa don"}],
    }
    frame = log([("c1", "Nhan hoa don", "2026-01-01T00:00:00Z", "binh")])
    assert build_checks(frame, spec)
    assert build_checks(CLEAN, spec) == []


def test_a5_counts_conformance_rules_among_its_checks() -> None:
    # A check that runs but is not counted makes the pass total wrong, and the
    # pass total is what a person reads to decide the table is sound.
    spec = {
        "event_log": {"case_id": "case", "activity": "act"},
        "sequence_order": [{"before": "a", "after": "b"}],
        "segregation_of_duties": [{"first": "a", "second": "b"}],
    }
    assert count_checks(spec) == 2


def test_conformance_rules_without_an_event_log_block_are_refused() -> None:
    # Guessing which column is the case id has already gone wrong once here, by
    # pattern matching, for an entire analysis.
    with pytest.raises(ValidationSpecError, match="event_log"):
        build_checks(CLEAN, {"sequence_order": [{"before": "a", "after": "b"}]})


def test_a_conformance_rule_missing_an_activity_name_is_refused() -> None:
    with pytest.raises(ValidationSpecError, match="before"):
        build_checks(
            CLEAN,
            {
                "event_log": {"case_id": "case", "activity": "act"},
                "sequence_order": [{"after": "b"}],
            },
        )


def test_an_event_log_block_missing_a_required_role_is_refused() -> None:
    with pytest.raises(ValidationSpecError, match="activity"):
        build_checks(
            CLEAN,
            {
                "event_log": {"case_id": "case"},
                "sequence_order": [{"before": "a", "after": "b"}],
            },
        )


def test_a_spec_with_no_conformance_rules_needs_no_event_log() -> None:
    # The rest of the validator must keep working on tables that are not logs.
    assert build_checks(CLEAN, {"not_null": ["case"]}) == []
