"""Tests for the single I/O gateway, including atomicity of every write."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pytest

from analysis_system.core.storage import (
    StorageError,
    _atomic_write,
    read_csv,
    read_parquet,
    sha256_file,
    write_parquet,
    write_text,
)


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "case_id": ["c1", "c1", "c2"],
            "activity": ["Create", "Approve", "Create"],
            "amount": ["10.5", "20", "30"],
        }
    )


def test_read_csv_keeps_every_column_as_text(tmp_path: Path) -> None:
    source = tmp_path / "input.csv"
    source.write_text("case_id,amount\n0012,10.50\n", encoding="utf-8")
    frame = read_csv(source)
    # Leading zeros survive only if ingest refuses to reinterpret values.
    assert frame.loc[0, "case_id"] == "0012"
    assert frame.loc[0, "amount"] == "10.50"


def test_parquet_roundtrip_preserves_content(tmp_path: Path) -> None:
    target = tmp_path / "events.parquet"
    write_parquet(_frame(), target)
    restored = read_parquet(target)
    pd.testing.assert_frame_equal(restored, _frame())


def test_write_leaves_no_temporary_file_behind(tmp_path: Path) -> None:
    write_text("bao cao", tmp_path / "report.md")
    write_parquet(_frame(), tmp_path / "events.parquet")
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_failed_write_keeps_the_previous_file_intact(tmp_path: Path) -> None:
    target = tmp_path / "report.md"
    write_text("noi dung cu", target)

    def _explode(_: Path) -> None:
        raise RuntimeError("ghi that bai giua chung")

    with pytest.raises(RuntimeError):
        _atomic_write(target, _explode)

    assert target.read_text(encoding="utf-8") == "noi dung cu"
    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []


def test_write_text_pins_unix_line_endings(tmp_path: Path) -> None:
    target = tmp_path / "report.md"
    write_text("dong 1\ndong 2\n", target)
    assert target.read_bytes() == b"dong 1\ndong 2\n"


def test_written_files_are_readable_not_owner_only(tmp_path: Path) -> None:
    target = tmp_path / "report.md"
    write_text("noi dung", target)
    # mkstemp would leave 0600; artefacts must be readable like any other file.
    assert target.stat().st_mode & 0o044


def test_sha256_file_matches_hashlib(tmp_path: Path) -> None:
    target = tmp_path / "blob.bin"
    payload = b"noi dung bat ky" * 1000
    target.write_bytes(payload)
    assert sha256_file(target) == hashlib.sha256(payload).hexdigest()


def test_reading_a_missing_file_raises_storage_error(tmp_path: Path) -> None:
    with pytest.raises(StorageError):
        read_csv(tmp_path / "khong-co.csv")
    with pytest.raises(StorageError):
        read_parquet(tmp_path / "khong-co.parquet")


def test_writing_into_a_missing_directory_raises_storage_error(tmp_path: Path) -> None:
    with pytest.raises(StorageError):
        write_text("x", tmp_path / "chua-ton-tai" / "report.md")
