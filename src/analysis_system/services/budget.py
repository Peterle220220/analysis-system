"""Budget guard: counts tokens, money and wall clock, and halts on the ceiling.

The rule from the spec is absolute: on exceeding a ceiling the job halts and
reports. It never continues automatically, and it never quietly downgrades what
it was asked to do.

Tokens and money are counted separately because they run out at different
times. Five hundred thousand tokens of input costs a fraction of what the same
number of output tokens costs, so a single combined counter would let a job
blow through its dollar ceiling while its token counter still looked healthy.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Final

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

PRICE_UNIT: Final[int] = 1_000_000
STALE_PRICING_DAYS: Final[int] = 90
DEFAULT_WARN_RATIO: Final[float] = 0.8


class BudgetError(RuntimeError):
    """The budget or pricing configuration could not be loaded."""


class BudgetExceeded(RuntimeError):
    """A ceiling was reached. The job must halt and report."""


class ModelPrice(BaseModel):
    """Price of one model in USD per million tokens."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    input: float
    output: float
    cache_read: float = 0.0
    cache_write: float = 0.0


class Pricing(BaseModel):
    """The price table, with the date it was last checked against the vendor."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    last_verified: date
    models: dict[str, ModelPrice]

    def is_stale(self, today: date, max_age_days: int = STALE_PRICING_DAYS) -> bool:
        """True when the table is old enough that prices may have moved."""
        return (today - self.last_verified).days > max_age_days

    def price_of(self, model: str) -> ModelPrice:
        """Look up one model.

        Raises:
            BudgetError: the model is not in the table, so its cost is unknown.
        """
        if model not in self.models:
            known = ", ".join(sorted(self.models))
            raise BudgetError(
                f"Khong co gia cho model {model!r} trong pricing.yaml. Da khai bao: {known}"
            )
        return self.models[model]

    def cost_usd(
        self,
        model: str,
        *,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cache_read: int = 0,
        cache_write: int = 0,
    ) -> float:
        """Cost of one call in USD."""
        price = self.price_of(model)
        return (
            tokens_in * price.input
            + tokens_out * price.output
            + cache_read * price.cache_read
            + cache_write * price.cache_write
        ) / PRICE_UNIT


class JobBudget(BaseModel):
    """Ceilings for one whole job."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_tokens: int
    max_cost_usd: float
    max_wallclock_min: float


class AgentCallBudget(BaseModel):
    """Ceilings for a single agent call."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_tokens: int
    max_retries: int = 3


class ExtractionBudget(BaseModel):
    """Phase 5 ceilings, declared now so the config file has one shape."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_vision_calls: int = 0
    max_asr_minutes: int = 0
    asr_cache: str = "required"


class BudgetConfig(BaseModel):
    """The whole budget file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    per_job: JobBudget
    per_agent_call: AgentCallBudget
    extraction: ExtractionBudget = ExtractionBudget()
    on_exceed: str = "HALT_AND_REPORT"


def _load_yaml(path: Path) -> dict[str, object]:
    """Read a YAML mapping or fail with a clear message."""
    if not path.is_file():
        raise BudgetError(f"Khong tim thay file: {path}")
    try:
        parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise BudgetError(f"Khong doc duoc {path}: {error}") from error
    if not isinstance(parsed, dict):
        raise BudgetError(f"{path} phai la mot mapping YAML.")
    return parsed


def load_budget(path: Path) -> BudgetConfig:
    """Load config/budget.yaml.

    Raises:
        BudgetError: the file is missing or does not validate.
    """
    try:
        return BudgetConfig.model_validate(_load_yaml(path))
    except ValidationError as error:
        raise BudgetError(f"Budget {path} khong hop le:\n{error}") from error


def load_pricing(path: Path) -> Pricing:
    """Load config/pricing.yaml.

    Raises:
        BudgetError: the file is missing or does not validate.
    """
    try:
        return Pricing.model_validate(_load_yaml(path))
    except ValidationError as error:
        raise BudgetError(f"Pricing {path} khong hop le:\n{error}") from error


class BudgetTracker:
    """Running totals for one job, with a hard stop at every ceiling."""

    def __init__(
        self,
        config: BudgetConfig,
        pricing: Pricing,
        *,
        started_at: datetime,
        warn_ratio: float = DEFAULT_WARN_RATIO,
    ) -> None:
        """Start counting from zero."""
        self._config = config
        self._pricing = pricing
        self._started_at = started_at
        self._warn_ratio = warn_ratio
        self._tokens_in = 0
        self._tokens_out = 0
        self._cost_usd = 0.0
        self._calls = 0
        self._warnings: list[str] = []

    @property
    def tokens_total(self) -> int:
        """Every token counted so far, input and output together."""
        return self._tokens_in + self._tokens_out

    @property
    def cost_usd(self) -> float:
        """Money spent so far."""
        return self._cost_usd

    @property
    def warnings(self) -> tuple[str, ...]:
        """Warnings raised while approaching a ceiling."""
        return tuple(self._warnings)

    def record_call(
        self,
        model: str,
        *,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cache_read: int = 0,
        cache_write: int = 0,
    ) -> float:
        """Count one LLM call and stop the job if it crosses a ceiling.

        Returns:
            The cost of this single call in USD.

        Raises:
            BudgetExceeded: this call takes the job past its token ceiling, its
                money ceiling, or the per-call token ceiling.
        """
        call_tokens = tokens_in + tokens_out
        per_call_limit = self._config.per_agent_call.max_tokens
        if call_tokens > per_call_limit:
            raise BudgetExceeded(
                f"Mot lan goi dung {call_tokens} token, vuot tran moi lan goi {per_call_limit}."
            )

        cost = self._pricing.cost_usd(
            model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cache_read=cache_read,
            cache_write=cache_write,
        )
        new_tokens = self.tokens_total + call_tokens
        new_cost = self._cost_usd + cost

        if new_tokens > self._config.per_job.max_tokens:
            raise BudgetExceeded(
                f"Vuot tran token cua job: {new_tokens} > {self._config.per_job.max_tokens}."
            )
        if new_cost > self._config.per_job.max_cost_usd:
            raise BudgetExceeded(
                f"Vuot tran chi phi: ${new_cost:.4f} > ${self._config.per_job.max_cost_usd:.2f}."
            )

        self._tokens_in += tokens_in
        self._tokens_out += tokens_out
        self._cost_usd = new_cost
        self._calls += 1
        self._check_warnings()
        return cost

    def check_wallclock(self, now: datetime) -> None:
        """Stop the job when it has run too long.

        Raises:
            BudgetExceeded: the wall clock ceiling is behind us.
        """
        elapsed_min = (now - self._started_at).total_seconds() / 60.0
        if elapsed_min > self._config.per_job.max_wallclock_min:
            raise BudgetExceeded(
                f"Vuot tran thoi gian: {elapsed_min:.1f} phut > "
                f"{self._config.per_job.max_wallclock_min} phut."
            )

    def _check_warnings(self) -> None:
        """Record a warning once a ceiling is within reach."""
        token_ratio = self.tokens_total / self._config.per_job.max_tokens
        cost_ratio = self._cost_usd / self._config.per_job.max_cost_usd
        if token_ratio >= self._warn_ratio:
            self._add_warning(f"Da dung {token_ratio:.0%} tran token cua job.")
        if cost_ratio >= self._warn_ratio:
            self._add_warning(f"Da dung {cost_ratio:.0%} tran chi phi cua job.")

    def _add_warning(self, message: str) -> None:
        """Keep each distinct warning once."""
        if message not in self._warnings:
            self._warnings.append(message)

    def snapshot(self) -> dict[str, float]:
        """Current totals, for runs/<run_id>/budget.json."""
        return {
            "calls": float(self._calls),
            "tokens_in": float(self._tokens_in),
            "tokens_out": float(self._tokens_out),
            "tokens_total": float(self.tokens_total),
            "cost_usd": round(self._cost_usd, 6),
        }
