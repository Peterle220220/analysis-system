"""Pham vi du lieu: moi con so do tren tap nao, doc tu chinh cau SQL da dung bang.

Loi goc (cap do 3): SQL loc dung "> 0.2", con 381 tren 6.819 dong. Model khong
duoc bao dieu do, nen goi trung binh cua tap loc la "trung binh chung" va gan ty
le pha san cua 381 dong cho "toan bo du lieu".
"""

from __future__ import annotations

from analysis_system.agents.a7_analyst import build_analysis_request
from analysis_system.agents.a9_manager import build_answer_request
from analysis_system.core.boundary import BoundaryViolation
from analysis_system.domains.execution_engine.data_scope import (
    DataScope,
    parse_recipe,
    read_scope,
    recipe_of,
    scope_sentence,
    scope_text,
    shown_condition,
)

RECIPE = (
    "-- run: r   task: t1\n-- nguon: bang\n-- 6819 dong vao\n-- 381 dong ra\n\n"
    'SELECT * FROM bang WHERE "Debt Share %" > 0.2\n'
)


# --- doc tep SQL ------------------------------------------------------------------


def test_the_recipe_gives_rows_total_and_condition() -> None:
    assert parse_recipe(RECIPE) == DataScope(rows=381, total=6819, condition='"Debt Share %" > 0.2')


def test_an_older_recipe_without_rows_in_still_reads() -> None:
    old = '-- 381 dong ra\n\nSELECT * FROM bang WHERE "Debt Share %" > 0.2'
    assert parse_recipe(old) == DataScope(rows=381, total=None, condition='"Debt Share %" > 0.2')


def test_a_table_that_was_not_filtered_has_no_scope() -> None:
    assert parse_recipe("-- 40 dong ra\n\nSELECT a, CAST(b AS DOUBLE) AS b FROM t") is None


def test_the_condition_stops_before_the_next_clause() -> None:
    text = "-- 3 dong ra\n\nSELECT a, AVG(b) FROM t WHERE c > 1 GROUP BY a ORDER BY a"
    assert parse_recipe(text) == DataScope(rows=3, total=None, condition="c > 1")


def test_the_recipe_sits_beside_its_table() -> None:
    assert recipe_of("mart://r_t1_loc.parquet") == "mart://r_t1_loc.sql"


def test_the_scope_is_read_through_the_agents_own_reader() -> None:
    read: list[str] = []

    def load_text(uri: str) -> str:
        read.append(uri)
        return RECIPE

    assert read_scope(load_text, "mart://r_t1_loc.parquet") == parse_recipe(RECIPE)
    assert read == ["mart://r_t1_loc.sql"]


def test_a_recipe_outside_the_granted_scope_means_no_scope() -> None:
    def refuse(uri: str) -> str:
        raise BoundaryViolation(uri)

    assert read_scope(refuse, "mart://r_t1_loc.parquet") is None


def test_only_mart_tables_have_a_recipe() -> None:
    assert read_scope(lambda _uri: RECIPE, "clean://bang.parquet") is None


# --- cau noi pham vi ----------------------------------------------------------------


def test_the_sentence_says_rows_total_condition_and_not_everything() -> None:
    said = scope_sentence(DataScope(rows=381, total=6819, condition='"Debt Share %" > 0.2'))
    assert "381 dòng" in said
    assert "6819" in said
    assert '"Debt Share %" > 0.2' in said
    assert "KHÔNG phải toàn bộ dữ liệu" in said


def test_no_filter_no_sentence() -> None:
    assert scope_text(lambda _uri: "-- 4 dong ra\n\nSELECT * FROM t", "mart://x.parquet") == ""


def test_the_reader_sees_the_condition_without_quotes() -> None:
    assert shown_condition('"Debt Share %" > 0.2') == "Debt Share % > 0.2"


# --- ca hai nguoi viet deu duoc bao pham vi ----------------------------------------------


def test_the_analyst_is_told_the_scope() -> None:
    request = build_analysis_request([], "câu hỏi", 5, scope="PHAM VI 381 DONG")
    assert "pham_vi_du_lieu" in request.prompt
    assert "PHAM VI 381 DONG" in request.prompt


def test_without_a_filter_the_analyst_prompt_is_unchanged() -> None:
    assert "pham_vi_du_lieu" not in build_analysis_request([], "câu hỏi", 5).prompt


def test_the_manager_is_told_the_scope() -> None:
    request = build_answer_request("câu hỏi", [], [], [], scope="PHAM VI 381 DONG")
    assert "PHAM VI 381 DONG" in request.prompt
