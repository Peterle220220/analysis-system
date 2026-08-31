"""I/O contracts for individual agents.

These are the shapes an agent must return, and - just as importantly - the
shapes an LLM answer must fit before any of it is believed. A proposed rule that
names something outside the rulebook is rejected here, at the contract layer,
long before anything could execute it.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from analysis_system.contracts.base import EvidenceRef
from analysis_system.services.rulebook import RULE_ORDER

EVENT_LOG_ROLES = ("case_id", "activity", "timestamp", "resource")


class ValueCount(BaseModel):
    """How often one value occurs. Enough to spot a sentinel directly."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: str
    count: int


class ColumnProfile(BaseModel):
    """What code measured about one column. No opinions, only counts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    dtype: str
    non_null: int
    null_pct: float
    distinct: int
    avg_length: float = 0.0
    # A column staged as text can still hold numbers. This is the share that
    # parse as one, which is what separates a measure from a category code.
    numeric_share: float = 0.0
    min_value: str | None = None
    max_value: str | None = None
    top_values: tuple[ValueCount, ...] = ()
    outlier_count: int = 0
    is_pii_candidate: bool = False
    meaning: str = ""


class EventLogCandidates(BaseModel):
    """Which column plays which role in an event log, if any."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str | None = None
    activity: str | None = None
    timestamp: str | None = None
    resource: str | None = None

    @property
    def is_complete(self) -> bool:
        """True when all four roles are filled and process mining is possible."""
        return all(getattr(self, role) for role in EVENT_LOG_ROLES)


class ProfileInterpretation(BaseModel):
    """What the model is allowed to contribute to a profile.

    It may explain and it may point at columns. It may not produce a number:
    every count in the final report comes from code.
    """

    model_config = ConfigDict(extra="forbid")

    column_meanings: dict[str, str] = Field(default_factory=dict)
    pii_columns: list[str] = Field(default_factory=list)
    eventlog_candidates: EventLogCandidates = EventLogCandidates()
    observations: list[str] = Field(default_factory=list)


class ProfileReport(BaseModel):
    """The A2 deliverable."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    row_count: int
    column_count: int
    columns: tuple[ColumnProfile, ...]
    # De-duplication cannot be judged without this, and the previous profile
    # simply did not say.
    duplicate_rows: int = 0
    duplicate_rows_pct: float = 0.0
    pii_flags: tuple[str, ...] = ()
    eventlog_candidates: EventLogCandidates = EventLogCandidates()
    observations: tuple[str, ...] = ()


class CheckFailure(BaseModel):
    """One failed check, with somewhere to look."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    test: str
    count: int
    detail: str
    sample_rows: tuple[str, ...] = ()


class ValidationOutcome(BaseModel):
    """The A5 verdict on one table."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    target: str
    passed: int
    failed: int
    failures: tuple[CheckFailure, ...] = ()

    @property
    def is_ok(self) -> bool:
        """True when nothing failed."""
        return self.failed == 0


class ProposedRule(BaseModel):
    """One cleaning rule the model suggests.

    The rule id is checked against the rulebook here. An agent can therefore
    never be handed an invented rule to run, which is what the a3_cleaner
    manifest means by denying custom_rule_outside_rulebook.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: str
    columns: tuple[str, ...] = ()
    params: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""

    @field_validator("rule_id")
    @classmethod
    def _must_be_in_the_rulebook(cls, value: str) -> str:
        if value not in RULE_ORDER:
            allowed = ", ".join(RULE_ORDER)
            raise ValueError(f"Rule {value!r} khong co trong rulebook. Chi cho phep: {allowed}")
        return value


class RuleProposal(BaseModel):
    """What A3 asks a human to approve."""

    model_config = ConfigDict(extra="forbid")

    rules: list[ProposedRule] = Field(default_factory=list)
    summary: str = ""

    @property
    def rule_ids(self) -> tuple[str, ...]:
        """Just the ids, in the order proposed."""
        return tuple(rule.rule_id for rule in self.rules)


class ColumnLineage(BaseModel):
    """Where one output column came from.

    Declared by the model and verified by code: a lineage nobody checks is
    decoration, and deriving it by parsing SQL would be a second parser to get
    wrong.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    output: str
    sources: tuple[str, ...] = ()
    transform: str = ""


class SqlProposal(BaseModel):
    """A statement the model suggests, with its lineage."""

    model_config = ConfigDict(extra="forbid")

    sql: str
    target_table: str
    lineage: list[ColumnLineage] = Field(default_factory=list)
    reason: str = ""


class TransformResult(BaseModel):
    """The A4 deliverable."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    target: str
    sql: str
    rows_in: dict[str, int]
    rows_out: int
    lineage: tuple[ColumnLineage, ...] = ()
    content_hash: str = ""
    warnings: tuple[str, ...] = ()


class MetricValue(BaseModel):
    """One number, computed by code. The only figures an analysis may quote."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    value: float
    unit: str = ""
    source: str = ""


class Finding(BaseModel):
    """One conclusion, as the model proposes it.

    The claim carries placeholders where numbers go, never numbers. A claim with
    a digit typed into it is refused: that is the whole anti-hallucination
    mechanism, and it works by shape rather than by inspection.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_template: str
    metric_keys: tuple[str, ...] = ()
    evidence_ref: str = ""
    confidence: float = 0.0
    dimension: str = ""


class FindingProposal(BaseModel):
    """What the model returns."""

    model_config = ConfigDict(extra="forbid")

    findings: list[Finding] = Field(default_factory=list)
    summary: str = ""


class RenderedFinding(BaseModel):
    """One conclusion after code substituted the real figures."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim: str
    template: str
    metrics: dict[str, float] = Field(default_factory=dict)
    evidence_ref: str = ""
    confidence: float = 0.0
    dimension: str = ""

    def as_evidence(self) -> EvidenceRef:
        """The trace back to the data this conclusion rests on."""
        return EvidenceRef(
            source=self.evidence_ref,
            locator=",".join(sorted(self.metrics)),
            value=self.claim[:200],
        )


class AnalysisResult(BaseModel):
    """The A7 deliverable."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str
    question: str
    findings: tuple[RenderedFinding, ...] = ()
    metrics_available: int = 0
    rejected: tuple[str, ...] = ()


class NarrativeProposal(BaseModel):
    """Executive summary as the model proposes it, numbers as placeholders."""

    model_config = ConfigDict(extra="forbid")

    summary_template: str = ""
    audience: str = ""


class ReportResult(BaseModel):
    """The A8 deliverable."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str
    markdown: str
    html: str
    charts: tuple[str, ...] = ()
    findings: int = 0
    metrics: int = 0


class PlannedTask(BaseModel):
    """One agent call in a plan."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: str
    agent_id: str
    depends_on: tuple[str, ...] = ()
    # Which upstream tasks' outputs this one actually reads. Empty means "the
    # ones it depends on", which is the usual case. It is set where order and
    # data flow part company: A7 must run after validation, but what it reads is
    # the mart table A4 built, not the validation report A5 wrote.
    inputs_from: tuple[str, ...] = ()
    instruction: str = ""
    params: dict[str, Any] = Field(default_factory=dict)

    @property
    def reads_from(self) -> tuple[str, ...]:
        """The tasks whose outputs feed this one."""
        return self.inputs_from or self.depends_on


class Plan(BaseModel):
    """A DAG of agent calls.

    Produced by the planner, checked before anything runs. A plan is a proposal
    like any other model output: nothing in it executes until code has agreed
    the graph is sound.
    """

    model_config = ConfigDict(extra="forbid")

    tasks: tuple[PlannedTask, ...] = ()
    reason: str = ""

    @property
    def task_ids(self) -> tuple[str, ...]:
        """Every task id, in the order given."""
        return tuple(task.task_id for task in self.tasks)


class DiffSummary(BaseModel):
    """How many changes of each kind a cleaning run made."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reason: str
    count: int
    examples: tuple[str, ...] = ()


class CleanResult(BaseModel):
    """The A3 deliverable."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rows_in: int
    rows_out: int
    rules_applied: tuple[str, ...]
    diff_log: tuple[DiffSummary, ...]
    content_hash: str

    @property
    def rows_dropped_pct(self) -> float:
        """Percentage of rows removed."""
        if self.rows_in == 0:
            return 0.0
        return 100.0 * (self.rows_in - self.rows_out) / self.rows_in
