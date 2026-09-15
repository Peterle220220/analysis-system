"""Khong hoi ve moi quan he thi khong do tuong quan; cau hoi tieng Anh doc duoc nhu tieng Viet."""

from __future__ import annotations

import pandas as pd
import pytest

from analysis_system.domains.ai_planner.answer_shape import Demand, read_question, satisfied_by
from analysis_system.domains.execution_engine.statistics import (
    NO_RELATIONSHIP,
    StatisticsSpec,
    asks_relationship,
    suggest_spec,
    without_relationships,
)

NUMBERS = pd.DataFrame(
    {
        "doanh_thu": [3, 1, 4, 1, 5, 9, 2, 6, 5, 3, 5, 8, 9, 7, 9, 3, 2, 3, 8, 4],
        "chi_phi": [2, 7, 1, 8, 2, 8, 1, 8, 2, 8, 4, 5, 9, 0, 4, 5, 2, 3, 5, 3],
        "loi_nhuan": [1, 4, 1, 4, 2, 1, 3, 5, 6, 2, 3, 7, 3, 0, 9, 5, 0, 4, 8, 8],
    },
    dtype=float,
)


@pytest.mark.parametrize(
    "question",
    [
        "Mối quan hệ giữa doanh thu và chi phí?",
        "Doanh thu tương quan với lợi nhuận thế nào?",
        "Chi phí tác động ra sao tới lợi nhuận?",
        "What is the relationship between revenue and cost?",
        "How does cost impact profit?",
    ],
)
def test_relationship_questions_still_measure_correlations(question: str) -> None:
    assert asks_relationship(question)
    spec, notes = suggest_spec(NUMBERS, question=question)
    assert spec.correlations
    assert NO_RELATIONSHIP not in notes


@pytest.mark.parametrize(
    "question",
    [
        "So sánh doanh thu giữa quý 2 và quý 1, chênh lệch bao nhiêu?",
        "Tổng doanh thu là bao nhiêu?",
        "Dữ liệu này có gì đáng chú ý?",
        "Compare revenue between North and South",
    ],
)
def test_other_questions_do_not_trawl_for_correlations(question: str) -> None:
    spec, notes = suggest_spec(NUMBERS, question=question)
    assert not spec.correlations
    assert NO_RELATIONSHIP in notes


def test_declared_correlations_are_dropped_too_and_said_so() -> None:
    declared = StatisticsSpec(
        correlations=(("doanh_thu", "chi_phi"),),
        regressions=(("loi_nhuan", ("doanh_thu",)),),
    )
    kept, notes = without_relationships(declared, "Tổng doanh thu bao nhiêu?")
    assert kept.correlations == ()
    assert kept.regressions == ()
    assert notes == [NO_RELATIONSHIP]
    # Goi bang code, khong co cau hoi: giu nguyen.
    assert without_relationships(declared, "") == (declared, [])


@pytest.mark.parametrize(
    ("question", "demand"),
    [
        ("Compare revenue between North and South", Demand.COMPARISON),
        ("How much did revenue increase from Q1 to Q2?", Demand.COMPARISON),
        ("Lợi nhuận quý 2 tăng bao nhiêu so với quý 1?", Demand.COMPARISON),
        ("Why did sales drop?", Demand.CAUSE),
        ("Which region has the highest revenue?", Demand.RANKING),
        ("How many customers are there?", Demand.QUANTITY),
        ("Show the revenue trend over time", Demand.TREND),
    ],
)
def test_english_questions_are_read_like_vietnamese_ones(question: str, demand: Demand) -> None:
    assert read_question(question) is demand


def test_a_point_value_and_a_change_answer_the_questions_that_ask_for_them() -> None:
    assert satisfied_by(Demand.QUANTITY, ["Giá trị (LNST).value.by.Kỳ.Q2-2026"]).met
    assert satisfied_by(Demand.TREND, ["Giá trị (LNST).change.by.Kỳ.Q2-2026"]).met
    assert satisfied_by(Demand.COMPARISON, ["Giá trị (LNST).change.by.Kỳ.Q2-2026"]).met
