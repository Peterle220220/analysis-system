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
    record,
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


# --- so chi phi: mot cau hoi, mot con so ---------------------------------------------


def test_the_ledger_is_written_where_the_docstring_always_said_it_was() -> None:
    """`snapshot` promised runs/<run_id>/budget.json and nobody ever wrote it.

    Harmless while every provider was free. Not harmless once real credit went
    in: spend was counted, printed once, and gone as soon as the terminal
    scrolled.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        run_dir = Path(folder) / "r1"
        written = record(run_dir, {"calls": 2.0, "cost_usd": 0.004}, now=START)
        assert written == run_dir / "budget.json"
        assert written.exists()


def test_a_second_invocation_adds_to_the_first_rather_than_replacing_it() -> None:
    """One question routinely takes two invocations.

    `ask` stops at a gate and `resume-dag` finishes it, and each builds a
    tracker from zero. Overwriting would report the second half as the whole
    cost - an error in the direction nobody notices, because the number comes
    out smaller than the truth.
    """
    import json
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        run_dir = Path(folder) / "r2"
        record(run_dir, {"calls": 2.0, "tokens_total": 8000.0, "cost_usd": 0.004}, now=START)
        written = record(
            run_dir, {"calls": 3.0, "tokens_total": 12000.0, "cost_usd": 0.006}, now=START
        )

        ledger = json.loads(written.read_text(encoding="utf-8"))
        assert len(ledger["lan_chay"]) == 2, "phai giu ca hai lan, khong ghi de"
        assert ledger["tong"]["calls"] == 5.0
        assert ledger["tong"]["tokens_total"] == 20000.0
        assert ledger["tong"]["cost_usd"] == 0.01


def test_every_entry_says_when_it_happened() -> None:
    """A ledger without times cannot answer which run cost what."""
    import json
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        written = record(Path(folder) / "r3", {"cost_usd": 0.002}, now=START)
        entry = json.loads(written.read_text(encoding="utf-8"))["lan_chay"][0]
        assert entry["luc"] == START.isoformat()


def test_an_unreadable_ledger_is_started_again_rather_than_raised() -> None:
    """Losing earlier entries is bad; refusing to run because of them is worse."""
    import json
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        run_dir = Path(folder) / "r4"
        run_dir.mkdir()
        (run_dir / "budget.json").write_text("khong phai JSON", encoding="utf-8")

        written = record(run_dir, {"cost_usd": 0.002}, now=START)
        ledger = json.loads(written.read_text(encoding="utf-8"))
        assert len(ledger["lan_chay"]) == 1
        assert ledger["tong"]["cost_usd"] == 0.002


def test_a_tracker_snapshot_goes_straight_into_the_ledger() -> None:
    """The two halves have to fit: whatever the tracker counts is what gets kept."""
    import json
    import tempfile

    counter = tracker()
    counter.record_call("gemini-3.7-flash", tokens_in=1000, tokens_out=200)
    with tempfile.TemporaryDirectory() as folder:
        written = record(Path(folder) / "r5", counter.snapshot(), now=START)
        kept = json.loads(written.read_text(encoding="utf-8"))["tong"]
        assert kept["calls"] == 1.0
        assert kept["tokens_in"] == 1000.0
        assert kept["tokens_out"] == 200.0
