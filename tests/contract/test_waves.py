"""Chay song song: nhanh hon, va khong doi mot quyet dinh nao.

Hai tinh chat gan lien nhau o day. Mot dot chi chua nhung task khong task nao
doc ket qua cua task nao - do la thu khien viec chay chong len nhau la an toan.
Va moi quyet dinh van duoc xu ly theo THU TU TASK chu khong theo thu tu ket
thuc, vi tieu chi S1 doi hai lan chay cung mot ke hoach phai di den cung mot
trinh tu.
"""

from __future__ import annotations

import pytest

from analysis_system.manager.planner import PlanError, ordered_tasks, waves
from analysis_system.models.agents import Plan


def plan_of(tasks: list[dict[str, object]]) -> Plan:
    return Plan.model_validate({"tasks": tasks})


CHAIN = plan_of(
    [
        {"task_id": "t1", "agent_id": "a4_transformer", "instruction": "them cot"},
        {
            "task_id": "t2",
            "agent_id": "a7_analyst",
            "instruction": "phan tich",
            "depends_on": ["t1"],
        },
    ]
)

FORK = plan_of(
    [
        {"task_id": "t_fear", "agent_id": "a10_text_miner", "instruction": "nhom fear"},
        {"task_id": "t_sadness", "agent_id": "a10_text_miner", "instruction": "nhom sadness"},
        {
            "task_id": "t_answer",
            "agent_id": "a9_manager",
            "instruction": "tong hop",
            "depends_on": ["t_fear", "t_sadness"],
        },
    ]
)


# --- cai gi duoc chay cung luc ----------------------------------------------------


def test_two_tasks_that_share_nothing_are_one_wave() -> None:
    # Asked which words characterise sadness and which characterise fear, the
    # Manager plans two tasks with nothing in common - and they ran one after
    # the other because the runner only knew how to walk a list.
    grouped = [[task.task_id for task in wave] for wave in waves(FORK)]
    assert grouped == [["t_fear", "t_sadness"], ["t_answer"]]


def test_a_chain_is_one_task_per_wave() -> None:
    # Nothing here may overlap: t2 reads what t1 built.
    grouped = [[task.task_id for task in wave] for wave in waves(CHAIN)]
    assert grouped == [["t1"], ["t2"]]


def test_no_task_in_a_wave_depends_on_another_in_it() -> None:
    # The property the whole thing rests on, stated directly.
    for wave in waves(FORK):
        names = {task.task_id for task in wave}
        for task in wave:
            assert not names & set(task.depends_on)


# --- va thu tu thi khong doi -------------------------------------------------------


def test_flattening_the_waves_gives_back_the_old_order() -> None:
    # Criterion S1: the sequence tasks are considered in must not change just
    # because some of them now run at the same time.
    for plan in (CHAIN, FORK):
        flat = [task.task_id for wave in waves(plan) for task in wave]
        assert flat == [task.task_id for task in ordered_tasks(plan)]


def test_each_wave_is_sorted_by_id() -> None:
    # Two runs of the same plan must consider the same task first.
    grouped = waves(FORK)
    for wave in grouped:
        assert [task.task_id for task in wave] == sorted(task.task_id for task in wave)


def test_a_cycle_is_refused_here_too() -> None:
    # The same refusal as the sequential walk, for the same reason: no order
    # exists, so there is nothing to run.
    looped = plan_of(
        [
            {
                "task_id": "t1",
                "agent_id": "a7_analyst",
                "instruction": "x",
                "depends_on": ["t2"],
            },
            {
                "task_id": "t2",
                "agent_id": "a7_analyst",
                "instruction": "y",
                "depends_on": ["t1"],
            },
        ]
    )
    with pytest.raises(PlanError) as refused:
        waves(looped)
    assert "chu trinh" in str(refused.value)


def test_an_empty_plan_has_no_waves() -> None:
    assert waves(plan_of([])) == []
