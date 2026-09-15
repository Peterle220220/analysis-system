"""Chia cột thành Dimension và Measure (như Tableau), bằng code, không hỏi model.

Dimension là thứ để chia nhóm: chữ, ngày tháng, đúng/sai, và cột số chỉ mang 0/1
(như `Bankrupt?`: con số ở đây là một mã, cộng hay lấy trung bình nó không có
nghĩa gì). Measure là cột số còn lại: thứ để cộng, lấy trung bình, đếm. Mỗi cột
một vai rõ ràng, để vùng thả biết cột nào nhận cột nào.
"""

from __future__ import annotations

import warnings
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, Literal

import pandas as pd

Role = Literal["dimension", "measure"]
Kind = Literal["text", "date", "boolean", "number"]

# Cột lưu dạng chữ mà ít nhất chừng này phần đọc được thành số (hay thành ngày)
# thì được coi là cột số (hay cột ngày). Dưới mức đó là chữ lẫn số: một mã.
PARSE_SHARE: Final[float] = 0.9
# Chỉ đọc chừng này giá trị đầu để đoán cột ngày: đủ để chắc, không phải đọc hết.
DATE_SAMPLE: Final[int] = 500


@dataclass(frozen=True)
class Field:
    """Một cột, và vai của nó trên khung kéo thả."""

    name: str
    role: Role
    kind: Kind
    distinct: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FileSchema:
    """Số dòng và các Field của một tệp Parquet."""

    rows: int
    fields: tuple[Field, ...]


def _is_flag(values: pd.Series[Any]) -> bool:
    """Cột số chỉ mang 0 và 1: một cờ đánh dấu, không phải một phép đo."""
    distinct = set(values.unique().tolist())
    return 0 < len(distinct) <= 2 and distinct <= {0, 1}


def _parses_as_dates(text: pd.Series[Any]) -> bool:
    sample = text.head(DATE_SAMPLE)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        parsed = pd.to_datetime(sample, errors="coerce", format="mixed")
    return bool(parsed.notna().mean() >= PARSE_SHARE)


def field_of(name: str, series: pd.Series[Any]) -> Field:
    """Vai của một cột, đọc từ chính giá trị trong cột."""
    values = series.dropna()
    distinct = int(values.nunique())
    if pd.api.types.is_bool_dtype(series):
        return Field(name, "dimension", "boolean", distinct)
    if pd.api.types.is_datetime64_any_dtype(series):
        return Field(name, "dimension", "date", distinct)
    if pd.api.types.is_numeric_dtype(series):
        if _is_flag(values):
            return Field(name, "dimension", "boolean", distinct)
        return Field(name, "measure", "number", distinct)
    text = values.astype(str).str.strip()
    text = text[text != ""]
    if text.empty:
        return Field(name, "dimension", "text", distinct)
    numbers = pd.to_numeric(text, errors="coerce")
    if numbers.notna().mean() >= PARSE_SHARE:
        if _is_flag(numbers.dropna()):
            return Field(name, "dimension", "boolean", distinct)
        return Field(name, "measure", "number", distinct)
    if _parses_as_dates(text):
        return Field(name, "dimension", "date", distinct)
    return Field(name, "dimension", "text", distinct)


def schema_of(frame: pd.DataFrame) -> list[Field]:
    """Mỗi cột một Field, theo đúng thứ tự cột trong bảng."""
    return [field_of(str(column), frame[column]) for column in frame.columns]


@lru_cache(maxsize=16)
def _read_schema(path: str, stamp: tuple[int, int, int]) -> FileSchema:  # noqa: ARG001 - khoá bộ nhớ đệm
    frame = pd.read_parquet(path)
    return FileSchema(rows=len(frame.index), fields=tuple(schema_of(frame)))


def schema_of_file(path: Path) -> FileSchema:
    """Schema của một tệp Parquet, nhớ theo dấu vết của tệp.

    Mỗi lần thả cột là một lần hỏi; đọc lại cả bảng mỗi lần là phí. Khoá nhớ là
    thời điểm sửa CỘNG kích thước và inode: riêng thời điểm sửa thì không đủ, vì
    hệ thống tệp ghi nó theo nhịp đồng hồ thô (vài mili giây), và hai lần ghi
    trong cùng một nhịp giữ nguyên thời điểm. Đã đo: bộ test đầy đủ ghi đè tệp
    trong một nhịp và nhận lại schema cũ, 2 dòng thay vì 3.
    """
    found = path.stat()
    return _read_schema(str(path), (found.st_mtime_ns, found.st_size, found.st_ino))
