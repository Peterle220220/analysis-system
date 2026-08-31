"""A3 Cleaner: proposes cleaning rules, and executes only what a human approved.

The agent has two modes, and which one it is in depends entirely on whether the
Manager handed it approved rules:

* **No approved rules** - it proposes, writes nothing, and returns NEEDS_REVIEW.
  The proposal goes to a human gate.
* **Approved rules present** - it executes exactly those, and nothing else.

The model never executes anything. It emits a list of rule ids, each of which is
checked against the rulebook by the ProposedRule contract before it can travel
any further. An invented rule cannot survive that check, so it can never reach
the executor.

The row-drop ceiling is enforced *before* the output is written. A cleaning run
that would delete more than the manifest allows produces no file at all - there
is no half-cleaned artefact left behind for someone to pick up by mistake.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar, Final

import pandas as pd

from analysis_system.agents.base import BaseAgent, ManifestDir
from analysis_system.contracts.agents import (
    CleanResult,
    DiffSummary,
    ProfileReport,
    ProposedRule,
    RuleProposal,
)
from analysis_system.contracts.base import ErrorDetail, TaskRequest, TaskResult
from analysis_system.services.hashing import canonical_hash
from analysis_system.services.llm import LlmClient, LlmRequest
from analysis_system.services.pii import PiiMasker, build_llm_sample
from analysis_system.services.prompts import load_prompt
from analysis_system.services.rulebook import (
    RULE_ORDER,
    RULE_PARAMS,
    DiffEntry,
    RuleError,
    RuleSpec,
    apply_rules,
)
from analysis_system.services.scoped_storage import ScopedStorage
from analysis_system.settings import Settings

CLEAN_URI: Final[str] = "clean://events.parquet"
PROFILE_URI: Final[str] = "profile://profile.json"
APPROVED_RULES_PARAM: Final[str] = "approved_rules"
MAX_DIFF_EXAMPLES: Final[int] = 3


def summarise_diff(diff: tuple[DiffEntry, ...]) -> tuple[DiffSummary, ...]:
    """Group the diff log by reason, keeping a few examples of each.

    The full log can hold one entry per changed cell. What a human needs at the
    gate is how much of each kind of change happened, plus enough examples to
    recognise it.
    """
    grouped: dict[str, list[DiffEntry]] = {}
    for entry in diff:
        grouped.setdefault(entry.reason, []).append(entry)
    return tuple(
        DiffSummary(
            reason=reason,
            count=len(entries),
            examples=tuple(
                f"dong {entry.row_index}, cot {entry.column}: {entry.before!r} -> {entry.after!r}"
                for entry in entries[:MAX_DIFF_EXAMPLES]
            ),
        )
        for reason, entries in sorted(grouped.items())
    )


def to_rule_specs(approved: list[dict[str, Any]]) -> list[RuleSpec]:
    """Turn approved rules into an executable plan, one entry per approval.

    A rule approved for two column groups stays two entries: casting a sequence
    to an integer and a currency to a float are different intents, and merging
    them would force a choice nobody asked for. The rulebook runs them in
    RULE_ORDER, and entries of one rule in the order they arrived.

    Every entry is re-validated through ProposedRule, so a rule id outside the
    rulebook is rejected here even if something upstream let it through.

    Raises:
        ValueError: an entry names a rule outside the rulebook.
    """
    return [
        RuleSpec(rule.rule_id, rule.columns, rule.params)
        for rule in (ProposedRule.model_validate(entry) for entry in approved)
    ]


def build_proposal_request(frame: pd.DataFrame, profile: ProfileReport | None) -> LlmRequest:
    """Build the one question A3 is allowed to ask.

    The model sees the profile, the catalogue of rules it may choose from, and
    the usual capped, masked sample. It never sees the table.
    """
    pii_columns = list(profile.pii_flags) if profile else []
    # One masker for the whole payload, so the same value gets the same token
    # whether it appears in a sample row or in a statistic.
    masker = PiiMasker()

    def hide(value: str | None, column: str) -> str | None:
        """Mask a profile-derived value, with its column as context."""
        return None if value is None else masker.mask_text(value, column)

    payload = {
        # id -> the parameters that rule reads. Listing them stops the model
        # inventing options that would be refused.
        "rulebook": {rule_id: sorted(RULE_PARAMS[rule_id]) for rule_id in RULE_ORDER},
        "columns": [
            {
                "name": column.name,
                "dtype": column.dtype,
                "null_pct": column.null_pct,
                "distinct": column.distinct,
                "numeric_share": column.numeric_share,
                "min": hide(column.min_value, column.name),
                "max": hide(column.max_value, column.name),
                "top_values": [
                    {"value": hide(item.value, column.name), "count": item.count}
                    for item in column.top_values
                ],
                "outlier_count": column.outlier_count,
                "meaning": column.meaning,
                "is_pii": column.is_pii_candidate,
            }
            for column in (profile.columns if profile else ())
        ],
        "duplicate_rows": profile.duplicate_rows if profile else None,
        "duplicate_rows_pct": profile.duplicate_rows_pct if profile else None,
        "observations": list(profile.observations) if profile else [],
        "sample": build_llm_sample(frame, pii_columns=pii_columns, masker=masker),
    }
    return LlmRequest(
        purpose="a3_cleaner_propose",
        system=load_prompt("a3_cleaner_propose"),
        prompt=json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        schema=RuleProposal,
    )


class CleanerAgent(BaseAgent):
    """Proposes rules, then executes only the approved ones."""

    agent_id: ClassVar[str] = "a3_cleaner"

    def __init__(
        self,
        settings: Settings,
        manifest_dir: ManifestDir = None,
        *,
        llm: LlmClient | None = None,
    ) -> None:
        """Bind an optional model client on top of the usual agent setup."""
        super().__init__(settings, manifest_dir)
        self._llm = llm

    def execute(self, request: TaskRequest, files: ScopedStorage) -> TaskResult:
        """Propose or execute, depending on what the Manager approved."""
        if not request.input_refs:
            return self._failed(request, "NO_INPUT", "A3 can mot input_ref tro toi bang staging.")

        frame = files.load_parquet(request.input_refs[0].path)
        approved = request.scope.params.get(APPROVED_RULES_PARAM)

        # Absent means nobody has decided yet, so propose. Present but empty
        # means somebody decided nothing should run - a real answer, and one
        # that must be carried out. Treating the two the same would leave a run
        # proposing forever to a person who already said no.
        if approved is None:
            return self._propose(request, files, frame)
        if not isinstance(approved, list):
            return self._failed(
                request, "BAD_PARAMS", f"{APPROVED_RULES_PARAM} phai la mot danh sach."
            )
        return self._apply(request, files, frame, approved)

    # --- mode one: propose ----------------------------------------------------

    def _propose(
        self, request: TaskRequest, files: ScopedStorage, frame: pd.DataFrame
    ) -> TaskResult:
        """Suggest rules and stop. Nothing is written in this mode."""
        profile = self._read_profile(files)
        proposal = RuleProposal()
        if self._llm is not None:
            answer = self._llm.complete(build_proposal_request(frame, profile))
            if isinstance(answer.data, RuleProposal):
                proposal = answer.data

        return TaskResult(
            task_id=request.scope.task_id,
            agent_id=self.agent_id,
            status="NEEDS_REVIEW",
            metrics={
                "rows_in": float(len(frame.index)),
                "rules_proposed": float(len(proposal.rules)),
            },
            payload={
                "mode": "propose",
                "proposal": proposal.model_dump(mode="json"),
                "rule_ids": list(proposal.rule_ids),
            },
        )

    def _read_profile(self, files: ScopedStorage) -> ProfileReport | None:
        """Read the A2 report if it exists. A missing profile is not fatal."""
        try:
            raw = files.load_text(PROFILE_URI)
        except Exception:  # noqa: BLE001 - a missing profile only costs context
            return None
        return ProfileReport.model_validate_json(raw)

    # --- mode two: execute what was approved ----------------------------------

    def _apply(
        self,
        request: TaskRequest,
        files: ScopedStorage,
        frame: pd.DataFrame,
        approved: list[Any],
    ) -> TaskResult:
        """Run exactly the approved rules, refusing to drop too much."""
        # Both refusals are honest failures the Manager can act on, not crashes:
        # a rule outside the book, or a parameter no rule reads.
        try:
            plan = to_rule_specs(approved)
        except ValueError as error:
            return self._failed(request, "RULE_OUTSIDE_RULEBOOK", str(error))

        try:
            outcome = apply_rules(frame, plan)
        except RuleError as error:
            return self._failed(request, "RULE_REJECTED", str(error))
        ceiling = request.scope.limits.max_rows_dropped_pct
        if ceiling is not None and outcome.rows_dropped_pct > ceiling:
            # Checked before writing: a run that would delete too much leaves
            # nothing behind at all.
            return self._failed(
                request,
                "ROWS_DROPPED_EXCEEDED",
                f"Rule da duyet se bo {outcome.rows_dropped_pct:.2f}% so dong, "
                f"vuot tran {ceiling:.2f}%. Khong ghi file nao.",
                metrics={
                    "rows_in": float(outcome.rows_in),
                    "rows_out": float(outcome.rows_out),
                    "rows_dropped_pct": outcome.rows_dropped_pct,
                },
            )

        written = files.save_parquet(outcome.frame, CLEAN_URI)
        result = CleanResult(
            rows_in=outcome.rows_in,
            rows_out=outcome.rows_out,
            rules_applied=outcome.rules_applied,
            diff_log=summarise_diff(outcome.diff),
            content_hash=canonical_hash(outcome.frame),
        )
        return TaskResult(
            task_id=request.scope.task_id,
            agent_id=self.agent_id,
            status="OK",
            output_refs=(written,),
            metrics={
                "rows_in": float(result.rows_in),
                "rows_out": float(result.rows_out),
                "rows_dropped_pct": result.rows_dropped_pct,
            },
            payload=result.model_dump(mode="json"),
        )

    def _failed(
        self,
        request: TaskRequest,
        code: str,
        message: str,
        *,
        metrics: dict[str, float] | None = None,
    ) -> TaskResult:
        """Report an honest failure, with no output written."""
        return TaskResult(
            task_id=request.scope.task_id,
            agent_id=self.agent_id,
            status="FAILED",
            metrics=metrics or {},
            error=ErrorDetail(code=code, message=message, retryable=False),
        )
