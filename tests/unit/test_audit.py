"""Audit log tests: the log must be complete, append-only, and readable back."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from analysis_system.services.audit import (
    REQUIRED_EVENTS,
    AuditError,
    AuditLog,
    AuditRecord,
)

NOW = datetime(2026, 8, 30, 10, 12, 3, tzinfo=UTC)


@pytest.fixture
def log(tmp_path: Path) -> AuditLog:
    """A log writing into a throwaway run directory."""
    run_dir = tmp_path / "r_8f3a"
    run_dir.mkdir()
    return AuditLog(run_dir / "audit.jsonl", "r_8f3a")


def test_the_spec_requires_exactly_twelve_events() -> None:
    assert len(REQUIRED_EVENTS) == 12
    assert len(set(REQUIRED_EVENTS)) == 12


def test_a_record_round_trips_through_one_json_line(log: AuditLog) -> None:
    log.record(
        "TASK_COMPLETED",
        now=NOW,
        task_id="t_04",
        agent_id="a3_cleaner",
        status="OK",
        input_hash="3f9a",
        output_hash="7c21",
        metrics={"rows_in": 482119.0, "rows_out": 481808.0},
    )
    (record,) = log.read_all()
    assert record.event == "TASK_COMPLETED"
    assert record.agent_id == "a3_cleaner"
    assert record.metrics["rows_out"] == 481808.0
    assert record.ts == NOW


def test_each_event_is_one_line_and_nothing_is_rewritten(log: AuditLog) -> None:
    for offset, event in enumerate(("RUN_STARTED", "PLAN_CREATED", "RUN_ENDED")):
        log.record(event, now=NOW + timedelta(seconds=offset))  # type: ignore[arg-type]
    lines = log.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert log.events() == ["RUN_STARTED", "PLAN_CREATED", "RUN_ENDED"]


def test_appending_never_loses_earlier_history(log: AuditLog) -> None:
    log.record("RUN_STARTED", now=NOW)
    first = log.path.read_text(encoding="utf-8")
    log.record("RUN_ENDED", now=NOW + timedelta(minutes=1))
    assert log.path.read_text(encoding="utf-8").startswith(first)


def test_every_required_event_name_is_accepted(log: AuditLog) -> None:
    for event in REQUIRED_EVENTS:
        log.record(event, now=NOW)  # type: ignore[arg-type]
    assert log.events() == list(REQUIRED_EVENTS)


def test_an_invented_event_name_is_refused(log: AuditLog) -> None:
    with pytest.raises(AuditError):
        log.record("SOMETHING_I_MADE_UP", now=NOW)  # type: ignore[arg-type]


def test_a_corrupt_line_is_reported_with_its_number(log: AuditLog) -> None:
    log.record("RUN_STARTED", now=NOW)
    with log.path.open("a", encoding="utf-8") as stream:
        stream.write("day khong phai json\n")
    with pytest.raises(AuditError) as error:
        log.read_all()
    assert "Dong 2" in str(error.value)


def test_reading_a_log_that_does_not_exist_yet_is_empty(tmp_path: Path) -> None:
    assert AuditLog(tmp_path / "chua-co.jsonl", "r_x").read_all() == []


def test_boundary_violations_are_findable_for_criterion_s2(log: AuditLog) -> None:
    log.record("RUN_STARTED", now=NOW)
    log.record(
        "BOUNDARY_VIOLATION",
        now=NOW,
        task_id="t_09",
        agent_id="a3_cleaner",
        detail={"reason": "ghi ra raw://"},
    )
    violations = log.unresolved_violations()
    assert len(violations) == 1
    assert violations[0].detail["reason"] == "ghi ra raw://"


def test_lines_are_sorted_json_so_they_diff_cleanly() -> None:
    record = AuditRecord(ts=NOW, run_id="r_1", event="RUN_STARTED", agent_id="a1", task_id="t_1")
    line = record.to_line()
    assert line.index('"agent_id"') < line.index('"event"') < line.index('"run_id"')
    # exclude_none keeps unused fields out of the line entirely
    assert "status" not in line
