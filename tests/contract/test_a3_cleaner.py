"""A3 tests: it proposes, a human approves, and only then does it clean."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from analysis_system.agents.a3_cleaner import (
    APPROVED_RULES_PARAM,
    CLEAN_URI,
    CleanerAgent,
    build_proposal_request,
    summarise_diff,
    to_rule_specs,
)
from analysis_system.contracts.agents import ProposedRule, RuleProposal
from analysis_system.contracts.base import DataRef, ScopeToken, TaskRequest
from analysis_system.services import storage
from analysis_system.services.llm import CassetteProvider, LlmClient, LlmResponse
from analysis_system.services.rulebook import DiffEntry
from analysis_system.settings import LAYER_NAMES, LayerPaths, Settings, load_settings, resolve

NOW = datetime(2026, 8, 31, 11, 0, tzinfo=UTC)
MANIFEST_DIR = Path(__file__).resolve().parents[2] / "config" / "manifests"


def dirty() -> pd.DataFrame:
    """Forty rows: whitespace to trim, plus exactly one duplicate pair.

    The size matters. With only four rows, removing a single duplicate is a 25
    percent loss and trips the 5 percent ceiling - the guard would fire on a
    perfectly ordinary de-duplication. One duplicate in forty rows is 2.5
    percent, which is what a realistic clean looks like.
    """
    rows = [
        {"case_id": f"c{index}", "activity": "Create", "amount": str(index)}
        for index in range(1, 40)
    ]
    rows[0]["case_id"] = "  c1  "
    rows.append(dict(rows[-1]))
    return pd.DataFrame(rows)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    roots = {name: tmp_path / name for name in LAYER_NAMES}
    for root in roots.values():
        root.mkdir(parents=True, exist_ok=True)
    return load_settings().model_copy(update={"layers": LayerPaths(**roots)})


def token(params: dict[str, Any] | None = None, *, max_dropped: float | None = 5.0) -> ScopeToken:
    """A token matching the shipped a3_cleaner manifest."""
    return ScopeToken(
        run_id="r_1",
        task_id="t_03",
        agent_id="a3_cleaner",
        allow_read=("staging://**", "profile://**"),
        allow_write=("clean://**",),
        allow_tools=("pandas", "rulebook.apply"),
        params=params or {},
        limits={"max_rows_dropped_pct": max_dropped, "max_retries": 3},  # type: ignore[arg-type]
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )


def stage(settings: Settings, frame: pd.DataFrame) -> DataRef:
    storage.write_parquet(frame, resolve("staging://events.parquet", settings))
    return DataRef(path="staging://events.parquet", format="parquet", content_hash="a" * 64)


def request_for(scope: ScopeToken, ref: DataRef) -> TaskRequest:
    return TaskRequest(scope=scope, input_refs=(ref,), instruction="lam sach")


# --- mode one: propose only ---------------------------------------------------


def test_without_approved_rules_it_proposes_and_writes_nothing(settings: Settings) -> None:
    agent = CleanerAgent(settings, MANIFEST_DIR)
    result = agent.run(request_for(token(), stage(settings, dirty())), now=NOW)

    assert result.status == "NEEDS_REVIEW"
    assert result.payload["mode"] == "propose"
    # The whole point: nothing has been cleaned yet.
    assert not (settings.layers.clean / "events.parquet").exists()
    assert result.output_refs == ()


def test_a_proposal_from_the_model_is_carried_to_the_gate(
    settings: Settings, tmp_path: Path
) -> None:
    frame = dirty()
    cassettes = tmp_path / "cassettes"
    cassettes.mkdir()
    provider = CassetteProvider(cassettes)
    provider.record(
        build_proposal_request(frame, None),
        LlmResponse(
            data=RuleProposal(
                rules=[
                    ProposedRule(
                        rule_id="trim_whitespace",
                        columns=("case_id",),
                        reason="case_id co khoang trang thua",
                    ),
                    ProposedRule(rule_id="drop_exact_duplicates", reason="co dong trung"),
                ],
                summary="hai rule",
            ),
            provider="cassette",
            model="recorded",
        ),
    )

    agent = CleanerAgent(settings, MANIFEST_DIR, llm=LlmClient(provider))
    result = agent.run(request_for(token(), stage(settings, frame)), now=NOW)

    assert result.status == "NEEDS_REVIEW"
    assert result.payload["rule_ids"] == ["trim_whitespace", "drop_exact_duplicates"]
    assert not (settings.layers.clean / "events.parquet").exists()


# --- mode two: execute only what was approved ---------------------------------


def test_with_approved_rules_it_cleans_and_writes(settings: Settings) -> None:
    approved = [
        {"rule_id": "trim_whitespace", "columns": ["case_id"], "reason": "duyet"},
        {"rule_id": "drop_exact_duplicates", "reason": "duyet"},
    ]
    agent = CleanerAgent(settings, MANIFEST_DIR)
    result = agent.run(
        request_for(token({APPROVED_RULES_PARAM: approved}), stage(settings, dirty())), now=NOW
    )

    assert result.is_ok, result.error
    assert result.output_refs[0].path == CLEAN_URI
    assert (settings.layers.clean / "events.parquet").is_file()
    assert result.payload["rows_in"] == 40
    assert result.payload["rows_out"] == 39
    assert result.payload["rules_applied"] == ["trim_whitespace", "drop_exact_duplicates"]
    assert result.payload["content_hash"]


def test_it_runs_only_the_approved_rules_not_every_rule(settings: Settings) -> None:
    approved = [{"rule_id": "trim_whitespace", "columns": ["case_id"], "reason": "duyet"}]
    result = CleanerAgent(settings, MANIFEST_DIR).run(
        request_for(token({APPROVED_RULES_PARAM: approved}), stage(settings, dirty())), now=NOW
    )
    assert result.payload["rules_applied"] == ["trim_whitespace"]
    # Duplicates survive because de-duplication was never approved.
    assert result.payload["rows_out"] == 40


def test_the_same_rule_for_two_column_groups_stays_two_entries() -> None:
    # Merging them would force a choice nobody asked for.
    specs = to_rule_specs(
        [
            {"rule_id": "cast_numeric_safe", "columns": ["event_seq"], "reason": "a"},
            {"rule_id": "cast_numeric_safe", "columns": ["amount"], "reason": "b"},
        ]
    )
    assert len(specs) == 2
    assert [spec.columns for spec in specs] == [("event_seq",), ("amount",)]


def test_two_column_groups_approved_together_actually_clean(settings: Settings) -> None:
    frame = pd.DataFrame({"a": ["1", "2"], "b": ["3.5", "4.5"], "c": ["x", "y"]})
    approved = [
        {"rule_id": "cast_numeric_safe", "columns": ["a"], "reason": "duyet"},
        {"rule_id": "cast_numeric_safe", "columns": ["b"], "reason": "duyet"},
    ]
    result = CleanerAgent(settings, MANIFEST_DIR).run(
        request_for(token({APPROVED_RULES_PARAM: approved}), stage(settings, frame)), now=NOW
    )
    assert result.is_ok, result.error
    assert result.payload["rules_applied"] == ["cast_numeric_safe", "cast_numeric_safe"]


def test_an_invented_parameter_stops_the_run_instead_of_being_ignored(
    settings: Settings,
) -> None:
    # Exactly what a real proposal did: it asked for target_type, which no rule
    # reads. Silently ignoring it would make the approved plan a lie.
    approved = [
        {
            "rule_id": "cast_numeric_safe",
            "columns": ["a"],
            "params": {"target_type": "int64"},
            "reason": "duyet",
        }
    ]
    frame = pd.DataFrame({"a": ["1", "2"]})
    result = CleanerAgent(settings, MANIFEST_DIR).run(
        request_for(token({APPROVED_RULES_PARAM: approved}), stage(settings, frame)), now=NOW
    )
    assert result.status == "FAILED"
    assert result.error is not None
    assert "target_type" in result.error.message
    assert not (settings.layers.clean / "events.parquet").exists()


def test_the_proposal_prompt_lists_the_parameters_each_rule_reads() -> None:
    # The model invented parameters because it was only shown rule names.
    request = build_proposal_request(dirty(), None)
    assert "assume_timezone" in request.prompt


def test_an_invented_rule_is_refused_even_if_it_reaches_the_agent(settings: Settings) -> None:
    approved = [{"rule_id": "xoa_het_dong_xau", "reason": "ai do tu che"}]
    result = CleanerAgent(settings, MANIFEST_DIR).run(
        request_for(token({APPROVED_RULES_PARAM: approved}), stage(settings, dirty())), now=NOW
    )
    assert result.status == "FAILED"
    assert result.error is not None
    assert result.error.code == "RULE_OUTSIDE_RULEBOOK"
    assert not (settings.layers.clean / "events.parquet").exists()


def test_dropping_more_than_the_ceiling_halts_and_writes_nothing(settings: Settings) -> None:
    # Four rows collapsing to one is a 75 percent loss, far past the 5 percent ceiling.
    frame = pd.DataFrame({"case_id": ["c1"] * 4, "activity": ["Create"] * 4})
    approved = [{"rule_id": "drop_exact_duplicates", "reason": "duyet"}]
    result = CleanerAgent(settings, MANIFEST_DIR).run(
        request_for(token({APPROVED_RULES_PARAM: approved}), stage(settings, frame)), now=NOW
    )

    assert result.status == "FAILED"
    assert result.error is not None
    assert result.error.code == "ROWS_DROPPED_EXCEEDED"
    assert result.metrics["rows_dropped_pct"] == pytest.approx(75.0)
    # Nothing half-cleaned is left behind for someone to pick up by mistake.
    assert not (settings.layers.clean / "events.parquet").exists()


def test_standardize_datetime_still_refuses_to_guess_a_timezone(settings: Settings) -> None:
    # The refusal is reported as a failed task, not raised as a crash: the
    # Manager has to be able to record it and decide what happens next.
    frame = pd.DataFrame({"timestamp": ["2018-01-01T00:00:00Z", "2018-01-02T00:00:00Z"]})
    approved = [{"rule_id": "standardize_datetime", "columns": ["timestamp"], "reason": "duyet"}]
    result = CleanerAgent(settings, MANIFEST_DIR).run(
        request_for(token({APPROVED_RULES_PARAM: approved}), stage(settings, frame)), now=NOW
    )
    assert result.status == "FAILED"
    assert result.error is not None
    assert "assume_timezone" in result.error.message
    assert not (settings.layers.clean / "events.parquet").exists()


def test_the_approved_params_are_what_make_the_datetime_rule_run(settings: Settings) -> None:
    frame = pd.DataFrame({"timestamp": ["2018-01-01T00:00:00Z", "2018-01-02T00:00:00Z"]})
    approved = [
        {
            "rule_id": "standardize_datetime",
            "columns": ["timestamp"],
            "params": {"assume_timezone": "UTC"},
            "reason": "duyet",
        }
    ]
    result = CleanerAgent(settings, MANIFEST_DIR).run(
        request_for(token({APPROVED_RULES_PARAM: approved}), stage(settings, frame)), now=NOW
    )
    assert result.is_ok, result.error


def test_bad_params_are_reported_rather_than_ignored(settings: Settings) -> None:
    result = CleanerAgent(settings, MANIFEST_DIR).run(
        request_for(token({APPROVED_RULES_PARAM: "khong phai list"}), stage(settings, dirty())),
        now=NOW,
    )
    assert result.status == "FAILED"
    assert result.error is not None
    assert result.error.code == "BAD_PARAMS"


# --- helpers ------------------------------------------------------------------


def test_the_diff_log_is_grouped_with_a_few_examples() -> None:
    diff = tuple(
        DiffEntry("trim_whitespace", "case_id", index, "  x  ", "x", "cat khoang trang thua")
        for index in range(10)
    )
    summary = summarise_diff(diff)
    assert len(summary) == 1
    assert summary[0].count == 10
    assert len(summary[0].examples) == 3


def test_approved_entries_become_an_executable_plan() -> None:
    specs = to_rule_specs([{"rule_id": "trim_whitespace", "columns": ["a"], "params": {}}])
    assert specs[0].rule_id == "trim_whitespace"
    assert specs[0].columns == ("a",)


def test_the_proposal_prompt_carries_the_rulebook_and_no_raw_table() -> None:
    request = build_proposal_request(dirty(), None)
    assert "trim_whitespace" in request.prompt
    assert "drop_exact_duplicates" in request.prompt
    assert request.purpose == "a3_cleaner_propose"
