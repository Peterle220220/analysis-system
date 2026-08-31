"""PII masking, applied before every single LLM call.

Two decisions from the spec shape this module.

**Regex only, for patterns that are actually identifiable.** Email, phone, tax
code, bank account and national id have a shape. Personal names do not, and
Vietnamese name detection by NER is unreliable and expensive, so this module
does not attempt it.

**Names are handled by never sending the column at all.** Once A2 flags a column
as personal data, its values do not go to the model - only the column name and
aggregate statistics do. That is a stronger guarantee than masking, because it
cannot be defeated by a value the patterns fail to recognise.

The mapping from token back to the original value lives in memory for the
lifetime of one masker, is never written to disk, and is never sent anywhere.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from functools import partial
from typing import Any, Final

import pandas as pd

MAX_LLM_SAMPLE_ROWS: Final[int] = 20

# Order matters. Longer, more specific shapes are consumed first so a bank
# account pattern cannot swallow a phone number that appears inside it.
PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("EMAIL", re.compile(r"\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b")),
    # TAX_ID before PHONE: a tax id is ten digits plus a dashed branch
    # code, and the phone pattern would otherwise eat its first ten digits
    # and report the whole thing as a phone number.
    ("TAX_ID", re.compile(r"(?<!\d)\d{10}(?:-\d{3})(?!\d)")),
    ("PHONE", re.compile(r"(?<![\w+])(?:\+84|0)(?:\d[ .-]?){8,9}\d(?![\w])")),
    ("NATIONAL_ID", re.compile(r"(?<!\d)\d{12}(?!\d)")),
    ("BANK_ACCOUNT", re.compile(r"(?<!\d)\d{8,19}(?!\d)")),
)


class PiiMasker:
    """Replaces identifiable values with stable tokens.

    The same value always receives the same token inside one masker, so the
    model can still reason about repetition without ever seeing the value.
    """

    def __init__(self) -> None:
        """Start with an empty, in-memory mapping."""
        self._tokens: dict[tuple[str, str], str] = {}
        self._counts: dict[str, int] = {}

    @property
    def token_count(self) -> int:
        """How many distinct values have been masked."""
        return len(self._tokens)

    def _token_for(self, kind: str, value: str) -> str:
        """Return the stable token for one value, minting it on first sight."""
        key = (kind, value)
        existing = self._tokens.get(key)
        if existing is not None:
            return existing
        self._counts[kind] = self._counts.get(kind, 0) + 1
        token = f"<{kind}_{self._counts[kind]}>"
        self._tokens[key] = token
        return token

    def _substitute(self, kind: str, match: re.Match[str]) -> str:
        """Replacement callback for one pattern kind."""
        return self._token_for(kind, match.group(0))

    def mask_text(self, text: str, column_name: str = "") -> str:
        """Replace recognised values with tokens.

        Distinctive shapes are masked wherever they appear. Bare digit runs are
        masked only in a column whose name says they are account or document
        numbers - blanking every long number would hide prices and quantities
        while protecting nobody.
        """
        wide = name_suggests_pii(column_name)
        masked = text
        for kind, pattern in PATTERNS:
            if kind not in GUARDED_KINDS and not wide:
                continue
            masked = pattern.sub(partial(self._substitute, kind), masked)
        return masked

    def mask_value(self, value: Any, column_name: str = "") -> Any:
        """Mask a single cell, leaving non-text values untouched."""
        if isinstance(value, str):
            return self.mask_text(value, column_name)
        return value

    def mask_rows(self, rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        """Mask every string cell in a list of rows, with its column as context."""
        return [
            {key: self.mask_value(value, str(key)) for key, value in row.items()} for row in rows
        ]


def _blank(match: re.Match[str]) -> str:
    """Blank out a claimed span so a later pattern cannot claim it again."""
    return " " * len(match.group(0))


# Shapes that identify a person on their own. A bare digit run does not: a
# purchase document number, an order id and a house price all match one.
STRONG_KINDS: Final[frozenset[str]] = frozenset({"EMAIL", "PHONE", "TAX_ID"})

# What the leak guard refuses to let past, and what is masked in every column
# regardless of its name.
GUARDED_KINDS: Final[frozenset[str]] = STRONG_KINDS

# Column-name fragments that make a digit run credible as personal data.
# Deliberately specific: a bare "id" would match case_id and defeat the purpose.
PII_NAME_HINTS: Final[tuple[str, ...]] = (
    "account",
    "acct",
    "bank",
    "iban",
    "stk",
    "tai_khoan",
    "taikhoan",
    "tax",
    "mst",
    "cccd",
    "cmnd",
    "national_id",
    "citizen",
    "passport",
    "ssn",
    "email",
    "mail",
    "phone",
    "mobile",
    "dien_thoai",
)


def find_pii_kinds(text: str) -> set[str]:
    """Which pattern kinds match, consuming spans in the same order as masking."""
    kinds: set[str] = set()
    working = text
    for kind, pattern in PATTERNS:
        if pattern.search(working):
            kinds.add(kind)
        working = pattern.sub(_blank, working)
    return kinds


def name_suggests_pii(column_name: str) -> bool:
    """True when the column name itself points at personal data."""
    lowered = column_name.lower()
    return any(hint in lowered for hint in PII_NAME_HINTS)


def find_pii(text: str) -> list[str]:
    """Return every recognised value still present in a string.

    Patterns are applied in the same order, and consume the same spans, as
    mask_text. Without that, a ten digit phone number would be reported twice -
    once as PHONE and again as BANK_ACCOUNT - and the count would be fiction.

    Used as a last line of defence right before a request leaves the process.
    """
    found: list[str] = []
    working = text
    for _, pattern in PATTERNS:
        found.extend(match.group(0) for match in pattern.finditer(working))
        working = pattern.sub(_blank, working)
    return found


class PiiLeakError(RuntimeError):
    """Data that looks personal was about to be sent to a model."""


def assert_no_pii(payload: str) -> None:
    """Fail loudly rather than let an unmasked value reach the model.

    Only the distinctive shapes are checked. A bare run of digits cannot be
    judged without knowing which column it came from: a house price of
    26,590,000 matches the bank-account pattern, and refusing it would block a
    price list while protecting nobody.

    Raises:
        PiiLeakError: the payload still contains an email, phone or tax id.
    """
    found = find_pii_kinds(payload) & GUARDED_KINDS
    if found:
        raise PiiLeakError(
            f"Con gia tri chua duoc che ({', '.join(sorted(found))}). Khong duoc gui len LLM."
        )


def column_statistics(series: pd.Series[Any]) -> dict[str, Any]:
    """Aggregate description of a column, carrying no individual value."""
    total = int(series.size)
    non_null = int(series.notna().sum())
    lengths = series.dropna().astype(str).str.len()
    return {
        "dtype": str(series.dtype),
        "row_count": total,
        "null_pct": 0.0 if total == 0 else round(100.0 * (total - non_null) / total, 2),
        "distinct": int(series.nunique(dropna=True)),
        "avg_length": round(float(lengths.mean()), 2) if len(lengths) else 0.0,
    }


def build_llm_sample(
    frame: pd.DataFrame,
    *,
    pii_columns: Iterable[str] = (),
    max_rows: int = MAX_LLM_SAMPLE_ROWS,
    masker: PiiMasker | None = None,
) -> dict[str, Any]:
    """Build the only view of a dataset an LLM is ever allowed to see.

    Columns flagged as personal contribute statistics and nothing else. Every
    other column contributes at most max_rows sample rows, masked.

    Args:
        frame: the data to describe.
        pii_columns: columns A2 flagged as personal.
        max_rows: hard ceiling on sample rows, never exceeded.
        masker: reuse an existing masker to keep tokens stable across calls.

    Returns:
        A mapping safe to serialise into a prompt.
    """
    flagged = {str(name) for name in pii_columns}
    active = masker or PiiMasker()
    columns = [str(name) for name in frame.columns]

    safe_columns = [name for name in columns if name not in flagged]
    limit = min(max_rows, MAX_LLM_SAMPLE_ROWS, len(frame.index))
    records = frame.loc[:, safe_columns].head(limit).to_dict(orient="records")
    sample_rows = active.mask_rows(
        [{str(name): value for name, value in row.items()} for row in records]
    )

    return {
        "row_count": int(len(frame.index)),
        "column_count": len(columns),
        "columns": columns,
        "pii_columns": sorted(flagged),
        "statistics": {name: column_statistics(frame[name]) for name in columns},
        "sample_rows": sample_rows,
        "sample_note": (
            f"Toi da {limit} dong mau, da che PII. "
            f"Cac cot PII ({len(flagged)}) chi gui thong ke, khong gui gia tri."
        ),
    }
