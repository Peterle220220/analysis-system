"""How long to wait before trying a failed task again.

Backoff exists because the failures worth retrying are the transient ones - a
timeout, a rate limit, a provider having a bad minute - and hammering them
immediately makes them worse.

**There is no jitter here, deliberately.** Jitter is the right answer when many
clients retry against one service at once, which is not this situation: a run is
one sequential loop. What jitter would cost is criterion S1 - two runs of the
same plan would no longer behave identically. Determinism is worth more than a
spread this system has no use for.

The waiting itself is injected, so a test can prove the schedule without
spending the seconds.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

Sleep = Callable[[float], None]

DEFAULT_BASE_DELAY_S: Final[float] = 0.5
DEFAULT_FACTOR: Final[float] = 2.0
DEFAULT_MAX_DELAY_S: Final[float] = 30.0


class RetryError(ValueError):
    """A retry policy was asked for something it cannot answer."""


@dataclass(frozen=True)
class RetryPolicy:
    """A deterministic exponential backoff schedule."""

    base_delay_s: float = DEFAULT_BASE_DELAY_S
    factor: float = DEFAULT_FACTOR
    max_delay_s: float = DEFAULT_MAX_DELAY_S

    def __post_init__(self) -> None:
        """Refuse a schedule that would never wait, or would wait forever."""
        if self.base_delay_s < 0:
            raise RetryError("base_delay_s khong the am.")
        if self.factor < 1:
            raise RetryError("factor phai >= 1, neu khong thi khong con la backoff.")
        if self.max_delay_s < self.base_delay_s:
            raise RetryError("max_delay_s khong the nho hon base_delay_s.")

    def delay_for(self, attempt: int) -> float:
        """Seconds to wait after `attempt` has just failed.

        Args:
            attempt: 1 for the first failure, 2 for the second, and so on.

        Raises:
            RetryError: attempt is below 1, which is not a failure that happened.
        """
        if attempt < 1:
            raise RetryError(f"attempt phai >= 1, nhan duoc {attempt}.")
        delay = self.base_delay_s * (self.factor ** (attempt - 1))
        return min(delay, self.max_delay_s)

    def schedule(self, attempts: int) -> tuple[float, ...]:
        """The whole waiting schedule, for reading and for testing."""
        return tuple(self.delay_for(attempt) for attempt in range(1, attempts + 1))


NO_WAIT: Final[RetryPolicy] = RetryPolicy(base_delay_s=0.0, max_delay_s=0.0)


def wait(policy: RetryPolicy, attempt: int, sleep: Sleep = time.sleep) -> float:
    """Wait out the backoff for one failed attempt.

    Returns:
        How long it waited, so the caller can record it.
    """
    delay = policy.delay_for(attempt)
    if delay > 0:
        sleep(delay)
    return delay
