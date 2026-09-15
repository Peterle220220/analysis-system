"""Human gates: the run writes down what needs approving, then stops.

The two-step design is the only one compatible with resume. A gate that blocked
on input() would hold a process open for as long as a person takes to decide,
and a run killed while waiting would lose everything.

Instead: the gate is written to a file, the run exits cleanly, and a separate
command records the decision into the state. The decision then lives in the
state as data, so re-running the same run id replays it rather than asking
again - which is what lets a run containing a gate still be reproducible.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from analysis_system.core import storage
from analysis_system.manager.state import GateDecision, RunState, options_fingerprint
from analysis_system.models.agents import ProposedRule
from analysis_system.services.extraction import LOW_CONFIDENCE
from analysis_system.services.rule_intent import mismatches, warning_for
from analysis_system.services.rule_names import example_of, labelled

GATE_DIR_NAME: Final[str] = "gates"


class GateError(RuntimeError):
    """A gate file is missing or malformed."""


class GateOption(BaseModel):
    """One thing a person can approve or reject."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    option_id: str
    label: str
    detail: str = ""
    # Index of the proposal entry this option stands for. Set whenever one rule
    # was proposed more than once, so approving one group approves that group
    # and not its siblings.
    rule_index: int | None = None


class GateRequest(BaseModel):
    """Everything a person needs in order to decide."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    gate_id: str
    run_id: str
    task_id: str
    agent_id: str
    title: str
    question: str
    options: tuple[GateOption, ...] = ()
    payload: dict[str, Any] = Field(default_factory=dict)
    # The output this question was built from. A skipped task refreshes nothing,
    # so without this the Manager cannot tell whether the question on disk still
    # describes the result it is meant to be about.
    result_hash: str = ""
    created_at: datetime

    def describes(self, output_hash: str) -> bool:
        """True when this question was built from that output.

        A gate with no recorded hash predates this field and counts as not
        describing anything: assuming otherwise would assume the very thing this
        is here to establish.
        """
        return bool(self.result_hash) and self.result_hash == output_hash

    @property
    def option_ids(self) -> tuple[str, ...]:
        """Every option id, in the order presented."""
        return tuple(option.option_id for option in self.options)


class GateStore:
    """Reads and writes runs/<run_id>/gates/."""

    def __init__(self, run_dir: Path) -> None:
        """Bind the store to one run directory."""
        self._dir = run_dir / GATE_DIR_NAME

    @property
    def directory(self) -> Path:
        """Where gate files live."""
        return self._dir

    def path_for(self, gate_id: str) -> Path:
        """Where one gate is written."""
        return self._dir / f"{gate_id}.json"

    def write(self, request: GateRequest) -> Path:
        """Record a gate for a person to answer."""
        self._dir.mkdir(parents=True, exist_ok=True)
        return storage.write_text(request.model_dump_json(indent=2), self.path_for(request.gate_id))

    def read(self, gate_id: str) -> GateRequest:
        """Read one gate back.

        Raises:
            GateError: the gate does not exist or does not validate.
        """
        path = self.path_for(gate_id)
        if not path.is_file():
            raise GateError(f"Khong tim thay gate {gate_id!r} tai {path}")
        try:
            return GateRequest.model_validate_json(storage.read_text(path))
        except ValidationError as error:
            raise GateError(f"Gate {path} khong hop le:\n{error}") from error

    def all_gates(self) -> list[GateRequest]:
        """Every gate written for this run, oldest first."""
        if not self._dir.is_dir():
            return []
        return sorted(
            (self.read(path.stem) for path in self._dir.glob("*.json")),
            key=lambda request: request.created_at,
        )

    def pending(self, state: RunState) -> list[GateRequest]:
        """Gates still owed an answer.

        Not simply "no decision recorded". A decision made about an earlier
        result does not answer the question this gate is asking now, and the
        Manager pauses on exactly that - so if this listed only undecided gates,
        a run could stop at a gate the listing insisted was not there.
        """
        return [request for request in self.all_gates() if not answered(state, request)]


def answered(state: RunState, request: GateRequest) -> bool:
    """True when a person has answered the question this gate is asking.

    The one place that rule lives. The Manager and the gate listing reading it
    differently is how an operator gets told to go and look at nothing.
    """
    decision = state.gates.get(request.gate_id)
    return decision is not None and decision.still_applies_to(request.option_ids)


def _scope_of(rule: dict[str, Any], resolved: list[str] | None) -> str:
    """Which columns this rule will really touch, in the words of the answer.

    A rule naming no columns applies to every one - a convention the code knows,
    the prompt states, and the gate used to leave unsaid. Approving
    `cast_numeric_safe` on a sales table emptied the date column and the channel
    column, and nothing on the screen had suggested it would.

    `applies_to` is filled in by the agent, which has the table. Where it is
    absent - an older payload, or a proposal that never reached a frame - the
    declared columns are shown, and silence still says "every column" rather
    than saying nothing.
    """
    declared = rule.get("columns")
    if resolved:
        names = ", ".join(str(column) for column in resolved)
        return names if declared else f"MOI COT: {names}"
    if declared:
        return ", ".join(str(column) for column in declared)
    return "MOI COT"


def rule_options(
    rules: list[dict[str, Any]], scope: list[list[str]] | None = None
) -> tuple[GateOption, ...]:
    """One option per proposed rule.

    A rule proposed once keeps its plain id, which reads better at the terminal.
    A rule proposed several times becomes one option per group, so each can be
    judged on its own - which is the reason the proposal split them in the first
    place. Casting to int64 and casting to float64 are two intentions, not one
    conflict to resolve.
    """
    occurrences: dict[str, int] = {}
    for rule in rules:
        rule_id = str(rule.get("rule_id"))
        occurrences[rule_id] = occurrences.get(rule_id, 0) + 1

    # A reason that describes a different rule in the book. The person reads
    # the reason and approves it; the system runs the rule_id. Where the two
    # disagree they have approved something they were never shown.
    sounds_like = mismatches(rules)

    seen: dict[str, int] = {}
    options: list[GateOption] = []
    for index, rule in enumerate(rules):
        rule_id = str(rule.get("rule_id"))
        resolved = scope[index] if scope and index < len(scope) else None
        columns = _scope_of(rule, resolved)
        if occurrences[rule_id] == 1:
            option_id, rule_index = rule_id, None
        else:
            seen[rule_id] = seen.get(rule_id, 0) + 1
            option_id, rule_index = f"{rule_id}#{seen[rule_id]}", index
        options.append(
            GateOption(
                option_id=option_id,
                # Ten tieng Viet, khong phai `cast_numeric_safe`. Nguoi dung
                # dang duoc hoi co cho SUA DU LIEU CUA HO khong; doc khong hieu
                # thi ho khong duyet, ho doan. Ten cot thi giu nguyen - do la
                # thu ho nhan ra trong tep cua chinh minh.
                label=labelled(rule_id, columns),
                # A rule the proposer would not justify is shown as one. The
                # prompt requires a reason and a real run produced five with
                # none - approving a change to your data because a model
                # suggested it and said nothing further is not approving.
                detail=_rule_detail(rule, sounds_like.get(index, ""), rule_id),
                rule_index=rule_index,
            )
        )
    return tuple(options)


def _rule_detail(rule: dict[str, Any], sounds_like: str, rule_id: str) -> str:
    """What a person reads before approving one rule.

    A rule the proposer would not justify is shown as one: the prompt requires a
    reason and a real run produced five with none. Approving a change to your
    data because a model suggested it and said nothing further is not approving.

    And where the reason describes a different rule, that is said first - before
    the reason itself, so it cannot be read past.
    """
    reason = str(rule.get("reason") or "").strip()
    example = example_of(rule_id)
    if not reason:
        body = "KHONG CO LY DO - de xuat nay khong noi vi sao can lam."
    elif sounds_like:
        body = f"{warning_for(rule_id, sounds_like)} Ly do: {reason}"
    else:
        body = reason
    # Canh bao "luat va ly do khong khop" phai dung DAU DONG, khong duoc doc
    # luot qua - nguoi doc no la nguoi sap duyet mot viec khac voi viec ho
    # tuong. Vi du thi day xuong sau no.
    ordered = (body, example) if sounds_like else (example, body)
    # Ma luat van hien: no la thu khop voi nhat ky chay, nguoi van hanh can no.
    return " · ".join(part for part in (*ordered, f"[{rule_id}]") if part)


def span_options(spans: list[dict[str, Any]]) -> tuple[GateOption, ...]:
    """One option per piece of text a reader was unsure about.

    Only the doubtful ones. A page read cleanly has nothing to ask about, and
    putting four hundred confident lines in front of a person is how they stop
    reading any of them - which would defeat the check entirely.

    Each carries where it came from, because confirming text without being able
    to go and look at the original is not confirming anything.
    """
    doubtful = [
        (index, span)
        for index, span in enumerate(spans, start=1)
        if float(span.get("confidence", 1.0)) < LOW_CONFIDENCE
    ]
    return tuple(
        GateOption(
            option_id=f"s{index}",
            label=str(span.get("text", "")),
            detail=(
                f"tin cay: {float(span.get('confidence', 0.0)):.0%}"
                f" - o: {_where(span.get('locator') or {})}"
            ),
        )
        for index, span in doubtful
    )


def _where(locator: dict[str, Any]) -> str:
    """Where to look in the original, in words a person can follow."""
    if locator.get("kind") == "time":
        return (
            f"{float(locator.get('start_s', 0.0)):.1f}s - {float(locator.get('end_s', 0.0)):.1f}s"
        )
    page = locator.get("page", 0)
    box = locator.get("bbox")
    if box:
        return f"trang {page}, vung {tuple(round(float(edge)) for edge in box)}"
    return f"trang {page}"


def claim_options(claims: list[dict[str, Any]]) -> tuple[GateOption, ...]:
    """One option per claim in the Manager's argument.

    Numbered by position, like findings, so a decision can be applied later
    without re-running the synthesis. The chart is named in the detail because
    approving a claim means approving the picture that will stand beside it.
    """
    return tuple(
        GateOption(
            option_id=f"c{index}",
            label=str(claim.get("claim", "")),
            detail=(
                f"dan: {', '.join(claim.get('metric_keys') or []) or '(khong)'}"
                + (f" - bieu do: {claim['chart_ref']}" if claim.get("chart_ref") else "")
            ),
        )
        for index, claim in enumerate(claims, start=1)
    )


def finding_options(findings: list[dict[str, Any]]) -> tuple[GateOption, ...]:
    """One option per finding, for HUMAN GATE 2.

    Findings have no natural id, so they are numbered in the order A7 produced
    them: f1, f2, f3. The number is the position, which is what lets a decision
    be applied to the findings later without re-running the analysis.
    """
    return tuple(
        GateOption(
            option_id=f"f{index}",
            label=str(finding.get("claim", "")),
            detail=(
                f"nguon: {finding.get('evidence_ref', '')} - "
                f"tin cay: {float(finding.get('confidence', 0.0)):.2f}"
            ),
        )
        for index, finding in enumerate(findings, start=1)
    )


def decide(
    request: GateRequest,
    *,
    approved: tuple[str, ...],
    rejected: tuple[str, ...] = (),
    added: tuple[dict[str, Any], ...] = (),
    note: str = "",
    now: datetime,
) -> GateDecision:
    """Build a decision, refusing anything the gate never offered.

    `added` is the exception, and a deliberate one. Approving and rejecting can
    only ever pick from what was proposed, which lets a person veto and not
    direct - and being able to say *what you want instead* is the difference
    between being consulted and being in charge.

    An added rule is still bounded: `ProposedRule` refuses any id outside the
    rulebook, so a person can ask for more cleaning but not for cleaning the
    system has no code to do.

    Raises:
        GateError: an id was approved or rejected that this gate never listed,
            or an added rule is not one the rulebook has.
    """
    offered = set(request.option_ids)
    unknown = sorted((set(approved) | set(rejected)) - offered)
    if unknown:
        raise GateError(
            f"Gate {request.gate_id!r} khong he de xuat: {unknown}. "
            f"Chi co the duyet trong: {sorted(offered)}"
        )
    overlap = sorted(set(approved) & set(rejected))
    if overlap:
        raise GateError(f"Vua duyet vua tu choi cung mot muc: {overlap}")
    for rule in added:
        try:
            ProposedRule.model_validate(rule)
        except ValidationError as error:
            raise GateError(f"Luat ban them khong hop le: {error}") from error

    return GateDecision(
        gate_id=request.gate_id,
        approved=tuple(approved),
        rejected=tuple(rejected),
        added=tuple(dict(rule) for rule in added),
        note=note,
        decided_on=options_fingerprint(request.option_ids),
        decided_at=now,
    )


def approved_rules_from(request: GateRequest, decision: GateDecision) -> list[dict[str, Any]]:
    """Select, from the proposal, exactly the entries a person approved.

    Selection goes by option, not by rule name. When one rule was proposed for
    three different column groups, approving one option takes that group alone -
    which is what the proposal asked for by splitting them in the first place.

    The proposal is carried in the gate payload rather than rebuilt, so what
    executes is byte for byte what was shown at the gate.
    """
    proposal = request.payload.get("proposal") or {}
    rules = proposal.get("rules") or []
    if not isinstance(rules, list):
        raise GateError(f"Gate {request.gate_id!r} co proposal khong hop le.")

    chosen = set(decision.approved)
    wanted_indexes: set[int] = set()
    wanted_names: set[str] = set()
    for option in request.options:
        if option.option_id not in chosen:
            continue
        if option.rule_index is None:
            wanted_names.add(option.option_id)
        else:
            wanted_indexes.add(option.rule_index)

    selected: list[dict[str, Any]] = []
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            continue
        if index in wanted_indexes or rule.get("rule_id") in wanted_names:
            selected.append(rule)
    # What the person asked for, after what they approved. A rule they added
    # was never proposed, so it is not in the payload to be selected from - it
    # comes from the decision itself, and it runs on the same footing as the
    # rest because they asked for it just as deliberately.
    selected.extend(dict(rule) for rule in decision.added)
    return selected


def render_gate(request: GateRequest) -> str:
    """Human-readable summary of one gate, for the terminal."""
    lines = [
        f"Gate: {request.gate_id}",
        f"  Run   : {request.run_id}   Task: {request.task_id}   Agent: {request.agent_id}",
        f"  {request.title}",
        f"  {request.question}",
        "",
    ]
    if not request.options:
        lines.append("  (khong co muc nao de duyet)")
    for option in request.options:
        lines.append(f"  - {option.option_id}: {option.label}")
        if option.detail:
            lines.append(f"      {option.detail}")
    summary = (request.payload.get("proposal") or {}).get("summary")
    if summary:
        lines.extend(["", f"  Tom tat cua agent: {summary}"])
    return "\n".join(lines)


def gate_payload(proposal: dict[str, Any]) -> dict[str, Any]:
    """Wrap a proposal for storage in a gate, dropping nothing."""
    return {"proposal": json.loads(json.dumps(proposal, ensure_ascii=False))}
