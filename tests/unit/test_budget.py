"""Budget tests: every ceiling must stop the job, and money is counted apart."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from analysis_system.services.budget import (
    BudgetConfig,
    BudgetError,
    BudgetExceeded,
    BudgetTracker,
    Pricing,
    load_budget,
    load_pricing,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
START = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)


def pricing() -> Pricing:
    """The real price table shipped with the project."""
    return load_pricing(REPO_ROOT / "config" / "pricing.yaml")


def config() -> BudgetConfig:
    """The real budget shipped with the project."""
    return load_budget(REPO_ROOT / "config" / "budget.yaml")


def tracker(**overrides: object) -> BudgetTracker:
    """A tracker over the real configuration."""
    return BudgetTracker(
        config(),
        pricing(),
        started_at=START,
        **overrides,  # type: ignore[arg-type]
    )


# --- configuration ------------------------------------------------------------


def test_the_shipped_budget_matches_the_spec() -> None:
    budget = config()
    assert budget.per_job.max_tokens == 500_000
    assert budget.per_job.max_cost_usd == 5.00
    assert budget.per_job.max_wallclock_min == 30
    assert budget.on_exceed == "HALT_AND_REPORT"
    assert budget.extraction.asr_cache == "required"


def test_pricing_carries_all_four_rates_not_just_input_and_output() -> None:
    price = pricing().price_of("claude-opus-5")
    assert (price.input, price.output) == (5.00, 25.00)
    assert price.cache_read > 0
    assert price.cache_write > 0


def test_an_unpriced_model_is_an_error_not_a_guess() -> None:
    with pytest.raises(BudgetError, match="khong-co-model-nay"):
        pricing().cost_usd("khong-co-model-nay", tokens_in=10)


def test_pricing_goes_stale_after_ninety_days() -> None:
    table = pricing()
    assert not table.is_stale(table.last_verified + timedelta(days=89))
    assert table.is_stale(table.last_verified + timedelta(days=91))


def test_a_missing_config_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(BudgetError):
        load_budget(tmp_path / "khong-co.yaml")


# --- cost arithmetic ----------------------------------------------------------


def test_cost_is_computed_per_million_tokens() -> None:
    # 1M input at 2.00 plus 1M output at 10.00 on sonnet
    cost = pricing().cost_usd("claude-sonnet-5", tokens_in=1_000_000, tokens_out=1_000_000)
    assert cost == pytest.approx(12.00)


def test_output_tokens_cost_five_times_input_on_sonnet() -> None:
    table = pricing()
    only_in = table.cost_usd("claude-sonnet-5", tokens_in=100_000)
    only_out = table.cost_usd("claude-sonnet-5", tokens_out=100_000)
    assert only_out == pytest.approx(only_in * 5)


# --- ceilings -----------------------------------------------------------------


def test_a_normal_call_is_counted_without_complaint() -> None:
    guard = tracker()
    cost = guard.record_call("claude-sonnet-5", tokens_in=8_210, tokens_out=1_420)
    assert guard.tokens_total == 9_630
    assert cost > 0
    assert guard.cost_usd == pytest.approx(cost)


def test_one_oversized_call_is_refused_before_it_is_counted() -> None:
    guard = tracker()
    with pytest.raises(BudgetExceeded, match="moi lan goi"):
        guard.record_call("claude-sonnet-5", tokens_in=60_000)
    assert guard.tokens_total == 0


def test_the_job_token_ceiling_halts_the_run() -> None:
    guard = tracker()
    with pytest.raises(BudgetExceeded, match="tran token"):
        for _ in range(20):
            guard.record_call("claude-sonnet-5", tokens_in=40_000)


def test_the_money_ceiling_can_bite_before_the_token_ceiling() -> None:
    # This is why the two are counted apart: 250k output tokens on opus costs
    # $6.25 while only half the token budget is gone.
    guard = tracker()
    with pytest.raises(BudgetExceeded, match="chi phi"):
        for _ in range(10):
            guard.record_call("claude-opus-5", tokens_out=25_000)
    assert guard.tokens_total < config().per_job.max_tokens


def test_the_wallclock_ceiling_halts_the_run() -> None:
    guard = tracker()
    guard.check_wallclock(START + timedelta(minutes=29))
    with pytest.raises(BudgetExceeded, match="thoi gian"):
        guard.check_wallclock(START + timedelta(minutes=31))


def test_a_warning_is_raised_before_the_ceiling_is_reached() -> None:
    guard = tracker()
    for _ in range(11):
        guard.record_call("claude-sonnet-5", tokens_in=40_000)
    assert guard.tokens_total == 440_000
    assert any("tran token" in warning for warning in guard.warnings)


def test_the_snapshot_reports_what_was_spent() -> None:
    guard = tracker()
    guard.record_call("claude-sonnet-5", tokens_in=1_000, tokens_out=500)
    snapshot = guard.snapshot()
    assert snapshot["calls"] == 1.0
    assert snapshot["tokens_in"] == 1_000.0
    assert snapshot["tokens_out"] == 500.0
    assert snapshot["tokens_total"] == 1_500.0
    assert snapshot["cost_usd"] > 0
