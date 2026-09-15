"""Boi canh cua bo du lieu: nguoi viet, khong phai may doan.

De xuat ban dau la de Planner DOAN linh vuc roi gan vai "ban la chuyen gia
$DOMAIN". Bi bac vi do la mot nhan ma code khong doi chieu duoc voi gi ca -
trong khi ca he thong nay dung tren dung mot luat: moi thu model quyet deu phai
kiem lai duoc.
"""

from __future__ import annotations

from pathlib import Path

from analysis_system.domains.ai_planner.asked_columns import ASKED_PARAM
from analysis_system.domains.data_ingestion.dataset_context import (
    MAX_LENGTH,
    read_context,
    write_context,
)
from analysis_system.domains.data_ingestion.glossary_store import GLOSSARY_PARAM
from analysis_system.manager.planner import (
    CONTEXT_PARAM,
    with_asked,
    with_context,
    with_glossary,
)
from analysis_system.models.agents import Plan, PlannedTask


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


def test_line_breaks_are_kept_but_blank_lines_are_not(tmp_path: Path) -> None:
    """Truoc day o day gop CA O thanh mot dong, va ly do ghi la "no di vao mot
    khoi JSON; xuong dong lung tung chi lam prompt kho doc".

    Ly do do viet TRUOC khi co bang chu giai. Bang chu giai doc theo tung dong,
    nen gop dong lai la giet no - va da giet that: chu he thong khai du sau cot
    theo dung mau trang huong dan, he thong doc ra con so khong, va khong co
    dau hieu nao cho thay hong.

    JSON thi khong ngai xuong dong; no tu thoat ky tu. Nen giu dong, va chi bo
    dong trong - the la ca hai moi lo deu duoc.
    """
    write_context(tmp_path, "Dòng một\n\n   Dòng hai")
    assert read_context(tmp_path) == "Dòng một\nDòng hai"


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


# --- xuong dong phai song sot -------------------------------------------------


def test_the_line_breaks_survive(tmp_path: Path) -> None:
    """Bang chu giai doc theo TUNG DONG. Gop ca o thanh mot dong thi no chet.

    Da xay ra that: chu he thong khai du sau cot theo dung mau trang huong dan,
    va he thong doc ra con so khong. Hong ma im lang - o Boi canh van hien lai
    dung chu ho go, vi trinh duyet tu xuong dong theo be ngang.
    """
    text = "Dong mot.\ny = Ket qua\njob = Nghe nghiep"
    write_context(tmp_path, text)
    assert len(read_context(tmp_path).splitlines()) == 3


def test_the_glossary_can_be_read_back(tmp_path: Path) -> None:
    from analysis_system.domains.ai_planner.asked_columns import parse_glossary

    write_context(tmp_path, "Khao sat ngan hang.\ny = Ket qua\njob = Nghe nghiep")
    assert sorted(parse_glossary(read_context(tmp_path))) == ["job", "y"]


def test_stray_spacing_inside_a_line_is_still_tidied(tmp_path: Path) -> None:
    write_context(tmp_path, "y   =    Ket   qua\n\n\njob = Nghe nghiep")
    kept = read_context(tmp_path)
    assert "y = Ket qua" in kept
    assert "   " not in kept


# --- bang chu giai di theo tham so rieng --------------------------------------


def test_every_step_gets_the_glossary_too() -> None:
    planned = with_glossary(a_plan(), "Debt ratio % = tỷ lệ nợ")
    for task in planned.tasks:
        assert task.params[GLOSSARY_PARAM] == "Debt ratio % = tỷ lệ nợ"


def test_no_glossary_leaves_the_plan_untouched() -> None:
    plan = a_plan()
    assert with_glossary(plan, "   ") == plan


# --- cau hoi goc di toi moi buoc -------------------------------------------------


def test_every_step_gets_the_original_question() -> None:
    planned = with_asked(a_plan(), "So sánh biên lợi nhuận gộp giữa hai nhóm")
    for task in planned.tasks:
        assert task.params[ASKED_PARAM] == "So sánh biên lợi nhuận gộp giữa hai nhóm"


def test_the_original_question_does_not_replace_a_step_instruction() -> None:
    plan = a_plan()
    planned = with_asked(plan, "câu hỏi")
    assert [task.instruction for task in planned.tasks] == [task.instruction for task in plan.tasks]


def test_no_question_leaves_the_plan_untouched() -> None:
    plan = a_plan()
    assert with_asked(plan, "  ") == plan
