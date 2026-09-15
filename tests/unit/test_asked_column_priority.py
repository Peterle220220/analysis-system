"""Cot duoc hoi phai duoc tach nhom, va chu giai thang moi phep doan cot.

Luot chay that tren bo pha san, hoi "So sanh bien loi nhuan gop trung binh giua
nhom pha san va nhom song sot":

* buoc phan tich KHONG nhan duoc cau hoi nao (chi co loi dan cua Manager), nen
  buoc chon phep kiem chon tam cot tach nhom ro nhat va bo dung cot duoc hoi;
  cau tra loi chi co mot trung binh chung 0.61, khong tach nhom;
* phan chon chi so khop theo chu, khong doc chu giai, va giu lai `Gross Profit to
  Sales` thay cho `Operating Gross Margin` ma chu giai da chi dich danh.

Do tren chinh bang do: dua cau hoi va chu giai vao thi cap (Operating Gross
Margin, Bankrupt?) dung hang MOT.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analysis_system.agents.a7_analyst import AnalystAgent
from analysis_system.core.settings import load_settings
from analysis_system.domains.data_ingestion.glossary_store import GLOSSARY_PARAM
from analysis_system.services.asked_columns import ASKED_PARAM, asked_question
from analysis_system.services.shortlist import by_glossary, choose, rankings_for
from analysis_system.services.statistics import compute_statistics, suggest_spec

GLOSSARY = "\n".join(
    [
        "Operating Gross Margin = biên lợi nhuận gộp hoạt động",
        "Realized Sales Gross Margin = biên lợi nhuận gộp doanh thu thực tế",
        "Gross Profit to Sales = lợi nhuận gộp/doanh thu",
        "Bankrupt? = phá sản",
    ]
)
QUESTION = (
    "So sánh biên lợi nhuận gộp trung bình giữa nhóm phá sản và nhóm sống sót. "
    "Nhóm nào có biên lợi nhuận tốt hơn?"
)


# --- cau hoi goc ---------------------------------------------------------------


def test_the_original_question_comes_first() -> None:
    params = {ASKED_PARAM: "câu gốc", "question": "câu của bước"}
    assert asked_question(params, "lời dặn") == "câu gốc"


def test_then_the_step_question_then_the_instruction() -> None:
    assert asked_question({"question": "câu của bước"}, "lời dặn") == "câu của bước"
    assert asked_question({}, "lời dặn") == "lời dặn"


# --- buoc chon phep kiem nhan duoc cau hoi --------------------------------------


def _frame() -> pd.DataFrame:
    """Muoi cot tach nhom ro hon han cot duoc hoi, du de tran 8 phep kiem day."""
    rng = np.random.default_rng(0)
    group = np.array([0] * 30 + [1] * 30)
    data: dict[str, object] = {"Bankrupt?": group}
    for index in range(10):
        data[f"Strong separator {index}"] = group * (5 + index) + rng.normal(0, 1, 60)
    data["Operating Gross Margin"] = group * 0.2 + rng.normal(0, 1, 60)
    return pd.DataFrame(data)


def _split_by_group(params: dict[str, object]) -> set[str]:
    metrics, _ = AnalystAgent(load_settings())._statistics(_frame(), params)
    return {key.split(".", 1)[0] for key in metrics if ".by.Bankrupt?" in key}


def test_without_the_question_the_asked_column_is_not_split() -> None:
    """Dung loi cua luot chay that: khong co cau hoi thi cot duoc hoi bi bo."""
    assert "Operating Gross Margin" not in _split_by_group({})


def test_the_original_question_reaches_the_test_selection() -> None:
    params: dict[str, object] = {ASKED_PARAM: QUESTION, GLOSSARY_PARAM: GLOSSARY}
    assert "Operating Gross Margin" in _split_by_group(params)


# --- chu giai uu tien tuyet doi khi chon chi so ----------------------------------

COLUMNS = [
    "Operating Gross Margin",
    "Realized Sales Gross Margin",
    "Gross Profit to Sales",
    "Bankrupt?",
    "Debt ratio %",
]


def test_the_glossary_names_the_column_asked_for() -> None:
    found = by_glossary(QUESTION, COLUMNS, GLOSSARY)
    assert {"Operating Gross Margin", "Bankrupt?"} <= found
    assert "Gross Profit to Sales" not in found


def test_no_glossary_means_no_override() -> None:
    assert by_glossary(QUESTION, COLUMNS, "") == set()


def _metrics() -> list[dict[str, object]]:
    keys = [
        "Gross Profit to Sales.mean",
        "Operating Gross Margin.mean",
        "Operating Gross Margin.diff.by.Bankrupt?",
        *(f"Filler {index}.mean" for index in range(40)),
    ]
    return [{"key": key, "value": 0.5, "unit": ""} for key in keys]


def test_the_shortlist_keeps_the_grouped_numbers_of_the_glossary_column() -> None:
    shown, note = choose(_metrics(), QUESTION, budget=200, glossary=GLOSSARY)
    assert "Operating Gross Margin.diff.by.Bankrupt?" in {item["key"] for item in shown}
    assert "Operating Gross Margin" in note
    assert "Gross Profit to Sales" not in note


def test_without_the_glossary_the_grouped_numbers_were_dropped() -> None:
    """Dung loi cua luot chay that: cau hoi tieng Viet, khong ai doc chu giai."""
    shown, _ = choose(_metrics(), QUESTION, budget=200)
    assert "Operating Gross Margin.diff.by.Bankrupt?" not in {item["key"] for item in shown}


def test_the_rankings_put_the_glossary_column_first() -> None:
    ranked = [{"khoa": "Gross Profit to Sales.mean"}, {"khoa": "Operating Gross Margin.mean"}]
    shown = [{"key": "Gross Profit to Sales.mean"}, {"key": "Operating Gross Margin.mean"}]
    ordered = rankings_for(ranked, shown, QUESTION, glossary=GLOSSARY)
    assert ordered[0]["khoa"] == "Operating Gross Margin.mean"


# --- trung binh tung nhom: "nhom nao cao hon" phai doc duoc ----------------------


def test_each_group_gets_its_own_mean_so_the_direction_is_readable() -> None:
    frame = _frame()
    params: dict[str, object] = {ASKED_PARAM: QUESTION, GLOSSARY_PARAM: GLOSSARY}
    metrics, _ = AnalystAgent(load_settings())._statistics(frame, params)
    means = frame.groupby("Bankrupt?")["Operating Gross Margin"].mean()
    first = metrics["Operating Gross Margin.mean.by.Bankrupt?.0"].value
    second = metrics["Operating Gross Margin.mean.by.Bankrupt?.1"].value
    assert first == pytest.approx(means[0], abs=1e-3)
    assert second == pytest.approx(means[1], abs=1e-3)
    # Muc chenh la nhom dau tru nhom sau: gio doc ra duoc tu hai con so tren.
    diff = metrics["Operating Gross Margin.diff.by.Bankrupt?"].value
    assert diff == pytest.approx(first - second, abs=1e-3)


def test_three_groups_get_a_mean_each() -> None:
    rng = np.random.default_rng(1)
    frame = pd.DataFrame({"score": rng.normal(0, 1, 30), "region": ["A", "B", "C"] * 10})
    spec, _ = suggest_spec(frame, question="", context="")
    metrics, _ = compute_statistics(frame, spec)
    for region in ("A", "B", "C"):
        expected = frame.loc[frame["region"] == region, "score"].mean()
        assert metrics[f"score.mean.by.region.{region}"].value == pytest.approx(expected, abs=1e-3)
