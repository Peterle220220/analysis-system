"""Dò tìm mọi giả định về hình dạng đầu vào, trong một lượt.

Bốn lỗi vừa qua đều cùng một họ: một giả định về tên cột hay hình dạng bảng,
đóng cứng từ hồi hệ thống chỉ được thử trên dữ liệu sạch sẽ. Chủ hệ thống vấp
từng cái một, mỗi bộ dữ liệu một lỗi.

Bài này không chờ nữa. Nó ném vào hệ thống những cái tên cột và hình dạng bảng
tệ nhất còn gặp được trong thực tế, chạy qua mọi tầng KHÔNG cần API, và đếm chỗ
nào vỡ.

Không gọi model. Không tốn tiền. Chạy hết trong vài giây.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest

from analysis_system.domains.visualization.svg_chart import bar_chart, pairs_from
from analysis_system.models.agents import Finding, MetricValue
from analysis_system.services.asked_columns import columns_in, untouched
from analysis_system.services.column_names import tidy
from analysis_system.services.findings import rankings, render_all
from analysis_system.services.metric_families import grouped
from analysis_system.services.metrics import compute_metrics
from analysis_system.services.shortlist import choose
from analysis_system.services.statistics import suggest_spec

# Ten cot te nhat con gap duoc trong thuc te.
TEN_COT = [
    "Bankrupt?",
    " ROA(A) before interest and % after tax",
    "Non-industry income and expenditure/revenue",
    "cons.price.idx",
    "y",
    "Doanh thu (trieu dong)",
    "col with quotes",
    "col{with}braces",
    "col.with.many.dots",
    "UPPER lower MiXeD",
    "cot_tieng_viet_co_dau",
    "x" * 120,
    "123",
    "-",
]

HINH_DANG = {
    "mot dong": pd.DataFrame({"a": [1.0], "b": ["x"]}),
    "mot cot": pd.DataFrame({"a": list(range(40))}),
    "bang rong": pd.DataFrame(),
    "cot toan rong": pd.DataFrame({"a": [None] * 40, "b": list(range(40))}),
    "cot khong doi": pd.DataFrame({"a": [1.0] * 40, "b": [f"g{i % 3}" for i in range(40)]}),
    "moi dong mot nhom": pd.DataFrame({"a": [f"id{i}" for i in range(40)], "b": list(range(40))}),
    "NaN va vo cuc": pd.DataFrame({"a": [np.nan, np.inf, -np.inf, *range(37)]}),
    "so am va zero": pd.DataFrame(
        {"a": [-5.0, 0.0, 5.0] * 14, "b": [f"g{i % 2}" for i in range(42)]}
    ),
    "ten cot trung nhau": pd.DataFrame(np.zeros((40, 2)), columns=["a", "a"]),
}


def _bang(cot: list[str], rows: int = 40) -> pd.DataFrame:
    data: dict[str, list[Any]] = {}
    for index, name in enumerate(cot):
        if index % 3 == 0:
            data[name] = [float(i % 7) for i in range(rows)]
        elif index % 3 == 1:
            data[name] = [f"nhom_{i % 4}" for i in range(rows)]
        else:
            data[name] = [i % 2 for i in range(rows)]
    return pd.DataFrame(data)


@pytest.fixture
def kho() -> tuple[pd.DataFrame, dict[str, MetricValue]]:
    frame, _ = tidy(_bang(TEN_COT))
    return frame, compute_metrics(frame, dimensions=tuple(frame.columns))


CAU_HOI = "Ty le Bankrupt? la bao nhieu, va ROA trung binh the nao?"


def test_every_layer_survives_awkward_column_names(
    kho: tuple[pd.DataFrame, dict[str, MetricValue]],
) -> None:
    frame, metrics = kho
    view = [{"key": m.key, "value": m.value, "unit": m.unit} for m in metrics.values()]
    choose(view, CAU_HOI)
    grouped(view, CAU_HOI)
    rankings(metrics)
    columns_in(list(metrics))
    untouched(CAU_HOI, [list(metrics)[:2]], list(metrics))
    suggest_spec(frame, question=CAU_HOI)
    bar_chart(pairs_from({k: v.value for k, v in metrics.items()}, list(metrics)[:6]))


def test_every_measured_key_can_be_put_into_a_sentence(
    kho: tuple[pd.DataFrame, dict[str, MetricValue]],
) -> None:
    """Mot chi so do duoc ma khong dat vao cau duoc la mot chi so vo dung."""
    _, metrics = kho
    khong_chen_duoc = [
        key
        for key in list(metrics)[:300]
        if not render_all(
            [
                Finding(
                    claim_template="Gia tri la {" + key + "}.",
                    metric_keys=(key,),
                    evidence_ref="m://x",
                )
            ],
            metrics,
        )[0]
    ]
    assert khong_chen_duoc == []


@pytest.mark.parametrize("ten", sorted(HINH_DANG))
def test_an_awkward_table_shape_does_not_crash(ten: str) -> None:
    frame, _ = tidy(HINH_DANG[ten])
    compute_metrics(frame, dimensions=tuple(frame.columns))
    suggest_spec(frame, question="phan tich")
