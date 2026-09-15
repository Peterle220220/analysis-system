"""Mot nhom mo ta bang nhieu dieu kien phai duoc LOC bang WHERE ghep AND.

Luot 3.2 that: "co bao nhieu cong ty song sot nhung loi nhuan am, trung binh ty le
no cua nhom nay". Prompt Planner ghi "lenh cho a4 LUON la them cot, giu nguyen so
dong", nen ke hoach them mot cot co roi giu 6.819 dong: khong tinh duoc so luong
lan trung binh cua nhom. Va nhom ay rong: cot loi nhuan da chuan hoa ve 0 den 1,
khong co gia tri am nao - cau tra loi dung la 0, kem ly do.
"""

from __future__ import annotations

import pandas as pd

from analysis_system.domains.ai_planner.prompts import load_prompt
from analysis_system.domains.execution_engine.data_scope import (
    DataScope,
    empty_note,
    parse_recipe,
    scope_sentence,
)
from analysis_system.domains.execution_engine.thresholds import flag_instead_of_filter

QUESTION = (
    "Có bao nhiêu công ty sống sót (không phá sản) nhưng lại có lợi nhuận ròng/tổng tài sản "
    "âm (nhỏ hơn 0)? Trung bình tỷ lệ nợ của nhóm công ty cá biệt này là bao nhiêu?"
)
FLAG_SQL = (
    'SELECT *, CASE WHEN "trang_thai" = 0 AND "loi_nhuan" < 0 THEN 1 ELSE 0 END AS ca_biet '
    "FROM bang"
)
FILTER_SQL = 'SELECT * FROM bang WHERE "trang_thai" = 0 AND "loi_nhuan" < 0'


# --- cot co thay cho loc -------------------------------------------------------------


def test_a_flag_for_one_described_group_is_sent_back() -> None:
    said = flag_instead_of_filter(QUESTION, FLAG_SQL, 6819, 6819)
    assert "WHERE" in said
    assert "AND" in said


def test_a_real_filter_passes() -> None:
    assert flag_instead_of_filter(QUESTION, FILTER_SQL, 6819, 0) == ""


def test_a_comparison_between_groups_may_keep_a_flag() -> None:
    question = "So sánh tỷ lệ nợ giữa nhóm lợi nhuận nhỏ hơn 0 và nhóm còn lại"
    assert flag_instead_of_filter(question, FLAG_SQL, 10, 10) == ""


def test_a_question_without_a_condition_is_left_alone() -> None:
    assert flag_instead_of_filter("Tính thêm cột tỷ lệ lợi nhuận", FLAG_SQL, 10, 10) == ""


def test_a_table_that_already_lost_rows_is_not_this_problem() -> None:
    assert flag_instead_of_filter(QUESTION, FLAG_SQL, 10, 5) == ""


def test_a_new_column_without_a_flag_is_not_this_problem() -> None:
    sql = "SELECT *, loi_nhuan / tai_san AS ty_le FROM bang"
    assert flag_instead_of_filter(QUESTION, sql, 10, 10) == ""


# --- loc ra 0 dong: noi vi sao ----------------------------------------------------------

TABLES = {
    "bang": pd.DataFrame(
        {"trang_thai": [0, 1, 0], "loi_nhuan": [0.2, 0.5, 1.0], "ten": ["a", "b", "c"]}
    )
}


def test_an_empty_filter_explains_itself_with_real_ranges() -> None:
    lines = empty_note(FILTER_SQL, TABLES, 0)
    assert lines[0] == "-- ghi chu: Không có dòng nào thỏa điều kiện lọc."
    assert '-- ghi chu: Cột "loi_nhuan" trong dữ liệu chỉ nằm từ 0.2 đến 1.' in lines
    assert '-- ghi chu: Cột "trang_thai" trong dữ liệu chỉ nằm từ 0 đến 1.' in lines
    assert not any('"ten"' in line for line in lines)  # cot chu khong co khoang so


def test_a_filter_that_found_rows_needs_no_note() -> None:
    assert empty_note(FILTER_SQL, TABLES, 2) == []


def test_the_note_travels_to_the_scope_and_the_sentence() -> None:
    recipe = "\n".join(
        [
            "-- 6819 dong vao",
            "-- 0 dong ra",
            *empty_note(FILTER_SQL, TABLES, 0),
            "",
            FILTER_SQL,
        ]
    )
    scope = parse_recipe(recipe)
    assert scope is not None
    assert scope.rows == 0
    assert len(scope.notes) == 3
    said = scope_sentence(scope)
    assert "câu trả lời cho 'có bao nhiêu' là 0" in said
    assert "chỉ nằm từ 0.2 đến 1" in said


def test_the_sentence_points_to_the_row_count() -> None:
    said = scope_sentence(DataScope(rows=381, total=6819, condition="x > 0.2"))
    assert "rows.total" in said
    assert "là 0" not in said


# --- prompt khong con ep them cot co --------------------------------------------------


def test_the_planner_prompt_no_longer_forces_a_flag() -> None:
    text = load_prompt("manager_plan")
    assert "luôn là **" not in text
    assert "Lọc ra MỘT nhóm bằng `WHERE`" in text
    assert "`AND`" in text


def test_the_transformer_prompt_allows_a_where_filter() -> None:
    assert "Lọc bằng `WHERE` thì được" in load_prompt("a4_transformer_sql")
