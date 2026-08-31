"""Retry tests: the schedule is fixed, and waiting is something a test can watch."""

from __future__ import annotations

import pytest

from analysis_system.manager.retry import NO_WAIT, RetryError, RetryPolicy, wait


def test_each_failure_waits_longer_than_the_last() -> None:
    policy = RetryPolicy(base_delay_s=1.0, factor=2.0)
    assert policy.schedule(4) == (1.0, 2.0, 4.0, 8.0)


def test_the_wait_stops_growing_at_the_ceiling() -> None:
    policy = RetryPolicy(base_delay_s=1.0, factor=10.0, max_delay_s=5.0)
    assert policy.schedule(3) == (1.0, 5.0, 5.0)


def test_the_same_attempt_always_waits_the_same() -> None:
    # No jitter, on purpose: two runs of one plan must behave identically (S1).
    policy = RetryPolicy()
    assert [policy.delay_for(2) for _ in range(5)] == [policy.delay_for(2)] * 5


def test_asking_about_an_attempt_that_never_happened_is_an_error() -> None:
    with pytest.raises(RetryError, match="attempt phai >= 1"):
        RetryPolicy().delay_for(0)


def test_a_factor_below_one_is_not_a_backoff() -> None:
    with pytest.raises(RetryError, match="factor"):
        RetryPolicy(factor=0.5)


def test_a_ceiling_below_the_base_delay_is_refused() -> None:
    with pytest.raises(RetryError, match="max_delay_s"):
        RetryPolicy(base_delay_s=10.0, max_delay_s=1.0)


def test_a_negative_delay_is_refused() -> None:
    with pytest.raises(RetryError, match="base_delay_s"):
        RetryPolicy(base_delay_s=-1.0)


def test_waiting_sleeps_for_exactly_the_scheduled_time() -> None:
    slept: list[float] = []
    assert wait(RetryPolicy(base_delay_s=2.0), 2, slept.append) == 4.0
    assert slept == [4.0]


def test_a_zero_delay_does_not_sleep_at_all() -> None:
    # Tests use this policy: the schedule is what matters, not the seconds.
    slept: list[float] = []
    assert wait(NO_WAIT, 3, slept.append) == 0.0
    assert slept == []
