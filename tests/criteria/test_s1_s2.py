"""S1 and S2, each proved by a whole run rather than argued from parts."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from analysis_system.agents.a5_validator import ValidatorAgent
from analysis_system.core import storage
from analysis_system.core.boundary import load_manifest
from analysis_system.core.hashing import canonical_hash, canonical_hash_text
from analysis_system.core.settings import Settings
from analysis_system.models.base import ScopeToken, TaskRequest
from tests.criteria.harness import (
    MANIFEST_DIR,
    approve_all,
    plan,
    run_to_completion,
    runner_for,
    settings_in,
    staged_source,
)

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


def outputs_of(settings: Settings) -> dict[str, str]:
    """The content hash of every table a run produced."""
    folders = (
        ("staging", settings.layers.staging),
        ("clean", settings.layers.clean),
        ("mart", settings.layers.mart),
    )
    return {
        f"{name}/{path.name}": canonical_hash(storage.read_parquet(path))
        for name, folder in folders
        for path in sorted(folder.glob("*.parquet"))
    }


def audit_events(run_dir: Path) -> list[dict[str, object]]:
    """Every line of the run's audit log, parsed."""
    return [
        json.loads(line)
        for line in (run_dir / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    ]


# --- S1: chay lai cung input ra cung output -------------------------------------


def test_s1_two_runs_on_the_same_input_agree_on_every_hash(tmp_path: Path) -> None:
    # Different run ids, different directories. If either could move a hash,
    # "the same input gives the same output" would be untrue in the only way
    # that matters.
    first, settings_a, _ = run_to_completion(tmp_path / "one", "r_a")
    second, settings_b, _ = run_to_completion(tmp_path / "two", "r_b")
    assert first.is_complete and second.is_complete
    assert outputs_of(settings_a) == outputs_of(settings_b)
    assert outputs_of(settings_a)  # and it actually produced something


def test_s1_the_hash_ignores_what_is_not_the_data() -> None:
    # A report differing only in run id and timestamp is the same report.
    first = "run_id: r_a\ntimestamp: 2026-01-01\nrows: 5000\n"
    second = "run_id: r_b\ntimestamp: 2026-09-02\nrows: 5000\n"
    assert canonical_hash_text(first) == canonical_hash_text(second)


def test_s1_a_single_changed_cell_changes_the_hash(tmp_path: Path) -> None:
    # The other half of the claim: equal hashes must mean equal data.
    _, settings, _ = run_to_completion(tmp_path, "r_c")
    before = outputs_of(settings)
    mart = next(settings.layers.mart.glob("*.parquet"))
    frame = storage.read_parquet(mart)
    frame.iloc[0, 0] = "doi mot o duy nhat"
    storage.write_parquet(frame, mart)
    assert outputs_of(settings) != before


def test_s1_a_run_stays_repeatable_through_its_human_gates(tmp_path: Path) -> None:
    # A gate replays its stored decision instead of asking again, which is the
    # only thing that lets a run containing a person be reproducible at all.
    outcome, _, _ = run_to_completion(tmp_path, "r_gates")
    assert outcome.is_complete
    assert set(outcome.state.gates) == {"gate_t3_clean", "gate_t6_analyse"}


# --- S2: khong agent nao vuot boundary ------------------------------------------


def test_s2_a_clean_run_records_no_boundary_violation(tmp_path: Path) -> None:
    outcome, _, run_dir = run_to_completion(tmp_path, "r_clean")
    assert outcome.is_complete
    assert "BOUNDARY_VIOLATION" not in [record["event"] for record in audit_events(run_dir)]
    assert all(task.phase != "BOUNDARY_VIOLATION" for task in outcome.state.tasks.values())


def test_s2_an_agent_reaching_outside_its_scope_is_stopped(tmp_path: Path) -> None:
    # The criterion means nothing unless a violation would actually be caught.
    # A5's manifest allows writing to validation:// only; this token grants the
    # mart, and must be refused before the agent runs at all.
    agent = ValidatorAgent(settings_in(tmp_path), MANIFEST_DIR)
    token = ScopeToken(
        run_id="r_bad",
        task_id="t_bad",
        agent_id="a5_validator",
        allow_read=("mart://**",),
        allow_write=("mart://**",),
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
    )
    result = agent.run(TaskRequest(scope=token, instruction="x"), now=NOW)
    assert result.status == "BOUNDARY_VIOLATION"
    assert result.error is not None
    assert "ghi" in result.error.message


def test_s2_the_audit_log_holds_what_the_check_needs(tmp_path: Path) -> None:
    # S2 is checked by reading the log, so the log has to carry the events that
    # make reading it meaningful.
    _, _, run_dir = run_to_completion(tmp_path, "r_log")
    events = {record["event"] for record in audit_events(run_dir)}
    assert {
        "RUN_STARTED",
        "PLAN_CREATED",
        "SCOPE_ISSUED",
        "TASK_STARTED",
        "TASK_COMPLETED",
        "VALIDATION_RESULT",
        "HUMAN_GATE",
        "RUN_ENDED",
    } <= events


def test_s2_every_token_issued_stayed_inside_its_manifest(tmp_path: Path) -> None:
    # A token wider than its manifest cannot be built, because it is cut from
    # it. This checks the record agrees with that claim.
    _, _, run_dir = run_to_completion(tmp_path, "r_scope")
    issued = [record for record in audit_events(run_dir) if record["event"] == "SCOPE_ISSUED"]
    assert issued
    for record in issued:
        manifest = load_manifest(str(record["agent_id"]), MANIFEST_DIR)
        detail = record["detail"]
        assert isinstance(detail, dict)
        assert set(detail["allow_write"]) <= set(manifest.allow.write)
        assert set(detail["allow_read"]) <= set(manifest.allow.read)


def test_s2_a_run_paused_at_a_gate_records_no_violation_either(tmp_path: Path) -> None:
    settings = settings_in(tmp_path)
    source = staged_source(settings)
    run_dir = tmp_path / "runs" / "r_paused"
    outcome = runner_for(settings, run_dir).run(plan(), source, run_id="r_paused")
    assert outcome.is_paused
    approve_all(run_dir, str(outcome.paused_gate))
    assert "BOUNDARY_VIOLATION" not in [record["event"] for record in audit_events(run_dir)]
