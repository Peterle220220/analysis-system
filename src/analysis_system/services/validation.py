"""The validator: the objective referee of the pipeline.

This module is 100% code and must stay that way. It decides PASS or FAIL at
every checkpoint, so an LLM is never allowed anywhere near it, and it must never
alter data to make a check succeed.

Schema checks run through pandera; the drift check between two layers is a plain
comparison. Every failure carries a count and real example rows, because a
failure nobody can locate in the data is not actionable.
"""

from __future__ import annotations

import operator
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

import pandas as pd
import pandera.pandas as pa
from pandera.errors import SchemaErrors

from analysis_system.services.process_mining import EventLogSpec, order_events

MAX_SAMPLE_ROWS: Final[int] = 5


class ValidationSpecError(RuntimeError):
    """The validation specification itself is malformed.

    Distinct from a failed check: this means the rules could not be understood,
    not that the data broke them.
    """


@dataclass(frozen=True)
class ColumnRule:
    """What a single column must satisfy."""

    name: str
    nullable: bool = True
    dtype: str | None = None
    unique: bool = False

    def check_count(self) -> int:
        """Number of distinct assertions this rule contributes."""
        return (
            1 + (0 if self.nullable else 1) + (1 if self.dtype else 0) + (1 if self.unique else 0)
        )


@dataclass(frozen=True)
class SchemaSpec:
    """The full contract a frame must satisfy at a checkpoint."""

    columns: tuple[ColumnRule, ...]
    unique_together: tuple[tuple[str, ...], ...] = ()

    def check_count(self) -> int:
        """Total number of assertions in this specification."""
        return sum(rule.check_count() for rule in self.columns) + len(self.unique_together)


@dataclass(frozen=True)
class Failure:
    """One failed check, with enough detail to find it in the data."""

    test: str
    count: int
    detail: str
    sample_rows: tuple[dict[str, str], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ValidationReport:
    """The verdict at one checkpoint."""

    passed: int
    failed: int
    failures: tuple[Failure, ...]

    @property
    def is_ok(self) -> bool:
        """True when nothing failed."""
        return self.failed == 0


def build_schema(spec: SchemaSpec) -> pa.DataFrameSchema:
    """Turn a specification into a pandera schema.

    Returns:
        A schema that reports every violation rather than stopping at the first.
    """
    columns = {
        rule.name: pa.Column(
            dtype=rule.dtype,
            nullable=rule.nullable,
            unique=rule.unique,
            required=True,
            coerce=False,
        )
        for rule in spec.columns
    }
    unique = [list(group) for group in spec.unique_together]
    return pa.DataFrameSchema(
        columns=columns,
        unique=unique or None,
        strict=False,
        ordered=False,
    )


def _sample_rows(frame: pd.DataFrame, indices: list[Any]) -> tuple[dict[str, str], ...]:
    """Pull up to MAX_SAMPLE_ROWS offending rows out of the frame as text."""
    usable = [index for index in indices if index in frame.index][:MAX_SAMPLE_ROWS]
    samples: list[dict[str, str]] = []
    for index in usable:
        row = frame.loc[index]
        samples.append({str(key): str(value) for key, value in row.items()})
    return tuple(samples)


def check_schema(frame: pd.DataFrame, spec: SchemaSpec) -> list[Failure]:
    """Run the schema contract and translate pandera errors into failures."""
    schema = build_schema(spec)
    try:
        schema.validate(frame, lazy=True)
    except SchemaErrors as errors:
        return _failures_from(errors, frame)
    return []


def _failures_from(errors: SchemaErrors, frame: pd.DataFrame) -> list[Failure]:
    """Group pandera failure cases into one Failure per (column, check)."""
    cases = errors.failure_cases
    if cases.empty:
        return []
    failures: list[Failure] = []
    grouping = cases.groupby(["column", "check"], dropna=False, sort=True)
    for (column, check), group in grouping:
        indices = group["index"].dropna().tolist() if "index" in group else []
        examples = ", ".join(str(value) for value in group["failure_case"].head(3))
        failures.append(
            Failure(
                test=f"{column}:{check}",
                count=len(group),
                detail=f"Vi pham {check!r} tren cot {column!r}. Vi du: {examples}",
                sample_rows=_sample_rows(frame, indices),
            )
        )
    return failures


def check_row_count_drift(rows_in: int, rows_out: int, *, max_drop_pct: float) -> list[Failure]:
    """Compare row counts between two layers.

    Args:
        rows_in: rows entering the step.
        rows_out: rows leaving it.
        max_drop_pct: the largest acceptable loss, as a percentage.

    Returns:
        A single failure when too many rows disappeared, otherwise nothing.
    """
    if rows_in <= 0:
        return []
    dropped_pct = 100.0 * (rows_in - rows_out) / rows_in
    if dropped_pct <= max_drop_pct:
        return []
    return [
        Failure(
            test="row_count_drift",
            count=rows_in - rows_out,
            detail=(
                f"Mat {dropped_pct:.2f}% so dong ({rows_in} -> {rows_out}), "
                f"vuot nguong {max_drop_pct:.2f}%."
            ),
        )
    ]


def run_checks(
    frame: pd.DataFrame,
    spec: SchemaSpec,
    *,
    rows_in: int | None = None,
    max_drop_pct: float | None = None,
) -> ValidationReport:
    """Run every check for a checkpoint and return the verdict.

    Args:
        frame: the frame under test.
        spec: the schema contract.
        rows_in: row count of the previous layer, when drift should be checked.
        max_drop_pct: the drift threshold that goes with rows_in.

    Returns:
        The report. It never modifies the frame.
    """
    failures = check_schema(frame, spec)
    total_checks = spec.check_count()

    if rows_in is not None and max_drop_pct is not None:
        total_checks += 1
        failures.extend(check_row_count_drift(rows_in, len(frame.index), max_drop_pct=max_drop_pct))

    return ValidationReport(
        passed=max(total_checks - len(failures), 0),
        failed=len(failures),
        failures=tuple(failures),
    )


# --- comparison operators the business rules may use --------------------------

COMPARISONS: Final[dict[str, Callable[[Any, Any], Any]]] = {
    ">=": operator.ge,
    ">": operator.gt,
    "<=": operator.le,
    "<": operator.lt,
    "==": operator.eq,
    "!=": operator.ne,
}


def _comparable(series: pd.Series[Any]) -> pd.Series[Any]:
    """Coerce a column into something two columns can be compared with.

    Staged data is text, so a date sits in the frame as a string and comparing
    two of them lexically happens to work for ISO dates and silently does not
    for anything else. Numbers and timestamps are converted properly; whatever
    resists both is left as text and compared as text.
    """
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().sum() == series.notna().sum() and series.notna().any():
        return numeric
    try:
        parsed = pd.to_datetime(series, errors="coerce", format="mixed")
    except (ValueError, TypeError):
        return series.astype("string")
    if parsed.notna().sum() == series.notna().sum() and series.notna().any():
        return parsed
    return series.astype("string")


def check_ranges(
    frame: pd.DataFrame, rules: Sequence[tuple[str, float | None, float | None]]
) -> list[Failure]:
    """Check that numeric columns stay inside their stated bounds.

    Args:
        frame: the frame under test.
        rules: (column, minimum, maximum) triples. Either bound may be None.

    Returns:
        One failure per column that has values outside its bounds.
    """
    failures: list[Failure] = []
    for column, minimum, maximum in rules:
        if column not in frame.columns:
            failures.append(
                Failure(
                    test=f"{column}:range",
                    count=0,
                    detail=f"Khong co cot {column!r} de kiem khoang gia tri.",
                )
            )
            continue
        values = pd.to_numeric(frame[column], errors="coerce")
        outside = pd.Series(False, index=frame.index)
        if minimum is not None:
            outside = outside | (values < minimum)
        if maximum is not None:
            outside = outside | (values > maximum)
        offenders = frame.index[outside.fillna(False).to_numpy(dtype=bool)]
        if len(offenders):
            bounds = f"[{minimum if minimum is not None else '-vo cuc'}, "
            bounds += f"{maximum if maximum is not None else '+vo cuc'}]"
            failures.append(
                Failure(
                    test=f"{column}:range",
                    count=int(len(offenders)),
                    detail=f"{len(offenders)} gia tri nam ngoai khoang {bounds}.",
                    sample_rows=_sample_rows(frame, list(offenders)),
                )
            )
    return failures


def check_comparisons(
    frame: pd.DataFrame, rules: Sequence[tuple[str, str, str, str]]
) -> list[Failure]:
    """Check business rules that relate two columns.

    Args:
        frame: the frame under test.
        rules: (name, left column, operator, right column) tuples, for example
            ("approval_after_request", "approval_date", ">=", "request_date").

    Returns:
        One failure per rule that any row breaks.

    Raises:
        ValidationSpecError: the rule names an operator that does not exist.
    """
    failures: list[Failure] = []
    for name, left, symbol, right in rules:
        if symbol not in COMPARISONS:
            raise ValidationSpecError(
                f"Phep so sanh {symbol!r} khong hop le. Chi cho phep: "
                + ", ".join(sorted(COMPARISONS))
            )
        missing = [column for column in (left, right) if column not in frame.columns]
        if missing:
            failures.append(Failure(test=name, count=0, detail=f"Thieu cot de so sanh: {missing}."))
            continue

        holds = COMPARISONS[symbol](_comparable(frame[left]), _comparable(frame[right]))
        # A row where either side is missing cannot break the rule; only a row
        # where both are present and the comparison is false is a violation.
        both_present = frame[left].notna() & frame[right].notna()
        broken = both_present & ~holds.fillna(False).astype(bool)
        offenders = frame.index[broken.to_numpy(dtype=bool)]
        if len(offenders):
            failures.append(
                Failure(
                    test=name,
                    count=int(len(offenders)),
                    detail=f"{len(offenders)} dong vi pham {left} {symbol} {right}.",
                    sample_rows=_sample_rows(frame, list(offenders)),
                )
            )
    return failures


def check_pattern(frame: pd.DataFrame, rules: Sequence[tuple[str, str, str]]) -> list[Failure]:
    """Check that text columns hold the shape they are supposed to hold.

    Worth having now that documents and recordings feed this pipeline. A code
    typed into a spreadsheet is usually the right shape; the same code read off
    a scan is where `O` becomes `0` and `1` becomes `l`, and nothing downstream
    notices until a join quietly matches nothing.

    Args:
        frame: the frame under test.
        rules: (name, column, pattern) triples. The pattern must match from the
            start of the value - `fullmatch`, not `search`, because "contains a
            date somewhere" is not the same assertion as "is a date".

    Returns:
        One failure per column that has values of the wrong shape, or per rule
        that could not be run.
    """
    failures: list[Failure] = []
    for name, column, pattern in rules:
        test = name or f"{column}:pattern"
        if column not in frame.columns:
            failures.append(
                Failure(
                    test=test,
                    count=0,
                    detail=f"Khong co cot {column!r} de kiem dinh dang.",
                )
            )
            continue
        try:
            compiled = re.compile(pattern)
        except re.error as error:
            # A specification is written by a person or proposed by a model, and
            # neither is incapable of typing `[unclosed`. Falling over here would
            # take the whole run down for it.
            failures.append(
                Failure(
                    test=test,
                    count=0,
                    detail=f"Mau {pattern!r} khong bien dich duoc: {error}.",
                )
            )
            continue

        values = frame[column]
        present = values.notna()
        as_text = values.astype("string")
        # Bound to the argument rather than closed over: `.map` runs now, so a
        # closure would work today and break the day somebody makes this lazy.
        matches = as_text.map(
            lambda item, rule=compiled: (
                bool(rule.fullmatch(item)) if isinstance(item, str) else False
            )
        )
        # A missing value is not a wrongly shaped one. Whether a column may be
        # empty is what `not_null` is for, and answering it twice in two places
        # is how the two answers start to disagree.
        wrong = present & ~matches.fillna(False).astype(bool)
        offenders = frame.index[wrong.to_numpy(dtype=bool)]
        if len(offenders):
            failures.append(
                Failure(
                    test=test,
                    count=int(len(offenders)),
                    detail=f"{len(offenders)} gia tri khong khop mau {pattern!r}.",
                    sample_rows=_sample_rows(frame, list(offenders)),
                )
            )
    return failures


def check_time_window(
    frame: pd.DataFrame, rules: Sequence[tuple[str, str, str | None, str | None]]
) -> list[Failure]:
    """Check that timestamps fall inside the period the data is supposed to cover.

    The failure this catches is quiet and expensive: a row dated 1970 or 2099
    changes every average, every trend and every "which month sells most", and
    looks like data until somebody plots it.

    Args:
        frame: the frame under test.
        rules: (name, column, earliest, latest) tuples. Either bound may be
            None, and both are read the same way the column is.

    Returns:
        One failure per column with timestamps outside its window, per column
        that does not hold timestamps at all, and per bound that cannot be read.
    """
    failures: list[Failure] = []
    for name, column, earliest, latest in rules:
        test = name or f"{column}:time_window"
        if column not in frame.columns:
            failures.append(
                Failure(test=test, count=0, detail=f"Khong co cot {column!r} de kiem moc.")
            )
            continue

        values = frame[column]
        moments = pd.to_datetime(values, errors="coerce", format="mixed", utc=True)
        present = values.notna()
        unreadable = present & moments.isna()
        if bool(unreadable.all()) and bool(present.any()):
            # Reported rather than coerced. Parsing what parses and ignoring the
            # rest reports a clean column that was never checked at all.
            failures.append(
                Failure(
                    test=test,
                    count=int(present.sum()),
                    detail=f"Cot {column!r} khong doc duoc thanh moc thoi gian.",
                    sample_rows=_sample_rows(frame, list(frame.index[present.to_numpy()])),
                )
            )
            continue

        outside = pd.Series(False, index=frame.index)
        bounds: list[str] = []
        for bound, side in ((earliest, "truoc"), (latest, "sau")):
            if bound is None:
                continue
            edge = pd.to_datetime(bound, errors="coerce", utc=True)
            if pd.isna(edge):
                failures.append(
                    Failure(test=test, count=0, detail=f"Moc {bound!r} khong doc duoc.")
                )
                continue
            bounds.append(f"{side} {bound}")
            outside = outside | (moments < edge if side == "truoc" else moments > edge)

        # A value nobody could read is outside every window there is, and saying
        # so keeps it from being counted as inside one.
        outside = outside | unreadable
        offenders = frame.index[outside.fillna(False).to_numpy(dtype=bool)]
        if len(offenders) and bounds:
            failures.append(
                Failure(
                    test=test,
                    count=int(len(offenders)),
                    detail=(f"{len(offenders)} moc nam ngoai khoang ({', '.join(bounds)})."),
                    sample_rows=_sample_rows(frame, list(offenders)),
                )
            )
    return failures


def check_references(
    frame: pd.DataFrame, column: str, allowed: Iterable[Any], *, name: str = ""
) -> list[Failure]:
    """Check that every value of a column exists in a reference set.

    Returns:
        A single failure listing the values that have no match.
    """
    test = name or f"{column}:reference"
    if column not in frame.columns:
        return [Failure(test=test, count=0, detail=f"Khong co cot {column!r} de doi chieu.")]

    permitted = {str(value) for value in allowed}
    values = frame[column].dropna().astype(str)
    orphaned = frame.index[
        frame[column].notna().to_numpy(dtype=bool)
        & ~values.isin(permitted).reindex(frame.index, fill_value=False).to_numpy(dtype=bool)
    ]
    if not len(orphaned):
        return []
    unmatched = sorted({str(frame.loc[index, column]) for index in orphaned})[:3]
    return [
        Failure(
            test=test,
            count=int(len(orphaned)),
            detail=f"{len(orphaned)} gia tri khong co trong tap tham chieu. Vi du: {unmatched}.",
            sample_rows=_sample_rows(frame, list(orphaned)),
        )
    ]


# --- conformance: rules about sequences, not about rows -------------------------
#
# Everything above judges a row. These two judge a *case*: a set of rows in an
# order. Each row can be individually valid and the case still wrong, which is
# why they could not be expressed as column rules however the schema was bent.


def _cases(frame: pd.DataFrame, spec: EventLogSpec) -> tuple[pd.DataFrame, str | None]:
    """The log in the order things happened, or a reason it cannot be established.

    Order is taken from the same function the miner uses. Two answers to "what
    happened first" would be worse than none: the report and the referee would
    each be right about a different process.
    """
    missing = [name for name in spec.columns() if name not in frame.columns]
    if missing:
        return frame, f"khong co cot {missing} de doi chieu trinh tu."
    ordered, refused = order_events(frame, spec)
    if ordered.empty:
        return ordered, "khong con dong nao dung duoc sau khi loc."
    if spec.timestamp and "_ts" not in ordered.columns:
        # order_events explains why in `refused`; carry that through rather than
        # inventing a second wording for the same fact.
        return ordered, "; ".join(refused) or "khong doc duoc cot thoi gian."
    return ordered, None


def _unverifiable(test: str, reason: str) -> Failure:
    """A check that could not be carried out, reported as a failure on purpose.

    Not because the data broke the rule - it may well not have - but because a
    check that quietly passes when it could not run is worse than no check. A5
    halts on any failure, and refusing to analyse a process whose order nobody
    can establish is the right thing to halt on.
    """
    return Failure(test=f"{test}:unverifiable", count=0, detail=f"KHONG KIEM DUOC: {reason}")


def check_sequence_order(
    frame: pd.DataFrame,
    spec: EventLogSpec,
    pairs: Sequence[tuple[str, str]],
    *,
    name: str = "",
) -> list[Failure]:
    """Check that one activity never happens before another that must precede it.

    A case violates the rule when the later activity occurs and the earlier one
    either never occurred at all, or occurred after it. Both are the same defect
    from a control point of view - the step meant to authorise the next one did
    not do so - so they are reported together and the detail says which.

    Args:
        frame: the event log. It is never modified.
        spec: which column plays which role.
        pairs: (before, after) - `before` must precede `after` in every case.
        name: prefix for the test names, when the caller wants its own.

    Returns:
        One failure per rule that was broken, naming the cases that broke it.
    """
    failures: list[Failure] = []
    for before, after in pairs:
        test = name or f"order:{before}__before__{after}"
        ordered, reason = _cases(frame, spec)
        if reason is not None:
            failures.append(_unverifiable(test, reason))
            continue

        offending: list[Any] = []
        missing_entirely = 0
        for _, group in ordered.groupby(spec.case_id, sort=True):
            steps = list(group[spec.activity])
            if after not in steps:
                continue
            first_after = steps.index(after)
            if before not in steps:
                missing_entirely += 1
                offending.append(group.index[first_after])
            elif steps.index(before) > first_after:
                offending.append(group.index[first_after])

        if not offending:
            continue
        detail = f"{len(offending)} case co {after!r} ma khong co {before!r} truoc do."
        if missing_entirely:
            detail += f" Trong do {missing_entirely} case khong he co {before!r}."
        failures.append(
            Failure(
                test=test,
                count=len(offending),
                detail=detail,
                sample_rows=_sample_rows(ordered, offending),
            )
        )
    return failures


def check_segregation_of_duties(
    frame: pd.DataFrame,
    spec: EventLogSpec,
    pairs: Sequence[tuple[str, str]],
    *,
    name: str = "",
) -> list[Failure]:
    """Check that no one person performed both halves of a duty meant to be split.

    The classic control: whoever raises the order must not be whoever approves
    it. Violations are counted per case and the offending performers are named,
    because "somebody did both" is not something anyone can act on.

    Order does not matter here - doing both is the violation regardless of which
    came first - so this still works on a log with no usable timestamp.

    Args:
        frame: the event log. It is never modified.
        spec: which column plays which role. `resource` is required.
        pairs: activity pairs that one person must not both perform.
        name: prefix for the test names, when the caller wants its own.

    Returns:
        One failure per rule that was broken, naming who broke it.
    """
    failures: list[Failure] = []
    for first, second in pairs:
        test = name or f"sod:{first}__vs__{second}"
        if not spec.resource:
            failures.append(_unverifiable(test, "khong khai cot nguoi thuc hien."))
            continue
        ordered, reason = _cases(frame, spec)
        if reason is not None and spec.timestamp is None:
            failures.append(_unverifiable(test, reason))
            continue
        if spec.resource not in ordered.columns:
            failures.append(_unverifiable(test, f"khong co cot {spec.resource!r}."))
            continue

        offending: list[Any] = []
        culprits: set[str] = set()
        for _, group in ordered.groupby(spec.case_id, sort=True):
            acted = group[group[spec.activity].isin([first, second])]
            by_person = acted.groupby(spec.resource, sort=True)[spec.activity].nunique()
            both = [str(person) for person, count in by_person.items() if count > 1]
            if not both:
                continue
            culprits.update(both)
            offending.extend(acted.index[acted[spec.resource].astype(str).isin(both)])

        if not offending:
            continue
        named = sorted(culprits)[:3]
        failures.append(
            Failure(
                test=test,
                count=len(offending),
                detail=(
                    f"{len(offending)} su kien: cung mot nguoi lam ca {first!r} lan "
                    f"{second!r} trong mot case. Vi du: {named}."
                ),
                sample_rows=_sample_rows(ordered, offending),
            )
        )
    return failures
