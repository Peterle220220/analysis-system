"""A5 Validator: the referee. Code only, and it never touches the data.

Every other agent may be wrong in an interesting way. This one may only be
right or say nothing, which is why the spec forbids it a model outright: a
referee that reasons is a referee that can be argued with, and a PASS has to
mean the same thing every time it is printed.

Two properties hold and are tested:

* it never writes anywhere but validation://, so it cannot quietly repair the
  data it was asked to judge;
* the frame it was handed comes out byte for byte identical, so a check can
  never make itself pass.

A failure is useless without somewhere to look, so every one carries a count
and real offending rows.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar, Final

import pandas as pd

from analysis_system.agents.base import BaseAgent, ManifestDir, first_of
from analysis_system.core.hashing import canonical_hash
from analysis_system.core.scoped_storage import ScopedStorage
from analysis_system.core.settings import Settings
from analysis_system.domains.data_ingestion.validation import (
    ColumnRule,
    Failure,
    SchemaSpec,
    ValidationSpecError,
    check_comparisons,
    check_pattern,
    check_ranges,
    check_references,
    check_row_count_drift,
    check_schema,
    check_segregation_of_duties,
    check_sequence_order,
    check_time_window,
)
from analysis_system.domains.execution_engine.process_mining import EventLogSpec, ProcessMiningError
from analysis_system.models.agents import CheckFailure, ValidationOutcome
from analysis_system.models.base import ErrorDetail, TaskRequest, TaskResult

REPORT_PREFIX: Final[str] = "validation://"
SPEC_PARAM: Final[str] = "checks"


CONFORMANCE_KEYS: Final[tuple[str, ...]] = ("sequence_order", "segregation_of_duties")


def _event_log(spec: dict[str, Any]) -> EventLogSpec | None:
    """The role mapping the conformance rules share, if any were asked for.

    Declared once instead of on every rule: two rules disagreeing about which
    column is the case id is a mistake that looks like nothing at all.

    Raises:
        ValidationSpecError: conformance rules were asked for without saying
            which columns hold the case, the activity and the rest. Guessing
            that has already gone wrong once, silently, for a whole analysis.
    """
    wanted = [key for key in CONFORMANCE_KEYS if _rules(spec, key)]
    if not wanted:
        return None
    raw = spec.get("event_log")
    if not isinstance(raw, dict):
        raise ValidationSpecError(
            f"cac luat {wanted} can khoi 'event_log' khai case_id/activity"
            "/timestamp/resource. Khong doan cot."
        )
    try:
        return EventLogSpec.from_params(raw)
    except ProcessMiningError as error:
        raise ValidationSpecError(str(error)) from error


def _pair(rule: Any, first: str, second: str, label: str) -> tuple[str, str]:
    """Read one rule stated as two named activities."""
    if not isinstance(rule, dict) or first not in rule or second not in rule:
        raise ValidationSpecError(f"moi luat {label} phai co {first!r} va {second!r}.")
    return str(rule[first]), str(rule[second])


def _rules(spec: dict[str, Any], key: str) -> list[Any]:
    """Read one list of rules from the specification, tolerating its absence."""
    value = spec.get(key)
    return list(value) if isinstance(value, list) else []


def build_checks(frame: pd.DataFrame, spec: dict[str, Any]) -> list[Failure]:
    """Run every check the specification asks for.

    Args:
        frame: the table under test. It is never modified.
        spec: the checks to run, as handed over in the scope parameters.

    Returns:
        Every failure found, in a fixed order so two runs report the same thing.

    Raises:
        ValidationSpecError: a rule is malformed.
    """
    failures: list[Failure] = []

    not_null = [str(name) for name in _rules(spec, "not_null")]
    unique_together = tuple(
        tuple(str(name) for name in group) for group in _rules(spec, "unique_together")
    )
    if not_null or unique_together:
        schema = SchemaSpec(
            columns=tuple(ColumnRule(name=name, nullable=False) for name in not_null),
            unique_together=unique_together,
        )
        failures.extend(check_schema(frame, schema))

    ranges = [
        (str(rule["column"]), rule.get("min"), rule.get("max"))
        for rule in _rules(spec, "ranges")
        if isinstance(rule, dict) and "column" in rule
    ]
    if ranges:
        failures.extend(check_ranges(frame, ranges))

    comparisons = [
        (
            str(rule.get("name") or f"{rule['left']}_{rule['operator']}_{rule['right']}"),
            str(rule["left"]),
            str(rule["operator"]),
            str(rule["right"]),
        )
        for rule in _rules(spec, "comparisons")
        if isinstance(rule, dict) and {"left", "operator", "right"} <= set(rule)
    ]
    if comparisons:
        failures.extend(check_comparisons(frame, comparisons))

    log_spec = _event_log(spec)
    if log_spec is not None:
        failures.extend(
            check_sequence_order(
                frame,
                log_spec,
                [
                    _pair(rule, "before", "after", "sequence_order")
                    for rule in _rules(spec, "sequence_order")
                ],
            )
        )
        failures.extend(
            check_segregation_of_duties(
                frame,
                log_spec,
                [
                    _pair(rule, "first", "second", "segregation_of_duties")
                    for rule in _rules(spec, "segregation_of_duties")
                ],
            )
        )

    patterns = [
        (
            str(rule.get("name") or ""),
            str(rule["column"]),
            str(rule["pattern"]),
        )
        for rule in _rules(spec, "patterns")
        if isinstance(rule, dict) and {"column", "pattern"} <= set(rule)
    ]
    if patterns:
        failures.extend(check_pattern(frame, patterns))

    windows = [
        (
            str(rule.get("name") or ""),
            str(rule["column"]),
            None if rule.get("from") is None else str(rule["from"]),
            None if rule.get("to") is None else str(rule["to"]),
        )
        for rule in _rules(spec, "time_windows")
        if isinstance(rule, dict) and "column" in rule
    ]
    if windows:
        failures.extend(check_time_window(frame, windows))

    for rule in _rules(spec, "references"):
        if not isinstance(rule, dict) or "column" not in rule or "allowed" not in rule:
            raise ValidationSpecError("Moi rule tham chieu phai co 'column' va 'allowed'.")
        failures.extend(
            check_references(
                frame,
                str(rule["column"]),
                rule["allowed"],
                name=str(rule.get("name") or ""),
            )
        )

    return failures


def count_checks(spec: dict[str, Any]) -> int:
    """How many assertions the specification contains."""
    total = len(_rules(spec, "not_null")) + len(_rules(spec, "unique_together"))
    total += len(_rules(spec, "ranges")) + len(_rules(spec, "comparisons"))
    total += len(_rules(spec, "references"))
    # Counted like everything else. A5 refuses a specification that asserts
    # nothing, so a check the counter does not know about is a check that cannot
    # stop that refusal - and a run asserting only patterns would be told it had
    # asserted nothing at all.
    total += len(_rules(spec, "patterns")) + len(_rules(spec, "time_windows"))
    total += sum(len(_rules(spec, key)) for key in CONFORMANCE_KEYS)
    if spec.get("rows_in") is not None:
        total += 1
    return total


PLAN_PROBLEM_CODES: Final[frozenset[str]] = frozenset({"NO_INPUT", "NO_CHECKS"})


class ValidatorAgent(BaseAgent):
    """Judges a table against a stated contract, and changes nothing."""

    agent_id: ClassVar[str] = "a5_validator"

    def __init__(self, settings: Settings, manifest_dir: ManifestDir = None) -> None:
        """No model client: the referee is code, by specification."""
        super().__init__(settings, manifest_dir)

    def execute(self, request: TaskRequest, files: ScopedStorage) -> TaskResult:
        """Run the checks and write the verdict into the validation layer."""
        if not request.input_refs:
            return self._failed(request, "NO_INPUT", "A5 can mot input_ref tro toi bang can cham.")

        source = first_of(request.input_refs, "parquet")
        if source is None:
            return self._failed(request, "NO_INPUT", "A5 can mot bang de cham.")
        frame = files.load_parquet(source.path)
        before = canonical_hash(frame)

        spec = request.scope.params.get(SPEC_PARAM)
        if not isinstance(spec, dict):
            return self._failed(
                request,
                "NO_CHECKS",
                f"Thieu tham so {SPEC_PARAM!r}: khong biet phai cham theo tieu chi nao.",
            )

        try:
            failures = build_checks(frame, spec)
        except ValidationSpecError as error:
            return self._failed(request, "BAD_SPEC", str(error))

        rows_in = spec.get("rows_in")
        ceiling = spec.get("max_rows_dropped_pct")
        if isinstance(rows_in, int | float) and isinstance(ceiling, int | float):
            failures.extend(
                check_row_count_drift(int(rows_in), len(frame.index), max_drop_pct=float(ceiling))
            )

        total = count_checks(spec)
        outcome = ValidationOutcome(
            target=source.path,
            passed=max(total - len(failures), 0),
            failed=len(failures),
            failures=tuple(
                CheckFailure(
                    test=failure.test,
                    count=failure.count,
                    detail=failure.detail,
                    sample_rows=tuple(
                        json.dumps(row, ensure_ascii=False) for row in failure.sample_rows
                    ),
                )
                for failure in failures
            ),
        )

        report_uri = f"{REPORT_PREFIX}{request.scope.run_id}_{request.scope.task_id}.json"
        written = files.save_text(outcome.model_dump_json(indent=2), report_uri)

        # The data must come out exactly as it went in. A referee that could
        # edit the game is not a referee.
        if canonical_hash(frame) != before:
            return self._failed(
                request, "DATA_MUTATED", "A5 da lam thay doi du lieu duoc cham. Tuyet doi cam."
            )

        return TaskResult(
            task_id=request.scope.task_id,
            agent_id=self.agent_id,
            status="OK",
            output_refs=(written,),
            # A failed check is a verdict: the data broke a rule. An
            # unverifiable one is different in kind - the control could not be
            # carried out at all - and that is what belongs here.
            declined=tuple(
                [
                    failure.detail
                    for failure in outcome.failures
                    if failure.test.endswith(":unverifiable")
                ]
                # Zero checks is not a pass. With nothing declared this agent
                # ran nothing, found nothing and reported OK - so a run whose
                # data was never checked read exactly like one whose data was
                # checked and held. The whole point of a validator is to be the
                # difference between those two.
                + (
                    [
                        "KHONG CHAY PHEP KIEM NAO - khong ai khai 'checks' cho task nay. "
                        "Du lieu chua duoc kiem, khong phai da kiem va dat."
                    ]
                    if total == 0
                    else []
                )
            ),
            metrics={
                "checks_passed": float(outcome.passed),
                "checks_failed": float(outcome.failed),
                "rows": float(len(frame.index)),
            },
            payload=outcome.model_dump(mode="json"),
        )

    def _failed(self, request: TaskRequest, code: str, message: str) -> TaskResult:
        """Report an honest failure, with no verdict written."""
        return TaskResult(
            task_id=request.scope.task_id,
            agent_id=self.agent_id,
            status="FAILED",
            error=ErrorDetail(
                code=code,
                message=message,
                retryable=False,
                # Being handed the wrong input is the one failure a different
                # plan could actually fix.
                replannable=code in PLAN_PROBLEM_CODES,
            ),
        )
