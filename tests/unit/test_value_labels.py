"""Nhan tieng Viet cho gia tri cua cot phan loai: tu suy cho cot co, khai tay thang.

Loi goc: bieu do so sanh hai nhom tren mot cot co 0/1 ghi "cot=0" va "cot=1",
dung ma nguoi doc bao cao khong hieu. Khong duoc viet cung ten cot nao: nhan phai
den tu du lieu va tu nguoi dung, de dung duoc cho moi bo du lieu.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from analysis_system.services.value_labels import (
    VALUES_FILE,
    categories_of,
    display_name,
    effective_labels,
    labels_text,
    parse_labels,
    read_labels,
    suggested,
    write_labels,
)
from analysis_system.web.view import _charts

# --- cot nao la cot phan loai ---------------------------------------------------


def test_a_flag_and_a_small_text_column_are_categories() -> None:
    frame = pd.DataFrame(
        {
            "da_nghi": [0, 1] * 10,
            "vung": ["Bac", "Nam", "Trung", "Bac"] * 5,
            "luong": [float(index) for index in range(20)],
        }
    )
    found = categories_of(frame)
    assert found["da_nghi"] == ["0", "1"]
    assert found["vung"] == ["Bac", "Nam", "Trung"]
    assert "luong" not in found  # 20 gia tri: la so do, khong phai nhom


def test_numbers_sort_as_numbers() -> None:
    frame = pd.DataFrame({"hang": [10, 2, 1] * 4})
    assert categories_of(frame)["hang"] == ["1", "2", "10"]


def test_a_value_seen_once_per_group_is_not_a_category() -> None:
    frame = pd.DataFrame({"ma": ["a", "b", "c"]})
    assert categories_of(frame) == {}


# --- doc va viet o Nhan gia tri ---------------------------------------------------


def test_the_labels_cell_reads_and_writes_back_the_same() -> None:
    labels = parse_labels("0 = Còn hoạt động; 1 =  Đã   đóng cửa")
    assert labels == {"0": "Còn hoạt động", "1": "Đã đóng cửa"}
    assert labels_text(labels) == "0 = Còn hoạt động; 1 = Đã đóng cửa"


def test_a_pair_without_an_equals_sign_is_ignored() -> None:
    assert parse_labels("0 = Không; linh tinh; 1 =") == {"0": "Không"}


# --- tu suy cho cot co ------------------------------------------------------------


def test_a_flag_with_a_meaning_is_named_both_ways() -> None:
    assert suggested(["0", "1"], "đóng cửa; ngừng hoạt động") == {
        "0": "Không đóng cửa",
        "1": "Đóng cửa",
    }


def test_booleans_are_flags_too() -> None:
    assert suggested(["False", "True"], "đã nghỉ") == {"False": "Không đã nghỉ", "True": "Đã nghỉ"}


def test_no_guess_for_a_column_that_is_not_a_flag() -> None:
    assert suggested(["Bac", "Nam"], "vùng") == {}
    assert suggested(["0", "1", "2"], "hạng") == {}


def test_no_guess_without_a_meaning() -> None:
    assert suggested(["0", "1"], "") == {}


def test_no_double_negative() -> None:
    assert suggested(["0", "1"], "không có con") == {}


def test_the_display_name_is_the_first_alternative_capitalised() -> None:
    assert display_name("biên lợi nhuận gộp; lãi gộp") == "Biên lợi nhuận gộp"


# --- khai tay thang, theo tung gia tri --------------------------------------------


def test_a_declared_label_wins_value_by_value() -> None:
    found = effective_labels(
        {"flag": ["0", "1"]}, {"flag": {"0": "Còn hoạt động"}}, {"flag": "đóng cửa"}
    )
    assert found == {"flag": {"0": "Còn hoạt động", "1": "Đóng cửa"}}


def test_nothing_known_means_nothing_changed() -> None:
    assert effective_labels({"vung": ["Bac", "Nam"]}, {}, {}) == {}


def test_saved_labels_come_back(tmp_path: Path) -> None:
    write_labels(tmp_path, {"flag": {"0": "Không", "1": "Có"}, "rong": {}})
    assert read_labels(tmp_path) == {"flag": {"0": "Không", "1": "Có"}}


def test_a_broken_labels_file_reads_as_none(tmp_path: Path) -> None:
    (tmp_path / VALUES_FILE).write_text("{ khong phai json", encoding="utf-8")
    assert read_labels(tmp_path) == {}


# --- bieu do dung nhan -------------------------------------------------------------


def test_the_chart_on_the_page_uses_the_labels() -> None:
    measured = {"m.mean.by.flag.0": 0.6083, "m.mean.by.flag.1": 0.5987}
    answer = SimpleNamespace(claims=[SimpleNamespace(claim="So sánh", metric_keys=tuple(measured))])
    labels = {"flag": {"0": "Còn hoạt động", "1": "Đã đóng cửa"}}
    drawn = _charts(answer, measured, labels, {})  # type: ignore[arg-type]
    assert "flag: 0" not in drawn[0]
    assert "<b>Còn hoạt động</b> cao hơn Đã đóng cửa" in drawn[0]
