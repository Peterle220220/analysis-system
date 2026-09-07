"""Boi canh cua bo du lieu: nguoi viet, khong phai may doan.

De xuat ban dau la de Planner DOAN linh vuc roi gan vai "ban la chuyen gia
$DOMAIN". Bi bac vi do la mot nhan ma code khong doi chieu duoc voi gi ca -
trong khi ca he thong nay dung tren dung mot luat: moi thu model quyet deu phai
kiem lai duoc.
"""

from __future__ import annotations

from pathlib import Path

from analysis_system.contracts.agents import Plan, PlannedTask
from analysis_system.manager.planner import CONTEXT_PARAM, with_context
from analysis_system.services.dataset_context import MAX_LENGTH, read_context, write_context


def a_plan() -> Plan:
    return Plan(
        reason="thu",
        tasks=(
            PlannedTask(task_id="t1", agent_id="a4_transformer", instruction="dung bang"),
            PlannedTask(
                task_id="t2", agent_id="a7_analyst", instruction="phan tich", depends_on=("t1",)
            ),
        ),
    )


# --- luu va doc --------------------------------------------------------------------


def test_context_survives_a_round_trip(tmp_path: Path) -> None:
    write_context(tmp_path, "Khảo sát 40 nhà đầu tư cá nhân năm 2023.")
    assert read_context(tmp_path) == "Khảo sát 40 nhà đầu tư cá nhân năm 2023."


def test_a_dataset_with_no_context_reads_empty(tmp_path: Path) -> None:
    # Khong co boi canh khong phai la mot loai boi canh.
    assert read_context(tmp_path / "chua_co") == ""


def test_line_breaks_are_folded_into_one_line(tmp_path: Path) -> None:
    # No di vao mot khoi JSON; xuong dong lung tung chi lam prompt kho doc.
    write_context(tmp_path, "Dòng một\n\n   Dòng hai")
    assert read_context(tmp_path) == "Dòng một Dòng hai"


def test_a_very_long_context_is_cut(tmp_path: Path) -> None:
    # Mot tai lieu dan vao moi prompt la mot cach dot ngan sach token ma khong
    # ai de y.
    kept = write_context(tmp_path, "x" * (MAX_LENGTH + 500))
    assert len(kept) == MAX_LENGTH
    assert len(read_context(tmp_path)) == MAX_LENGTH


def test_writing_nothing_clears_it(tmp_path: Path) -> None:
    write_context(tmp_path, "cũ")
    write_context(tmp_path, "")
    assert read_context(tmp_path) == ""


# --- di theo ke hoach --------------------------------------------------------------


def test_the_context_reaches_every_step_not_just_the_last() -> None:
    """Buoc phan tich can boi canh y nhu buoc tong hop.

    Mot con so chi co nghia khi biet no do cai gi.
    """
    planned = with_context(a_plan(), "Khảo sát nhà đầu tư cá nhân")

    for task in planned.tasks:
        assert task.params[CONTEXT_PARAM] == "Khảo sát nhà đầu tư cá nhân"


def test_an_empty_context_leaves_the_plan_untouched() -> None:
    plan = a_plan()
    assert with_context(plan, "   ") == plan


def test_the_context_does_not_overwrite_other_params() -> None:
    plan = Plan(
        reason="thu",
        tasks=(
            PlannedTask(
                task_id="t1",
                agent_id="a7_analyst",
                instruction="phan tich",
                params={"question": "Tỷ lệ nam nữ?"},
            ),
        ),
    )

    planned = with_context(plan, "bối cảnh")

    assert planned.tasks[0].params["question"] == "Tỷ lệ nam nữ?"
    assert planned.tasks[0].params[CONTEXT_PARAM] == "bối cảnh"
