"""Bang nay co can lam sach khong, va can o dau - do bang code.

The cleaner proposes rules and a person approves them. What was missing sits
either side of that: nobody ever said *whether anything needed cleaning at
all*, and the reasons attached to each rule were prose a model wrote rather
than something counted.

Both matter for the same reason. A table nobody examined and a table examined
and found clean produce the identical gate - an empty list of rules - and the
person reading it cannot tell which they are looking at. And a rule justified
by "cot nay co ve co khoang trang thua" is a rule approved on somebody's
impression; one justified by "47 gia tri trong 1.200 dong co khoang trang o
dau hoac cuoi" is a rule approved on a fact.

So this counts. Every finding here carries how many values it touches and
which column they are in, and a table with no findings is reported as
**examined and clean**, listing what was looked at.

No model. Counting trailing spaces is arithmetic, and an arithmetic answer that
changes between runs is not an answer.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final

import pandas as pd

# A value that is only a placeholder for a missing one. Written out rather than
# guessed, because deciding that "0" means missing is a judgement about the
# data that belongs to whoever owns it.
SENTINELS: Final[frozenset[str]] = frozenset(
    {"", "na", "n/a", "null", "none", "nil", "-", "--", "?", "khong co", "khong ro"}
)

# Below this share of parseable numbers, a text column is a category code that
# happens to contain digits rather than a measure stored as text.
NUMERIC_SHARE: Final[float] = 0.9

# A column with more distinct values than this share of its rows is closer to
# an identifier than a category, and casting or trimming it is riskier.
IDENTIFIER_SHARE: Final[float] = 0.95

DATE_LIKE: Final[re.Pattern[str]] = re.compile(
    r"^\s*\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}([ T]\d{1,2}:\d{2})?\s*$"
)


@dataclass(frozen=True)
class Finding:
    """One thing in the data that could be cleaned, and how much of it there is."""

    rule_id: str
    column: str
    affected: int
    total: int
    detail: str
    # What the rule needs in order to run, taken from what was counted rather
    # than from a default. `replace_sentinel_with_null` will not run without the
    # list of sentinels, and naming the ones actually found beats handing over
    # the whole vocabulary: a person reading "NA, -" learns what is in their
    # data, and the rule touches nothing else.
    params: Mapping[str, Any] = field(default_factory=dict)

    @property
    def share_pct(self) -> float:
        """What fraction of the column this touches."""
        return 100.0 * self.affected / self.total if self.total else 0.0

    def as_reason(self) -> str:
        """The sentence a person reads at the gate - counted, not guessed."""
        return f"{self.detail} ({self.affected:,}/{self.total:,} dòng, {self.share_pct:.1f}%)"


@dataclass(frozen=True)
class Diagnosis:
    """What an examination of one table found."""

    rows: int
    columns: tuple[str, ...]
    findings: tuple[Finding, ...] = ()
    examined: tuple[str, ...] = ()

    @property
    def needs_cleaning(self) -> bool:
        """True when there is something to fix."""
        return bool(self.findings)

    @property
    def verdict(self) -> str:
        """What to tell the person, in one sentence.

        The clean case is stated as plainly as the dirty one. "Nothing found"
        and "nothing looked for" are different answers, and a gate that shows
        an empty list says the second while meaning the first.
        """
        if self.findings:
            columns = sorted({finding.column for finding in self.findings})
            return (
                f"Đã xem {self.rows:,} dòng trên {len(self.columns)} cột. Hệ thống đọc "
                "mọi cột dưới dạng chữ để không tự ý diễn giải sai dữ liệu "
                "của bạn. "
                f"Có {len(self.findings)} cột cần sửa: " + ", ".join(columns)
            )
        return (
            f"Đã xem {self.rows:,} dòng trên {len(self.columns)} cột và KHÔNG thấy gì "
            f"cần sửa. Đã kiểm: {', '.join(self.examined)}."
        )


# A finding about the table rather than about one column. Named here because two
# modules have to agree on it: writing it out twice is how a seeded rule ends up
# scoped to a column called "(moi cot)".
EVERY_COLUMN: Final[str] = "(mọi cột)"


def _text_columns(frame: pd.DataFrame) -> list[str]:
    return [
        str(name)
        for name in frame.columns
        if not pd.api.types.is_numeric_dtype(frame[name])
        and not pd.api.types.is_datetime64_any_dtype(frame[name])
    ]


def _untrimmed(values: pd.Series) -> int:
    text = values.dropna().astype(str)
    return int((text != text.str.strip()).sum())


def _unnormalised(values: pd.Series) -> int:
    text = values.dropna().astype(str)
    return int(sum(1 for item in text if unicodedata.normalize("NFC", item) != item))


def _sentinels_found(values: pd.Series) -> tuple[int, tuple[str, ...]]:
    """How many stand-ins for "missing" a column holds, and which ones."""
    text = values.dropna().astype(str).str.strip().str.lower()
    hit = text[text.isin(SENTINELS)]
    return int(hit.size), tuple(sorted(set(hit)))


def _numeric_share(values: pd.Series) -> float:
    text = values.dropna().astype(str).str.strip()
    if text.empty:
        return 0.0
    parsed = pd.to_numeric(text.str.replace(",", "", regex=False), errors="coerce")
    return float(parsed.notna().mean())


def _has_leading_zeros(values: pd.Series) -> bool:
    """True when any value carries a leading zero that casting would destroy.

    `"0"` and `"0.5"` are numbers written normally; `"00001"` and `"07"` are
    codes written with a width. Only the second kind loses anything by becoming
    a number, and it loses it in a way nothing downstream can detect.
    """
    text = values.dropna().astype(str).str.strip()
    return bool(text.str.match(r"^-?0\d").any())


def _date_share(values: pd.Series) -> float:
    text = values.dropna().astype(str)
    if text.empty:
        return 0.0
    return float(text.str.match(DATE_LIKE).mean())


def examine(frame: pd.DataFrame) -> Diagnosis:
    """Look at a table and say what, if anything, needs cleaning.

    Every check is a count over the actual values. Where a check does not apply
    - a numeric column has no trailing spaces to find - it is simply not run,
    and what *was* run is reported so a clean verdict can be read as a claim
    about something rather than an absence of effort.
    """
    rows = len(frame.index)
    columns = tuple(str(name) for name in frame.columns)
    findings: list[Finding] = []
    examined: list[str] = []

    if rows == 0:
        return Diagnosis(rows=0, columns=columns, examined=("bảng rỗng",))

    duplicates = int(frame.duplicated().sum())
    examined.append("dòng trùng lặp")
    if duplicates:
        findings.append(
            Finding(
                rule_id="drop_exact_duplicates",
                column=EVERY_COLUMN,
                affected=duplicates,
                total=rows,
                detail="có dòng trùng lặp hoàn toàn",
            )
        )

    text_columns = _text_columns(frame)
    if text_columns:
        examined.extend(["khoảng trắng thừa", "dấu tiếng Việt chưa chuẩn", "giá trị thay thế"])

    for name in text_columns:
        values = frame[name]
        present = int(values.notna().sum())
        if not present:
            continue

        untrimmed = _untrimmed(values)
        if untrimmed:
            findings.append(
                Finding(
                    "trim_whitespace",
                    name,
                    untrimmed,
                    present,
                    "có khoảng trắng ở đầu hoặc cuối ô",
                )
            )

        unnormalised = _unnormalised(values)
        if unnormalised:
            findings.append(
                Finding(
                    "normalize_unicode_nfc",
                    name,
                    unnormalised,
                    present,
                    "dấu tiếng Việt chưa ở dạng chuẩn NFC",
                )
            )

        sentinels, which = _sentinels_found(values)
        if sentinels:
            findings.append(
                Finding(
                    "replace_sentinel_with_null",
                    name,
                    sentinels,
                    present,
                    f"là giá trị thay thế cho ô trống ({', '.join(which)})",
                    params={"sentinels": list(which)},
                )
            )

        # Casting is proposed only where it is safe. A column that is almost
        # all distinct is an identifier, and "00001" cast to a number is 1.
        #
        # Distinctness alone is not enough. A postcode column repeats itself
        # freely and would pass that test, and casting it would silently drop
        # the leading zero from every value - a loss no later step can see,
        # because "1234" is a perfectly good number.
        distinct_share = values.nunique(dropna=True) / present
        if (
            _numeric_share(values) >= NUMERIC_SHARE
            and distinct_share < IDENTIFIER_SHARE
            and not _has_leading_zeros(values)
        ):
            findings.append(
                Finding(
                    "cast_numeric_safe",
                    name,
                    present,
                    present,
                    # Noi ro he thong da lam gi, thay vi noi nhu the du lieu cua nguoi
                    # dung co loi. Trong Excel cot nay LA so; no thanh chu vi
                    # chinh he thong doc moi cot duoi dang chu.
                    "toàn bộ là số, cần chuyển sang kiểu số để tính được",
                )
            )
        if _date_share(values) >= NUMERIC_SHARE:
            findings.append(
                Finding(
                    "standardize_datetime",
                    name,
                    present,
                    present,
                    "toàn bộ là ngày tháng, cần chuyển sang kiểu ngày để tính được",
                )
            )

    return Diagnosis(rows=rows, columns=columns, findings=tuple(findings), examined=tuple(examined))
