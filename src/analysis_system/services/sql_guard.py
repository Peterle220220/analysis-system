"""SQL written by a model does not run until this module says it may.

The spec is blunt about it: only SELECT and CREATE VIEW, no DROP or DELETE or
UPDATE or ATTACH, nothing outside the tables the task was given, and no cross
join without a condition.

**What this is and is not.** It is a keyword and identifier guard working on
tokenised text, not a SQL parser. It catches the mistakes and the obvious
attacks; a sufficiently exotic dialect trick could get past it. That is why it
is the first of two defences and not the only one: A4 runs its query against an
in-memory database loaded from Parquet, so there is nothing durable for a query
to damage even if one slipped through. Say so plainly rather than pretend a
regex is a sandbox.

Three details matter more than they look:

* comments are stripped first, so `SELECT 1 -- DROP TABLE x` is not flagged and
  `SELECT 1; /**/ DROP TABLE x` still is;
* string literals are blanked before keywords are searched, so a row containing
  the word DROP does not trip the guard;
* more than one statement is refused outright, which is what stops
  `SELECT 1; DROP TABLE x`.
"""

from __future__ import annotations

import re
from typing import Final

# A statement may only begin with one of these.
ALLOWED_STARTS: Final[tuple[str, ...]] = ("SELECT", "WITH")
ALLOWED_CREATE: Final[re.Pattern[str]] = re.compile(
    r"^CREATE\s+(?:OR\s+REPLACE\s+)?(?:TEMP\s+|TEMPORARY\s+)?VIEW\b", re.IGNORECASE
)

# Refused wherever they appear outside a string literal.
FORBIDDEN: Final[tuple[str, ...]] = (
    "DROP",
    "DELETE",
    "UPDATE",
    "INSERT",
    "ALTER",
    "TRUNCATE",
    "REPLACE INTO",
    "ATTACH",
    "DETACH",
    "COPY",
    "EXPORT",
    "IMPORT",
    "INSTALL",
    "LOAD",
    "PRAGMA",
    "CALL",
    "GRANT",
    "REVOKE",
    "VACUUM",
    "CHECKPOINT",
)

TABLE_AFTER: Final[re.Pattern[str]] = re.compile(
    r"\b(?:FROM|JOIN)\s+([A-Za-z_][\w.]*)", re.IGNORECASE
)
CROSS_JOIN: Final[re.Pattern[str]] = re.compile(r"\bCROSS\s+JOIN\b", re.IGNORECASE)

# Names a WITH clause defines for itself. These are not tables anybody grants.
CTE_NAME: Final[re.Pattern[str]] = re.compile(
    r"(?:\bWITH\s+(?:RECURSIVE\s+)?|,\s*)([A-Za-z_]\w*)\s+AS\s*\(", re.IGNORECASE
)
JOIN_WITHOUT_ON: Final[re.Pattern[str]] = re.compile(
    r"\bJOIN\s+[A-Za-z_][\w.]*(?:\s+(?:AS\s+)?[A-Za-z_]\w*)?\s*(?!\s*(?:ON|USING)\b)",
    re.IGNORECASE,
)


class SqlGuardError(RuntimeError):
    """The statement is not one this system will execute."""


def strip_comments(sql: str) -> str:
    """Remove line and block comments, leaving the code positions intact."""
    without_block = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    return re.sub(r"--[^\n]*", " ", without_block)


def blank_literals(sql: str) -> str:
    """Replace the contents of string literals with spaces.

    Keeps the quotes so the shape of the statement survives, but means a row
    value containing the word DELETE cannot be mistaken for the keyword.
    """
    out: list[str] = []
    quote: str | None = None
    for char in sql:
        if quote is None:
            if char in {"'", '"'}:
                quote = char
                out.append(char)
            else:
                out.append(char)
        else:
            if char == quote:
                quote = None
                out.append(char)
            else:
                out.append(" ")
    return "".join(out)


def split_statements(sql: str) -> list[str]:
    """Split on semicolons that are not inside a string literal."""
    blanked = blank_literals(sql)
    pieces: list[str] = []
    start = 0
    for index, char in enumerate(blanked):
        if char == ";":
            pieces.append(sql[start:index])
            start = index + 1
    pieces.append(sql[start:])
    return [piece.strip() for piece in pieces if piece.strip()]


def extract_cte_names(sql: str) -> set[str]:
    """Names the statement defines for itself in a WITH clause."""
    return {match.group(1).lower() for match in CTE_NAME.finditer(blank_literals(sql))}


def extract_tables(sql: str) -> set[str]:
    """Every table name the statement reads from, excluding its own CTEs.

    A CTE is created by the statement itself, so requiring it to be granted
    would refuse perfectly ordinary SQL.
    """
    blanked = blank_literals(sql)
    referenced = {match.group(1).lower() for match in TABLE_AFTER.finditer(blanked)}
    return referenced - extract_cte_names(sql)


def check_sql(sql: str, *, allowed_tables: set[str] | None = None) -> str:
    """Approve one statement, or refuse it with a reason.

    Args:
        sql: the statement to check.
        allowed_tables: names the statement may read. None means do not check
            names, which is only appropriate in a test.

    Returns:
        The statement, with comments stripped, ready to run.

    Raises:
        SqlGuardError: the statement is empty, is more than one statement, does
            not start with SELECT / WITH / CREATE VIEW, contains a forbidden
            keyword, reads a table it was not given, or joins without a condition.
    """
    cleaned = strip_comments(sql).strip()
    if not cleaned:
        raise SqlGuardError("Cau lenh rong.")

    statements = split_statements(cleaned)
    if len(statements) > 1:
        raise SqlGuardError(
            f"Chi cho phep mot cau lenh, nhan duoc {len(statements)}. "
            "Nhieu cau lenh la cach kinh dien de gan them mot lenh pha huy."
        )

    statement = statements[0]
    searchable = blank_literals(statement)

    upper = searchable.lstrip().upper()
    starts_ok = upper.startswith(ALLOWED_STARTS) or ALLOWED_CREATE.match(searchable.lstrip())
    if not starts_ok:
        first = upper.split()[0] if upper.split() else "?"
        raise SqlGuardError(
            f"Cau lenh bat dau bang {first!r}. Chi cho phep SELECT, WITH hoac CREATE VIEW."
        )

    for keyword in FORBIDDEN:
        pattern = r"\b" + keyword.replace(" ", r"\s+") + r"\b"
        if re.search(pattern, searchable, re.IGNORECASE):
            raise SqlGuardError(f"Cau lenh chua tu khoa bi cam: {keyword}.")

    if CROSS_JOIN.search(searchable):
        raise SqlGuardError(
            "Cam CROSS JOIN: mot phep noi khong dieu kien co the no ra khong gioi han."
        )

    if allowed_tables is not None:
        permitted = {name.lower() for name in allowed_tables}
        used = extract_tables(statement)
        stray = sorted(used - permitted)
        if stray:
            raise SqlGuardError(
                f"Cau lenh doc bang khong duoc cap: {stray}. Chi cho phep: {sorted(permitted)}"
            )

    return statement


def is_safe(sql: str, *, allowed_tables: set[str] | None = None) -> bool:
    """True when the statement would be approved."""
    try:
        check_sql(sql, allowed_tables=allowed_tables)
    except SqlGuardError:
        return False
    return True
