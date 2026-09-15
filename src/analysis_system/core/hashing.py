"""Canonical hashing: the one definition of "same output" (criterion S1).

Parquet bytes are not comparable across runs because pyarrow embeds writer
metadata, so equality is defined over table *content* instead: normalise every
cell to text, sort rows and columns, then hash. Reports are hashed only after
the volatile fields (run id, timestamps, durations, cost) are removed.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterable, Sequence
from typing import Final

import pandas as pd

FLOAT_FORMAT: Final[str] = "{:.10g}"
CELL_SEPARATOR: Final[str] = "\t"
ROW_SEPARATOR: Final[str] = "\n"

# Trailing \w* is required: \b would not match "duration_s" or "run_id_prev",
# because an underscore is itself a word character.
DEFAULT_VOLATILE_PATTERNS: Final[tuple[str, ...]] = (
    r"(?i)\brun[_ ]?id\w*",
    r"(?i)\btimestamp\w*",
    r"(?i)\bduration\w*",
    r"(?i)\bcost\w*",
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}",
)


def _is_missing(value: object) -> bool:
    """Return True for None, NaN, NaT and pandas NA.

    The three missing markers are compared by identity rather than passed to
    pandas.isna, which is typed for arrays and cannot accept a bare object.
    """
    if value is None or value is pd.NaT or value is pd.NA:
        return True
    return isinstance(value, float) and math.isnan(value)


def _normalise_cell(value: object) -> str:
    """Render one cell as deterministic text.

    Missing values collapse to the empty string and floats use a fixed format so
    that 1.10 and 1.1 cannot hash differently.
    """
    if _is_missing(value):
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return FLOAT_FORMAT.format(value)
    text = str(value)
    return (
        text.replace("\\", "\\\\")
        .replace(CELL_SEPARATOR, "\\t")
        .replace(ROW_SEPARATOR, "\\n")
        .replace("\r", "\\r")
    )


def canonical_frame(frame: pd.DataFrame, *, sort_keys: Sequence[str] | None = None) -> str:
    """Serialise a frame to its canonical text form.

    Columns are ordered by name and rows are sorted by their rendered text, so
    neither row order nor column order can change the result.

    Args:
        frame: the table to serialise.
        sort_keys: columns to sort rows by. When omitted, rows are sorted by
            their full rendered content.

    Returns:
        The canonical serialisation.

    Raises:
        KeyError: a requested sort key is not a column of the frame.
    """
    columns = sorted(str(column) for column in frame.columns)
    if sort_keys is not None:
        missing = [key for key in sort_keys if key not in columns]
        if missing:
            raise KeyError(f"Khong co cot de sap xep: {missing}")

    rendered: dict[str, list[str]] = {
        column: [_normalise_cell(value) for value in frame[column].tolist()] for column in columns
    }
    row_count = len(frame.index)
    rows = [
        CELL_SEPARATOR.join(rendered[column][index] for column in columns)
        for index in range(row_count)
    ]
    if sort_keys is None:
        rows.sort()
    else:
        order = sorted(
            range(row_count),
            key=lambda index: tuple(rendered[key][index] for key in sort_keys),
        )
        rows = [rows[index] for index in order]

    header = CELL_SEPARATOR.join(columns)
    return ROW_SEPARATOR.join([header, *rows])


def canonical_hash(frame: pd.DataFrame, *, sort_keys: Sequence[str] | None = None) -> str:
    """Return the SHA-256 over the canonical form of a frame."""
    payload = canonical_frame(frame, sort_keys=sort_keys)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def strip_volatile_lines(text: str, *, drop_patterns: Iterable[str] | None = None) -> str:
    """Drop every line carrying a value that changes between runs."""
    patterns = [re.compile(p) for p in (drop_patterns or DEFAULT_VOLATILE_PATTERNS)]
    kept = [
        line for line in text.splitlines() if not any(pattern.search(line) for pattern in patterns)
    ]
    return ROW_SEPARATOR.join(kept)


def canonical_hash_text(text: str, *, drop_patterns: Iterable[str] | None = None) -> str:
    """Return the SHA-256 of a report once its volatile lines are removed."""
    stripped = strip_volatile_lines(text, drop_patterns=drop_patterns)
    return hashlib.sha256(stripped.encode("utf-8")).hexdigest()
