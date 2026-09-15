"""Phase 0 sequential driver: CSV to staging, clean, validate, report.

This module exists only for Phase 0. In Phase 1 the Manager takes over the
sequencing and this file goes away; the services it calls stay exactly as they
are, wrapped in a scope check rather than rewritten.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from analysis_system.core import storage
from analysis_system.core.hashing import canonical_hash
from analysis_system.core.settings import Settings, resolve
from analysis_system.services import reporting
from analysis_system.services.rulebook import DiffEntry, RuleSpec, apply_rules
from analysis_system.services.validation import (
    ColumnRule,
    SchemaSpec,
    ValidationReport,
    run_checks,
)

STAGING_NAME = "events.parquet"
CLEAN_NAME = "events.parquet"
REPORT_NAME = "pipeline_report.md"


@dataclass(frozen=True)
class RunSummary:
    """What one end-to-end run produced."""

    run_id: str
    staging_path: Path
    clean_path: Path
    report_path: Path
    rows_in: int
    rows_out: int
    staging_hash: str
    clean_hash: str
    report_hash: str
    validation: ValidationReport

    @property
    def is_ok(self) -> bool:
        """True when validation passed."""
        return self.validation.is_ok


def make_run_id(now: datetime | None = None) -> str:
    """Build a run id from the clock. The only nondeterministic value here."""
    moment = now or datetime.now(UTC)
    return "r_" + moment.strftime("%Y%m%dT%H%M%S")


def ingest(source: Path, settings: Settings) -> tuple[pd.DataFrame, Path]:
    """Load the source CSV into the staging layer without altering a single cell.

    Returns:
        The staged frame and the path it was written to.
    """
    frame = storage.read_csv(source)
    target = resolve(f"staging://{STAGING_NAME}", settings)
    storage.write_parquet(frame, target)
    return frame, target


def build_plan(settings: Settings) -> list[RuleSpec]:
    """Build the approved rule plan from configuration.

    The order the rules appear here is irrelevant: the rulebook applies its own
    declared order.
    """
    cleaning = settings.cleaning
    return [
        RuleSpec("trim_whitespace"),
        RuleSpec("normalize_unicode_nfc"),
        RuleSpec(
            "standardize_datetime",
            cleaning.datetime_columns,
            {"assume_timezone": cleaning.assume_timezone},
        ),
        RuleSpec("cast_numeric_safe", cleaning.numeric_columns),
        RuleSpec("drop_exact_duplicates"),
        RuleSpec("flag_missing_required", cleaning.required_columns),
    ]


def clean(frame: pd.DataFrame, settings: Settings) -> tuple[pd.DataFrame, Path, list[DiffEntry]]:
    """Apply the approved rules and write the result to the clean layer.

    Returns:
        The cleaned frame, the path written, and the diff log.
    """
    outcome = apply_rules(frame, build_plan(settings))
    target = resolve(f"clean://{CLEAN_NAME}", settings)
    storage.write_parquet(outcome.frame, target)
    return outcome.frame, target, list(outcome.diff)


def build_schema_spec(settings: Settings) -> SchemaSpec:
    """Translate the configured contract into a schema specification."""
    return SchemaSpec(
        columns=tuple(
            ColumnRule(name=name, nullable=False) for name in settings.validation.not_null_columns
        ),
        unique_together=settings.validation.unique_together,
    )


def validate(frame: pd.DataFrame, rows_in: int, settings: Settings) -> ValidationReport:
    """Judge the cleaned frame. Never modifies it."""
    return run_checks(
        frame,
        build_schema_spec(settings),
        rows_in=rows_in,
        max_drop_pct=settings.validation.max_rows_dropped_pct,
    )


def run_pipeline(source: Path, settings: Settings, *, run_id: str | None = None) -> RunSummary:
    """Run the whole Phase 0 pipeline end to end.

    Args:
        source: the CSV to process.
        settings: loaded configuration.
        run_id: identifier for this run; generated from the clock when omitted.

    Returns:
        A summary containing every output path and content hash.
    """
    started = time.monotonic()
    identifier = run_id or make_run_id()

    staged, staging_path = ingest(source, settings)
    cleaned, clean_path, diff = clean(staged, settings)
    verdict = validate(cleaned, len(staged.index), settings)

    staging_hash = canonical_hash(staged)
    clean_hash = canonical_hash(cleaned)

    context = reporting.ReportContext(
        run_id=identifier,
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        duration_s=time.monotonic() - started,
        source_path=str(source),
        source_hash=storage.sha256_file(source),
        rows_in=len(staged.index),
        rows_out=len(cleaned.index),
        rules_applied=tuple(spec.rule_id for spec in build_plan(settings)),
        diff_summary=reporting.summarise_diff(diff),
        validation=verdict,
        column_stats=reporting.summarise_columns(cleaned),
        output_hashes=(("staging", staging_hash), ("clean", clean_hash)),
    )
    text = reporting.render_report(context)
    report_path = resolve(f"artifacts://{REPORT_NAME}", settings)
    storage.write_text(text, report_path)

    return RunSummary(
        run_id=identifier,
        staging_path=staging_path,
        clean_path=clean_path,
        report_path=report_path,
        rows_in=len(staged.index),
        rows_out=len(cleaned.index),
        staging_hash=staging_hash,
        clean_hash=clean_hash,
        report_hash=reporting.report_hash(text),
        validation=verdict,
    )
