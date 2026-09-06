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

from analysis_system.agents.base import BaseAgent, ManifestDir, first_of
from analysis_system.contracts.agents import (
    CleanResult,
    DiffSummary,
    ProfileReport,
    ProposedRule,
    RuleProposal,
)
from analysis_system.contracts.base import DataRef, ErrorDetail, TaskRequest, TaskResult
from analysis_system.services.diagnosis import EVERY_COLUMN, examine
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
TARGET_PARAM: Final[str] = "target"


def clean_uri_for(source_uri: str, run_id: str) -> str:
    """Where a cleaned table goes: named after the data, not the run.

    The old name was clean://events.parquet - a leftover from the event log this
    was built around, which left every later dataset both mislabelled and liable
    to overwrite the one before it.

    The run id is deliberately *not* in the name. A4 derives its SQL table name
    from this filename, so putting the run in it would change the table name on
    every run and break any statement written against it. What the table is
    called should describe the data; which run produced it is recorded in the
    state and in the content hash a citation carries.
    """
    stem = source_uri.rsplit("/", 1)[-1].rsplit(".", 1)[0] or "table"
    prefix = f"{run_id}_"
    if stem.startswith(prefix):
        # A1 stages as <run_id>_<name>; the cleaned table keeps only the name.
        stem = stem[len(prefix) :] or "table"
    return f"clean://{stem}.parquet"


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


PLAN_PROBLEM_CODES: Final[frozenset[str]] = frozenset({"NO_INPUT"})


def from_profile(profile: ProfileReport | None) -> list[ProposedRule]:
    """Rules the measurements themselves call for, whatever the model noticed.

    A2 counts duplicate rows and measures how numeric each column is. Both are
    arithmetic, and rule four of this project says arithmetic is not a model's
    job - yet the proposal depended entirely on whether the model happened to
    act on what it read. On one real run it did not, and two duplicate rows
    survived cleaning with nobody able to say so: `decide()` refuses to approve
    anything the gate never offered.

    Seeded rules go to the same gate and need the same approval. What changes is
    who may propose, not who decides.

    Only what needs no judgement. Duplicate rows are duplicate rows.

    Casting a numeric-looking column is **not** in that category, and the golden
    test caught the attempt: BPI19 holds `case_item = "00001"`, an identifier
    over ninety percent numeric, and casting it would have produced `1` and lost
    the leading zeros while still looking fine. Whether such a column is a
    measure or an identifier is a judgement - `statistics._is_counter` exists
    because of exactly that - so it stays with the model to propose and a person
    to approve.

    Mixed capitalisation is the same story: a real problem, no rule that surely
    fixes it, nothing seeded. Filling a gate with rules nobody can judge is how
    a gate becomes a rubber stamp.
    """
    if profile is None:
        return []

    seeded: list[ProposedRule] = []
    if profile.duplicate_rows > 0:
        seeded.append(
            ProposedRule(
                rule_id="drop_exact_duplicates",
                reason=(
                    f"[đo từ hồ sơ] có {profile.duplicate_rows} dòng trùng lặp hoàn toàn "
                    f"({profile.duplicate_rows_pct:.2f}% số dòng)."
                ),
            )
        )

    return seeded


def without_duplicates(proposal: RuleProposal) -> tuple[RuleProposal, list[str]]:
    """Collapse rules that are the same rule, and say how many went.

    Three identical `trim_whitespace` over every column arrived from a real run.
    They are one decision, not three: approving the first and refusing the third
    would mean nothing, and a list that asks the same question repeatedly teaches
    people to stop reading it.

    Same rule means same id, same columns, same parameters. A rule repeated for
    *different* columns is a different intention and is kept - that is what the
    prompt asks proposers to do.
    """
    seen: set[tuple[str, tuple[str, ...], str]] = set()
    kept: list[ProposedRule] = []
    notes: list[str] = []
    for rule in proposal.rules:
        key = (rule.rule_id, tuple(rule.columns), json.dumps(rule.params, sort_keys=True))
        if key in seen:
            notes.append(
                f"Bỏ một bản trùng của cách làm sạch {rule.rule_id!r} (cùng cột, cùng tham số)."
            )
            continue
        seen.add(key)
        kept.append(rule)
    return proposal.model_copy(update={"rules": kept}), notes


def without_unrunnable(proposal: RuleProposal) -> tuple[RuleProposal, list[str]]:
    """Drop rules that cannot run, and say which and why.

    A real run offered `replace_sentinel_with_null` with no `sentinels` list.
    The rule requires one and refuses to guess - rightly, since guessing which
    strings mean "missing" is how a legitimate value called "-" disappears. So
    the option was approved in good faith and the run died on it, after the
    approval, with nothing for the person to do about it.

    A gate must only offer what approving would actually do. Dropped out loud
    rather than in silence: a rule that vanishes without a word looks like a
    proposer that never proposed it.

    The examination seeds the same rule with the sentinels it actually counted,
    so a column that really needs this still gets asked about - with values from
    the data instead of a guess.
    """
    kept: list[ProposedRule] = []
    notes: list[str] = []
    for rule in proposal.rules:
        missing = sorted(RULE_PARAMS.get(rule.rule_id, frozenset()) - set(rule.params))
        if missing:
            notes.append(
                f"Bỏ cách làm sạch {rule.rule_id!r} vì thiếu tham số bắt buộc: "
                f"{', '.join(missing)} — duyệt nó thì lần chạy sẽ dừng giữa chừng."
            )
            continue
        kept.append(rule)
    return proposal.model_copy(update={"rules": kept}), notes


def rule_scope(proposal: RuleProposal, frame: pd.DataFrame) -> list[list[str]]:
    """The proposal, with each rule's real scope resolved against the table.

    A rule naming no columns applies to every one. That convention is stated in
    the prompt and known to the rulebook, and until now the gate never mentioned
    it - so approving `cast_numeric_safe` on a sales table emptied the date
    column and the channel column, and nothing on the screen had said it would.

    The agent is the right place to resolve it because the agent has the table.
    Resolving in the gate would mean handing the frame to a component whose whole
    job is asking questions, and resolving in the rulebook would be too late:
    by then the answer has already been given.
    """
    columns = [str(column) for column in frame.columns]
    # Named columns are listed as they were named, including any that do not
    # exist: the rulebook refuses those by name later, and hiding them here
    # would turn a clear refusal into a silent surprise.
    return [list(rule.columns) if rule.columns else columns for rule in proposal.rules]


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

        source = first_of(request.input_refs, "parquet")
        if source is None:
            return self._failed(request, "NO_INPUT", "A3 can mot bang de lam sach.")
        frame = files.load_parquet(source.path)
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
        return self._apply(request, files, frame, approved, source)

    # --- mode one: propose ----------------------------------------------------

    def _propose(
        self, request: TaskRequest, files: ScopedStorage, frame: pd.DataFrame
    ) -> TaskResult:
        """Suggest rules and stop. Nothing is written in this mode."""
        profile = self._read_profile(files, request.scope.run_id)
        proposal = RuleProposal()
        notes: list[str] = []
        if self._llm is not None:
            answer = self._llm.complete(build_proposal_request(frame, profile))
            if isinstance(answer.data, RuleProposal):
                # Three identical rules arrived from a real run. They are one
                # decision, not three, and a list that asks the same question
                # repeatedly teaches people to stop reading it.
                proposal, duplicates = without_duplicates(answer.data)
                notes.extend(duplicates)
                proposal, incomplete = without_unrunnable(proposal)
                notes.extend(incomplete)

        # What the profile measured, whatever the model noticed. Added after the
        # model's own rules and de-duplicated against them, so a problem the
        # model did spot is not asked about twice.
        seeded = from_profile(profile)
        if seeded:
            proposal, _ = without_duplicates(
                proposal.model_copy(update={"rules": [*proposal.rules, *seeded]})
            )

        # Whether anything needs cleaning at all, counted rather than judged.
        # Said out loud either way: "nothing found" and "nothing looked for"
        # produce the same empty list of rules, and a person reading that list
        # cannot tell which one they are being shown.
        diagnosis = examine(frame)

        # What the examination counted becomes something a person can approve,
        # not merely something they can read. A real run on 1,000 rows found
        # five columns needing work and offered nothing to agree to: the gate
        # said what was wrong and then asked a question with no answers in it.
        # Being shown a problem you cannot consent to fixing is not being
        # consulted.
        #
        # Proposing is all this does. Every seeded rule goes to the same gate
        # and needs the same approval; what changes is who may propose, not who
        # decides. And rule four of this project says a count is not a model's
        # job - `examine` already did the counting, with its own guards against
        # the casts that would destroy an identifier.
        found_rules = [
            ProposedRule(
                rule_id=found.rule_id,
                columns=() if found.column == EVERY_COLUMN else (found.column,),
                reason=f"[đo từ dữ liệu] {found.as_reason()}",
                params=dict(found.params),
            )
            for found in diagnosis.findings
            if RULE_PARAMS.get(found.rule_id, frozenset()) <= set(found.params)
        ]
        if found_rules:
            proposal, _ = without_duplicates(
                proposal.model_copy(update={"rules": [*proposal.rules, *found_rules]})
            )

        notes.insert(0, diagnosis.verdict)
        notes.extend(
            f"Cần sửa: {found.rule_id} trên {found.column} — {found.as_reason()}"
            for found in diagnosis.findings
        )

        return TaskResult(
            task_id=request.scope.task_id,
            agent_id=self.agent_id,
            status="NEEDS_REVIEW",
            # What was tidied away before the question was asked. A duplicate
            # removed in silence looks like a model that never proposed it.
            declined=tuple(notes),
            metrics={
                "rows_in": float(len(frame.index)),
                "rules_proposed": float(len(proposal.rules)),
                # How many places code counted as needing work. Zero with rules
                # proposed means the model saw something the counting did not,
                # which is worth a second look rather than a silent pass.
                "cho_can_sua": float(len(diagnosis.findings)),
                # Rules the proposer would not justify. The prompt requires a
                # reason and a real run produced five with none, so this is
                # worth a number rather than only a line at the gate.
                "rules_without_reason": float(
                    sum(1 for rule in proposal.rules if not rule.reason.strip())
                ),
            },
            payload={
                "mode": "propose",
                "proposal": proposal.model_dump(mode="json"),
                # Beside the proposal, never inside it. Inside, the model would
                # see the field and could write it - and a scope the proposer
                # states is not a check on the proposer.
                "rule_scope": rule_scope(proposal, frame),
                "rule_ids": list(proposal.rule_ids),
            },
        )

    def _read_profile(self, files: ScopedStorage, run_id: str) -> ProfileReport | None:
        """Read this run's A2 report if it exists. A missing profile is not fatal.

        The run's own profile first, then the old shared name, so a run started
        before profiles were named after their run still finds one.
        """
        for uri in (f"profile://{run_id}_profile.json", PROFILE_URI):
            try:
                return ProfileReport.model_validate_json(files.load_text(uri))
            except Exception:  # noqa: BLE001 - a missing profile only costs context
                continue
        return None

    def _apply(  # noqa: PLR0913 - the source travels with the frame it came from
        self,
        request: TaskRequest,
        files: ScopedStorage,
        frame: pd.DataFrame,
        approved: list[Any],
        source: DataRef,
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

        target = str(request.scope.params.get(TARGET_PARAM) or "") or clean_uri_for(
            source.path, request.scope.run_id
        )
        written = files.save_parquet(outcome.frame, target)
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
            error=ErrorDetail(
                code=code,
                message=message,
                retryable=False,
                # Being handed the wrong input is the one failure a different
                # plan could actually fix.
                replannable=code in PLAN_PROBLEM_CODES,
            ),
        )
