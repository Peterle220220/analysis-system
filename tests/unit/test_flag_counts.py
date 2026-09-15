"""Dem va ty le cho mot cot co 0/1.

Cho trong nay lam hong mot cau tra loi that. Hoi "co bao nhieu cong ty pha san
va bao nhieu cong ty khong?", cot `Bankrupt?` la 0/1 - tuc mot cot SO, nen no
chi nhan duoc sum, mean, median, min, max.

`Bankrupt?.sum = 220` CHINH LA so cong ty pha san, nhung khong ai goi no nhu
the va model khong nhan ra. Con "bao nhieu cong ty KHONG pha san" thi that su
khong co: no la 6819 - 220, mot phep tru, va he thong cam tu tinh ra so moi.

Cau tra loi noi thang "chua duoc do" - trung thuc, va dung. Nhung dung vi mot
cho trong dang le khong nen co: cot co 0/1 la cach pho bien nhat de luu mot ket
qua co/khong.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from analysis_system.domains.execution_engine.metrics import compute_metrics


def _flags(rows: int = 100, ones: int = 20) -> pd.DataFrame:
    return pd.DataFrame({"Bankrupt?": [1] * ones + [0] * (rows - ones)})


# --- ca bon con so phai co that -----------------------------------------------


def test_the_count_of_each_value_is_measured() -> None:
    found = compute_metrics(_flags())
    assert found["Bankrupt?.1.count"].value == 20.0
    assert found["Bankrupt?.0.count"].value == 80.0


def test_the_share_of_each_value_is_measured() -> None:
    """ "Bao nhieu phan tram" phai tra loi duoc ma khong ai phai tu chia."""
    found = compute_metrics(_flags())
    assert found["Bankrupt?.1.share_pct"].value == 20.0
    assert found["Bankrupt?.0.share_pct"].value == 80.0


def test_the_shares_add_up_to_a_hundred() -> None:
    found = compute_metrics(_flags())
    total = found["Bankrupt?.0.share_pct"].value + found["Bankrupt?.1.share_pct"].value
    assert round(total, 6) == 100.0


def test_the_label_reads_as_a_person_would_write_it() -> None:
    """`1`, khong phai `1.0` hay `1_0`."""
    found = compute_metrics(_flags())
    assert "Bankrupt?.1.count" in found
    assert "Bankrupt?.1_0.count" not in found


def test_the_units_say_what_the_number_is() -> None:
    found = compute_metrics(_flags())
    assert found["Bankrupt?.1.count"].unit == "dòng"
    assert found["Bankrupt?.1.share_pct"].unit == "%"


# --- khong lam mat gi va khong no bua -----------------------------------------


def test_the_ordinary_numeric_metrics_are_still_there() -> None:
    found = compute_metrics(_flags())
    for suffix in ("sum", "mean", "median", "min", "max"):
        assert f"Bankrupt?.{suffix}" in found


def test_a_column_with_many_values_gets_no_flag_counts() -> None:
    """Dem tung gia tri cua mot cot lien tuc la sinh ra hang nghin chi so vo dung."""
    frame = pd.DataFrame({"doanh_thu": np.arange(100, dtype=float)})
    found = compute_metrics(frame)
    assert not any(".count" in key for key in found if key.startswith("doanh_thu."))


def test_a_constant_column_gets_no_flag_counts() -> None:
    # Mot cot khong doi thi khong co hai nhom de dem.
    found = compute_metrics(pd.DataFrame({"co": [1] * 50}))
    assert "co.1.count" not in found


def test_a_two_valued_column_that_is_not_a_flag_still_works() -> None:
    """Khong phai co 0/1 nao cung la 0 va 1."""
    found = compute_metrics(pd.DataFrame({"diem": [5.0] * 30 + [9.0] * 70}))
    assert found["diem.5.count"].value == 30.0
    assert found["diem.9.count"].value == 70.0


def test_an_empty_frame_survives() -> None:
    assert compute_metrics(pd.DataFrame()) is not None
