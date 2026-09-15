"""Tran cho so phep chia nho, de bang nhieu cot khong treo may.

So phep `{do luong}.mean.by.{cot}.{nhom}` la tich cua ba thu - so cot chia
nhom, so nhom moi cot, so cot so - nen no tang theo BINH PHUONG so cot:

    100 cot ->   8.276 chi so,   6,8 giay
    300 cot ->  69.826 chi so,  56,4 giay
    500 cot -> 191.376 chi so, 155,0 giay
   1000 cot ->                   19 phut

Trong khi lop cat ngan sach chi gui khoang 540 cai cho model. Tinh 191.376 de
gui 540 la lang phi 350 lan, va nguoi dung ngoi cho ba phut cho phan lang phi.
"""

from __future__ import annotations

import time
from collections.abc import Mapping

import numpy as np
import pandas as pd

from analysis_system.domains.execution_engine.metrics import MAX_BREAKDOWNS, compute_metrics


def _wide(cols: int, rows: int = 2_000) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    data: dict[str, object] = {}
    for index in range(cols):
        if index % 4 == 0:
            data[f"nhom_{index}"] = pd.Series([f"g{i % 4}" for i in range(rows)], dtype=object)
        else:
            data[f"so_{index}"] = rng.normal(size=rows)
    return pd.DataFrame(data)


def _breakdowns(metrics: Mapping[str, object]) -> int:
    return sum(1 for key in metrics if ".mean.by." in key)


def test_a_wide_table_stays_under_the_cap() -> None:
    frame = _wide(400)
    cats = [c for c in frame.columns if frame[c].dtype == object]
    found = compute_metrics(frame, dimensions=tuple(cats))
    assert _breakdowns(found) <= MAX_BREAKDOWNS


def test_a_wide_table_finishes_quickly() -> None:
    """Truoc khi co tran, 500 cot mat 155 giay va 1000 cot mat 19 phut."""
    frame = _wide(400)
    cats = [c for c in frame.columns if frame[c].dtype == object]
    started = time.time()
    compute_metrics(frame, dimensions=tuple(cats))
    assert time.time() - started < 20


def test_what_was_left_out_is_said_out_loud() -> None:
    """Bo trong im lang thi nguoi doc tuong cai duoi day la tat ca."""
    frame = _wide(400)
    cats = [c for c in frame.columns if frame[c].dtype == object]
    found = compute_metrics(frame, dimensions=tuple(cats))
    assert "breakdowns_omitted" in found
    assert found["breakdowns_omitted"].value > 0


def test_an_ordinary_table_is_not_capped_and_says_nothing() -> None:
    """Bang 21 cot cua chu he thong dung khoang 110 phep - xa tran."""
    frame = _wide(20)
    cats = [c for c in frame.columns if frame[c].dtype == object]
    found = compute_metrics(frame, dimensions=tuple(cats))
    assert _breakdowns(found) < MAX_BREAKDOWNS
    assert "breakdowns_omitted" not in found


def test_the_ordinary_metrics_are_all_still_there() -> None:
    # Tran chi cham vao phep chia nho, khong cham vao gi khac.
    frame = _wide(20)
    cats = [c for c in frame.columns if frame[c].dtype == object]
    found = compute_metrics(frame, dimensions=tuple(cats))
    assert any(key.endswith(".mean") for key in found)
    assert any(key.endswith(".share_pct") for key in found)
    assert "rows.total" in found
