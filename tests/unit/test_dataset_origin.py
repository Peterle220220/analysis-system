"""Lối vào của bộ dữ liệu: ghi khi tải lên, đọc khi dựng danh sách."""

from __future__ import annotations

from pathlib import Path

from analysis_system.services.dataset_origin import (
    DIRECT,
    LIBRARY,
    ORIGIN_FILE,
    origin_of,
    read_origins,
    record_origin,
)


def test_an_upload_is_remembered_by_where_it_came_from(tmp_path: Path) -> None:
    record_origin(tmp_path, "student_performance", DIRECT)
    record_origin(tmp_path, "finance_data", LIBRARY)
    assert origin_of(tmp_path, "student_performance") == DIRECT
    assert origin_of(tmp_path, "finance_data") == LIBRARY


def test_a_dataset_uploaded_before_the_ledger_counts_as_the_library(tmp_path: Path) -> None:
    assert origin_of(tmp_path, "bankruptcy") == LIBRARY


def test_uploading_again_overwrites_the_origin(tmp_path: Path) -> None:
    record_origin(tmp_path, "finance_data", LIBRARY)
    record_origin(tmp_path, "finance_data", DIRECT)
    assert origin_of(tmp_path, "finance_data") == DIRECT


def test_an_unknown_origin_is_stored_as_the_library(tmp_path: Path) -> None:
    assert record_origin(tmp_path, "x", "tu_mot_noi_la") == LIBRARY
    assert read_origins(tmp_path) == {"x": LIBRARY}


def test_a_broken_ledger_is_read_as_empty_and_rewritten_cleanly(tmp_path: Path) -> None:
    (tmp_path / ORIGIN_FILE).write_text("không phải JSON", encoding="utf-8")
    assert read_origins(tmp_path) == {}
    record_origin(tmp_path, "a", DIRECT)
    assert read_origins(tmp_path) == {"a": DIRECT}
    assert sorted(item.name for item in tmp_path.iterdir()) == [ORIGIN_FILE]
