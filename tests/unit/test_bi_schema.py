"""Moi cot mot vai tren khung keo tha, doc tu chinh gia tri, khong hoi model."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from analysis_system.services.bi_schema import schema_of, schema_of_file


def test_each_column_gets_the_role_tableau_would_give_it() -> None:
    frame = pd.DataFrame(
        {
            "Company": ["A", "B", "C"],
            "Bankrupt?": [0, 1, 0],
            "Debt ratio %": [0.1, 0.5, 0.3],
            "Employees": [10, 20, 30],
            "Active": [True, False, True],
            "Founded": pd.to_datetime(["2020-01-01", "2021-05-01", "2022-07-01"]),
            "Revenue as text": ["1.5", "2.0", "3.25"],
            "Flag as text": ["0", "1", "1"],
            "Signed on": ["2024-01-02", "2024-02-03", "2024-03-04"],
            "Empty": [None, None, None],
        }
    )
    got = {field.name: (field.role, field.kind) for field in schema_of(frame)}
    assert got == {
        "Company": ("dimension", "text"),
        "Bankrupt?": ("dimension", "boolean"),
        "Debt ratio %": ("measure", "number"),
        "Employees": ("measure", "number"),
        "Active": ("dimension", "boolean"),
        "Founded": ("dimension", "date"),
        "Revenue as text": ("measure", "number"),
        "Flag as text": ("dimension", "boolean"),
        "Signed on": ("dimension", "date"),
        "Empty": ("dimension", "text"),
    }


def test_the_order_of_columns_is_kept() -> None:
    frame = pd.DataFrame({"b": [1.5, 2.5], "a": ["x", "y"]})
    assert [field.name for field in schema_of(frame)] == ["b", "a"]


def test_a_file_is_read_again_only_when_it_changes(tmp_path: Path) -> None:
    path = tmp_path / "t.parquet"
    pd.DataFrame({"a": ["x", "y"]}).to_parquet(path)
    first = schema_of_file(path)
    assert schema_of_file(path) is first
    assert first.rows == 2

    pd.DataFrame({"a": ["x", "y", "z"], "v": [1.5, 2.5, 3.5]}).to_parquet(path)
    second = schema_of_file(path)
    assert second.rows == 3
    assert [field.name for field in second.fields] == ["a", "v"]


def test_a_rewrite_within_one_clock_tick_is_still_seen(tmp_path: Path) -> None:
    # Bo test day du tung ghi de tep trong cung mot nhip dong ho cua he thong
    # tep: thoi diem sua khong doi, va schema cu (2 dong) bi tra lai. Ep dung
    # tinh huong do thay vi cho may rui ve thoi gian.
    path = tmp_path / "t.parquet"
    pd.DataFrame({"a": ["x", "y"]}).to_parquet(path)
    before = path.stat()
    assert schema_of_file(path).rows == 2

    pd.DataFrame({"a": ["x", "y", "z"], "v": [1.5, 2.5, 3.5]}).to_parquet(path)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert path.stat().st_mtime_ns == before.st_mtime_ns
    assert schema_of_file(path).rows == 3
