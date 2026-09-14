"""Ten bo du lieu hien thi dung nhu nguoi dung go; ma bo van la thu di vao duong dan."""

from __future__ import annotations

from pathlib import Path

from analysis_system.services.dataset_labels import (
    LABEL_FILE,
    MAX_LABEL,
    display_label,
    forget_label,
    label_of,
    read_labels,
    record_label,
)


def test_the_typed_name_is_kept_with_its_marks() -> None:
    typed = "  Báo cáo tài chính MB   của 4 quý gần nhất "
    assert display_label(typed, "x.xls") == "Báo cáo tài chính MB của 4 quý gần nhất"


def test_without_a_typed_name_the_file_name_is_used() -> None:
    assert display_label("", "Doanh thu Quý 3.xlsx") == "Doanh thu Quý 3"
    assert display_label("   ", "C:\\fakepath\\Đơn hàng.csv") == "Đơn hàng"
    assert display_label("", "") == ""


def test_a_long_name_is_cut_and_control_characters_dropped() -> None:
    assert len(display_label("a" * 300, "")) == MAX_LABEL
    assert display_label("Tên\x00\x1b lạ", "") == "Tên lạ"


def test_a_name_is_recorded_read_and_forgotten(tmp_path: Path) -> None:
    assert record_label(tmp_path, "bao_cao", "Báo cáo") == "Báo cáo"
    assert label_of(tmp_path, "bao_cao") == "Báo cáo"
    # Bo chua co ten thi hien ma cua no.
    assert label_of(tmp_path, "khac") == "khac"
    record_label(tmp_path, "bao_cao", "Báo cáo quý 3")
    assert read_labels(tmp_path) == {"bao_cao": "Báo cáo quý 3"}
    forget_label(tmp_path, "bao_cao")
    assert read_labels(tmp_path) == {}


def test_a_broken_ledger_reads_as_empty(tmp_path: Path) -> None:
    (tmp_path / LABEL_FILE).write_text("{", encoding="utf-8")
    assert read_labels(tmp_path) == {}
    assert label_of(tmp_path, "bo") == "bo"
