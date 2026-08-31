"""Runs approved SQL against an in-memory database, and nothing else.

This is the second of the two defences around model-written SQL. The first is
the guard, which reads the statement and refuses the obvious. This one is
structural: the tables live in a DuckDB instance created for this one query and
thrown away afterwards, populated from frames the caller already holds. There is
no file for a query to damage, no other schema to reach, and nothing that
survives the call - so even a statement that slipped past the guard has nothing
durable to destroy.

A query is also refused if it returns more rows than the task allows. A join
written without thinking is the usual way a mart goes from thousands of rows to
billions, and finding out by filling the disk is the wrong way to find out.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Final

import duckdb
import pandas as pd

from analysis_system.services.sql_guard import SqlGuardError, check_sql

DEFAULT_MAX_ROWS: Final[int] = 50_000_000

# Output larger than this multiple of the biggest input is treated as a join
# that lost control, and reported even when it stays under the hard ceiling.
EXPLOSION_FACTOR: Final[int] = 10


class SqlRunError(RuntimeError):
    """The statement could not be executed, or produced too much."""


@dataclass(frozen=True)
class QueryOutcome:
    """What one query produced, and what it cost to produce it."""

    frame: pd.DataFrame
    sql: str
    rows_in: dict[str, int]
    rows_out: int
    duration_s: float
    exploded: bool
    note: str = ""


def run_query(
    sql: str,
    tables: dict[str, pd.DataFrame],
    *,
    max_rows: int = DEFAULT_MAX_ROWS,
) -> QueryOutcome:
    """Check a statement, run it over the given tables, and return the result.

    Args:
        sql: the statement to run. It is passed through the guard first.
        tables: name to frame. Only these names may be read.
        max_rows: refuse a result larger than this.

    Returns:
        The result frame and the measurements around it.

    Raises:
        SqlGuardError: the guard refused the statement.
        SqlRunError: the database rejected it, or it produced too many rows.
    """
    approved = check_sql(sql, allowed_tables=set(tables))
    rows_in = {name: int(len(frame.index)) for name, frame in tables.items()}

    started = time.monotonic()
    connection = duckdb.connect()
    try:
        for name, frame in tables.items():
            connection.register(name, frame)
        try:
            result = connection.execute(approved).fetch_df()
        except duckdb.Error as error:
            raise SqlRunError(f"DuckDB tu choi cau lenh: {error}") from error
    finally:
        connection.close()
    duration = time.monotonic() - started

    rows_out = int(len(result.index))
    if rows_out > max_rows:
        raise SqlRunError(
            f"Ket qua {rows_out:,} dong, vuot tran {max_rows:,}. "
            "Rat co the mot phep join thieu dieu kien."
        )

    largest = max(rows_in.values(), default=0)
    exploded = largest > 0 and rows_out > largest * EXPLOSION_FACTOR
    note = (
        f"Ket qua {rows_out:,} dong tu bang lon nhat {largest:,} dong "
        f"- gap hon {EXPLOSION_FACTOR} lan, nen kiem lai dieu kien join."
        if exploded
        else ""
    )

    return QueryOutcome(
        frame=result,
        sql=approved,
        rows_in=rows_in,
        rows_out=rows_out,
        duration_s=round(duration, 4),
        exploded=exploded,
        note=note,
    )


def table_name_for(uri: str) -> str:
    """The table name a data reference is registered under.

    clean://events.parquet becomes events, which is what the model is shown and
    what the guard checks against.
    """
    stem = uri.rsplit("/", 1)[-1]
    return stem.rsplit(".", 1)[0] or "table"


def describe_tables(tables: dict[str, pd.DataFrame]) -> dict[str, dict[str, object]]:
    """Schema and size of each table, for the prompt.

    Column names and types only. The model writes SQL against a shape; it has no
    reason to see a single row to do that.
    """
    return {
        name: {
            "rows": int(len(frame.index)),
            "columns": [
                {"name": str(column), "dtype": str(frame[column].dtype)} for column in frame.columns
            ],
        }
        for name, frame in tables.items()
    }


__all__ = [
    "DEFAULT_MAX_ROWS",
    "EXPLOSION_FACTOR",
    "QueryOutcome",
    "SqlGuardError",
    "SqlRunError",
    "describe_tables",
    "run_query",
    "table_name_for",
]
