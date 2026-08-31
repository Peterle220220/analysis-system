"""SQL guard tests: what it must let through, and what it must never let through."""

from __future__ import annotations

import pytest

from analysis_system.services.sql_guard import (
    SqlGuardError,
    blank_literals,
    check_sql,
    extract_cte_names,
    extract_tables,
    is_safe,
    split_statements,
    strip_comments,
)

TABLES = {"events", "vendors"}


def approve(sql: str) -> str:
    return check_sql(sql, allowed_tables=TABLES)


# --- what must be allowed -----------------------------------------------------


def test_a_plain_select_is_allowed() -> None:
    approve("SELECT case_id, activity FROM events")


def test_a_common_table_expression_is_allowed() -> None:
    approve("WITH recent AS (SELECT * FROM events) SELECT count(*) FROM recent")


def test_creating_a_view_is_allowed() -> None:
    approve("CREATE VIEW summary AS SELECT case_id FROM events")
    approve("CREATE OR REPLACE TEMP VIEW summary AS SELECT case_id FROM events")


def test_a_join_with_a_condition_is_allowed() -> None:
    approve("SELECT e.case_id FROM events e JOIN vendors v ON e.vendor = v.id")


def test_an_aggregate_is_allowed() -> None:
    approve("SELECT activity, count(*) AS n FROM events GROUP BY activity ORDER BY n DESC")


# --- what must never be allowed -----------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE events",
        "DELETE FROM events",
        "UPDATE events SET price = 0",
        "INSERT INTO events VALUES (1)",
        "ALTER TABLE events ADD COLUMN x INT",
        "TRUNCATE events",
        "ATTACH 'other.db' AS other",
        "COPY events TO 'out.csv'",
        "INSTALL httpfs",
        "LOAD httpfs",
        "PRAGMA database_list",
    ],
)
def test_a_destructive_statement_is_refused(sql: str) -> None:
    assert not is_safe(sql, allowed_tables=TABLES)


def test_a_second_statement_smuggled_after_a_select_is_refused() -> None:
    # The classic shape: something harmless, a semicolon, then the real payload.
    with pytest.raises(SqlGuardError, match="mot cau lenh"):
        approve("SELECT 1 FROM events; DROP TABLE events")


def test_a_payload_hidden_behind_a_block_comment_is_still_refused() -> None:
    with pytest.raises(SqlGuardError):
        approve("SELECT 1 FROM events; /* nothing to see */ DROP TABLE events")


def test_a_cross_join_is_refused() -> None:
    with pytest.raises(SqlGuardError, match="CROSS JOIN"):
        approve("SELECT * FROM events CROSS JOIN vendors")


def test_reading_a_table_the_task_did_not_grant_is_refused() -> None:
    with pytest.raises(SqlGuardError, match="khong duoc cap"):
        approve("SELECT * FROM secrets")


def test_an_empty_statement_is_refused() -> None:
    with pytest.raises(SqlGuardError, match="rong"):
        approve("   ")


def test_a_statement_starting_with_something_else_is_refused() -> None:
    with pytest.raises(SqlGuardError, match="SELECT, WITH hoac CREATE VIEW"):
        approve("EXPLAIN SELECT * FROM events")


def test_creating_a_table_is_not_creating_a_view() -> None:
    with pytest.raises(SqlGuardError):
        approve("CREATE TABLE t AS SELECT * FROM events")


# --- the parts that make the checks trustworthy -------------------------------


def test_a_comment_is_not_mistaken_for_code() -> None:
    # Otherwise every query with a note in it would be refused.
    approve("SELECT case_id FROM events -- DROP TABLE events")
    assert "DROP" not in strip_comments("SELECT 1 -- DROP TABLE x")


def test_a_string_literal_is_not_mistaken_for_a_keyword() -> None:
    # A row value containing the word DELETE must not trip the guard.
    approve("SELECT * FROM events WHERE activity = 'DELETE Purchase Order Item'")


def test_blanking_keeps_the_shape_but_removes_the_contents() -> None:
    assert blank_literals("a = 'DROP'") == "a = '    '"


def test_a_semicolon_inside_a_literal_does_not_split_the_statement() -> None:
    assert len(split_statements("SELECT * FROM events WHERE note = 'a;b'")) == 1


def test_table_names_are_found_after_from_and_join() -> None:
    found = extract_tables("SELECT * FROM events e JOIN vendors v ON e.v = v.id")
    assert found == {"events", "vendors"}


def test_a_cte_defines_its_own_name() -> None:
    assert extract_cte_names("WITH recent AS (SELECT 1) SELECT * FROM recent") == {"recent"}


def test_several_ctes_are_all_recognised() -> None:
    sql = "WITH a AS (SELECT 1), b AS (SELECT 2) SELECT * FROM a JOIN b ON 1=1"
    assert extract_cte_names(sql) == {"a", "b"}


def test_a_cte_does_not_have_to_be_granted() -> None:
    approve("WITH recent AS (SELECT * FROM events) SELECT count(*) FROM recent")


def test_a_cte_name_does_not_smuggle_in_a_real_table() -> None:
    # Naming a CTE after a table you were not granted must not grant it.
    with pytest.raises(SqlGuardError, match="khong duoc cap"):
        approve("WITH x AS (SELECT * FROM secrets) SELECT * FROM x")


def test_names_are_compared_without_regard_to_case() -> None:
    check_sql("SELECT * FROM EVENTS", allowed_tables={"events"})


def test_the_approved_statement_comes_back_without_comments() -> None:
    cleaned = approve("SELECT 1 FROM events -- ghi chu")
    assert "ghi chu" not in cleaned
