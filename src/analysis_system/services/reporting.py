"""Report rendering. A template places every number; no LLM ever writes one.

From Phase 2 an LLM may write the prose around these numbers, but the figures
themselves are always substituted by this module, so a report can never state a
value that was not computed.

Volatile lines carry an explicit marker instead of being matched by keyword.
Keyword matching looked fine until the column statistics table gained a row for
a column literally named "timestamp": that row is substantive content, and a
keyword rule would have silently dropped it from the comparison hash, hiding
real regressions.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final

import pandas as pd

from analysis_system.services.hashing import canonical_hash_text
from analysis_system.services.rulebook import DiffEntry
from analysis_system.services.validation import ValidationReport

# Appended to any line whose value legitimately changes between identical runs.
VOLATILE_MARKER: Final[str] = "<!--volatile-->"


@dataclass(frozen=True)
class ColumnStat:
    """Descriptive statistics for one column. Computed by code, always."""

    name: str
    dtype: str
    non_null: int
    null_pct: float
    distinct: int


@dataclass(frozen=True)
class ReportContext:
    """Everything the template is allowed to print."""

    run_id: str
    generated_at: str
    duration_s: float
    source_path: str
    source_hash: str
    rows_in: int
    rows_out: int
    rules_applied: tuple[str, ...]
    diff_summary: tuple[tuple[str, int], ...]
    validation: ValidationReport
    column_stats: tuple[ColumnStat, ...]
    output_hashes: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    @property
    def rows_dropped_pct(self) -> float:
        """Percentage of rows removed between input and output."""
        if self.rows_in == 0:
            return 0.0
        return 100.0 * (self.rows_in - self.rows_out) / self.rows_in


def summarise_columns(frame: pd.DataFrame) -> tuple[ColumnStat, ...]:
    """Compute per-column statistics in a fixed, name-sorted order."""
    total = len(frame.index)
    stats: list[ColumnStat] = []
    for name in sorted(str(column) for column in frame.columns):
        series = frame[name]
        non_null = int(series.notna().sum())
        null_pct = 0.0 if total == 0 else 100.0 * (total - non_null) / total
        stats.append(
            ColumnStat(
                name=name,
                dtype=str(series.dtype),
                non_null=non_null,
                null_pct=null_pct,
                distinct=int(series.nunique(dropna=True)),
            )
        )
    return tuple(stats)


def summarise_diff(diff: Sequence[DiffEntry]) -> tuple[tuple[str, int], ...]:
    """Count diff entries per reason, sorted so the order never varies."""
    counts: dict[str, int] = {}
    for entry in diff:
        counts[entry.reason] = counts.get(entry.reason, 0) + 1
    return tuple(sorted(counts.items()))


def _volatile(line: str) -> str:
    """Mark a line whose value changes between otherwise identical runs."""
    return f"{line} {VOLATILE_MARKER}"


def render_report(context: ReportContext) -> str:
    """Render the Phase 0 pipeline report as Markdown.

    Returns:
        The full report text. Every number comes from the context.
    """
    lines: list[str] = [
        "# Báo cáo pipeline: Phase 0",
        "",
        "## Lần chạy",
        "",
        _volatile(f"- Run id: `{context.run_id}`"),
        _volatile(f"- Thời điểm: {context.generated_at}"),
        _volatile(f"- Thời gian chạy: {context.duration_s:.2f}s"),
        "",
        "## Nguồn",
        "",
        # The absolute path is environment noise; the hash below is the real identity.
        _volatile(f"- File: `{context.source_path}`"),
        f"- SHA-256: `{context.source_hash}`",
        "",
        "## Làm sạch",
        "",
        f"- Số dòng vào: **{context.rows_in}**",
        f"- Số dòng ra: **{context.rows_out}**",
        f"- Tỷ lệ dòng bị bỏ: **{context.rows_dropped_pct:.2f}%**",
        f"- Rule đã áp dụng ({len(context.rules_applied)}): "
        + ", ".join(f"`{rule}`" for rule in context.rules_applied),
        "",
    ]

    if context.diff_summary:
        lines.extend(["| Thay đổi | Số lượng |", "|---|---:|"])
        lines.extend(f"| {reason} | {count} |" for reason, count in context.diff_summary)
    else:
        lines.append("Không có thay đổi nào được ghi nhận.")
    lines.append("")

    verdict = "PASS" if context.validation.is_ok else "FAIL"
    lines.extend(
        [
            "## Kiểm định",
            "",
            f"- Kết quả: **{verdict}**",
            f"- Số kiểm tra đạt: **{context.validation.passed}**",
            f"- Số kiểm tra hỏng: **{context.validation.failed}**",
            "",
        ]
    )
    if context.validation.failures:
        lines.extend(["| Kiểm tra | Số vi phạm | Chi tiết |", "|---|---:|---|"])
        lines.extend(
            f"| `{failure.test}` | {failure.count} | {failure.detail} |"
            for failure in context.validation.failures
        )
        lines.append("")

    lines.extend(
        [
            "## Thống kê cột",
            "",
            "| Cột | Kiểu | Không rỗng | % rỗng | Số giá trị khác nhau |",
            "|---|---|---:|---:|---:|",
        ]
    )
    lines.extend(
        f"| `{stat.name}` | {stat.dtype} | {stat.non_null} | "
        f"{stat.null_pct:.2f} | {stat.distinct} |"
        for stat in context.column_stats
    )
    lines.append("")

    if context.output_hashes:
        lines.extend(["## Hash đầu ra", "", "| Tầng | canonical_hash |", "|---|---|"])
        lines.extend(f"| {label} | `{value}` |" for label, value in context.output_hashes)
        lines.append("")

    return "\n".join(lines)


def report_hash(text: str) -> str:
    """Hash a report, ignoring only the lines explicitly marked volatile."""
    return canonical_hash_text(text, drop_patterns=[re.escape(VOLATILE_MARKER)])
