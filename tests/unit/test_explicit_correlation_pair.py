"""Hoi dich danh mot cap tuong quan thi do dung cap do.

Bai 3.3 (bankruptcy__q5, 2026-09-13): "trong nhom pha san, ty le no va bien loi
nhuan gop co he so tuong quan la bao nhieu". Cap duoc hoi yeu; tam cap "ty le no
voi X" va "bien loi nhuan gop voi Y" gan +-1 chiem het tran tam phep kiem, va cau
tra loi bao cao nhung cap khong ai hoi. Bang duoi dung lai dung hinh dang do.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analysis_system.domains.execution_engine.statistics import (
    MAX_SUGGESTED,
    asks_correlation,
    compute_statistics,
    suggest_spec,
)

DEBT = "Debt ratio %"
MARGIN = "Operating Gross Margin"
GLOSSARY = f"{DEBT} = tỷ lệ nợ\n{MARGIN} = biên lợi nhuận gộp"


def bankrupt_like() -> pd.DataFrame:
    """Hai cot duoc hoi tuong quan yeu; moi cot co nhieu 'ban sao' tuong quan gan 1."""
    rng = np.random.default_rng(7)
    rows = 220
    debt = rng.normal(0.4, 0.1, rows)
    margin = 0.1 * debt + rng.normal(0.6, 0.05, rows)
    frame = {DEBT: debt, MARGIN: margin}
    for index in range(6):
        frame[f"Net worth {index}"] = 1 - debt + rng.normal(0, 0.001, rows)
        frame[f"Sales margin {index}"] = margin + rng.normal(0, 0.001, rows)
    return pd.DataFrame(frame)


ASKED = (
    "Chỉ xét riêng trong nhóm các công ty phá sản, tỷ lệ nợ và biên lợi nhuận gộp có "
    "hệ số tương quan là bao nhiêu? Chúng tỷ lệ thuận hay tỷ lệ nghịch?"
)


def test_a_named_pair_is_measured_and_nothing_else() -> None:
    spec, notes = suggest_spec(bankrupt_like(), question=ASKED, context=GLOSSARY)
    assert spec.correlations == ((DEBT, MARGIN),)
    assert any("đích danh" in note for note in notes)


def test_the_named_pair_becomes_a_metric_the_answer_can_cite() -> None:
    frame = bankrupt_like()
    spec, _ = suggest_spec(frame, question=ASKED, context=GLOSSARY)
    metrics, refused = compute_statistics(frame, spec)
    assert f"{DEBT}.corr.with.{MARGIN}" in metrics
    assert refused == []


def test_a_pair_holding_both_asked_columns_outranks_stronger_pairs_holding_one() -> None:
    # Khong co tu "tuong quan": khong kich hoat cap dich danh, nhung cap co CA HAI
    # cot duoc hoi van phai lot vao tran, du yeu hon moi cap chi co mot cot.
    # "lien quan" hoi ve quan he (khong hoi quan he thi khong do tuong quan nao,
    # chu he thong chot 2026-09-15) ma khong phai tu cua cap dich danh.
    question = "Tỷ lệ nợ và biên lợi nhuận gộp liên quan thế nào trong nhóm này?"
    spec, _ = suggest_spec(bankrupt_like(), question=question, context=GLOSSARY)
    assert (DEBT, MARGIN) in spec.correlations
    assert len(spec.correlations) == MAX_SUGGESTED


def test_an_open_question_still_searches_for_the_strongest_pairs() -> None:
    question = "Biến nào tương quan mạnh nhất với tỷ lệ nợ?"
    spec, _ = suggest_spec(bankrupt_like(), question=question, context=GLOSSARY)
    assert len(spec.correlations) == MAX_SUGGESTED
    assert all(DEBT in pair for pair in spec.correlations)


@pytest.mark.parametrize(
    ("question", "asks"),
    [
        ("Hai cột này có tương quan không?", True),
        ("Chúng tỷ lệ thuận hay tỷ lệ nghịch?", True),
        ("Chúng tỉ lệ nghịch à?", True),
        ("Doanh thu có đồng biến với chi phí?", True),
        ("What is the correlation between A and B?", True),
        ("So sánh trung bình tỷ lệ nợ giữa hai nhóm", False),
    ],
)
def test_the_question_is_read_for_the_word_correlation(question: str, asks: bool) -> None:
    assert asks_correlation(question) is asks
