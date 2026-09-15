"""Phạm vi của một bảng mart: bao nhiêu dòng, lọc theo điều kiện nào.

Bước biến đổi ghi câu SQL đã dựng bảng vào một tệp `.sql` nằm ngay cạnh bảng. Đọc
lại tệp đó thì biết mọi con số đo trên bảng này thuộc về tập nào.

Không nói ra thì model tự đoán. Lượt chạy thật, hỏi trong nhóm "tỷ lệ nợ lớn hơn
0.2": SQL lọc đúng `> 0.2` (381 trên 6.819 dòng), nhưng model gọi trung bình của
chính tập đã lọc (0.23) là "mức trung bình chung", và gán tỷ lệ phá sản của 381
dòng ấy (20,21 %) cho "toàn bộ dữ liệu", vốn chỉ có 3,23 %. Mọi con số đều thật,
nên lớp chống bịa số không bắt được: sai là PHẠM VI, không phải con số.

Lọc ra 0 dòng cũng là một câu trả lời ("có bao nhiêu" là 0), và nó cần một lời
giải thích: tệp SQL ghi thêm khoảng giá trị thật của các cột trong điều kiện, để
người đọc thấy vì sao rỗng thay vì đoán là hệ thống hỏng.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final

import pandas as pd

from analysis_system.core import storage
from analysis_system.core.boundary import BoundaryViolation
from analysis_system.core.settings import ConfigError

RECIPE_SUFFIX: Final[str] = ".sql"
MART_PREFIX: Final[str] = "mart://"

ROWS_OUT: Final[re.Pattern[str]] = re.compile(r"^--\s*(\d+)\s+dong ra\s*$", re.MULTILINE)
ROWS_IN: Final[re.Pattern[str]] = re.compile(r"^--\s*(\d+)\s+dong vao\s*$", re.MULTILINE)
NOTE: Final[re.Pattern[str]] = re.compile(r"^--\s*ghi chu:\s*(.+?)\s*$", re.MULTILINE)
NOTE_PREFIX: Final[str] = "-- ghi chu: "

# Mệnh đề WHERE, tới mệnh đề kế tiếp hoặc hết câu. Đọc bằng chữ, không phân tích
# cú pháp: chỉ để NÓI RA điều kiện, không để quyết định gì.
WHERE: Final[re.Pattern[str]] = re.compile(
    r"\bwhere\b(.+?)(?=\bgroup\s+by\b|\border\s+by\b|\bhaving\b|\bqualify\b|\blimit\b"
    r"|\bunion\b|\)\s*select\b|;|$)",
    re.IGNORECASE | re.DOTALL,
)

# Luật đi kèm khi có phạm vi, cho cả A7 lẫn A9.
SCOPE_RULE: Final[str] = (
    "Neu co 'pham_vi_du_lieu': moi chi so do tren DUNG tap do, KHONG phai toan bo du "
    "lieu. Khong goi trung binh cua tap nay la 'trung binh chung', khong viet 'toan bo "
    "du lieu' hay 'ca bo du lieu'. Muon nhac dieu kien loc thi chep DUNG dieu kien trong "
    "'pham_vi_du_lieu', dung dien giai lai thanh mot nguong khac."
)


@dataclass(frozen=True)
class DataScope:
    """Một tập đã lọc: bao nhiêu dòng, trên tổng bao nhiêu, theo điều kiện nào."""

    rows: int
    total: int | None
    condition: str
    notes: tuple[str, ...] = ()


def recipe_of(table_uri: str) -> str:
    """Tệp SQL nằm cạnh một bảng mart."""
    return table_uri.rsplit(".", 1)[0] + RECIPE_SUFFIX


def _conditions(sql: str) -> list[str]:
    body = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    found = [" ".join(match.group(1).split()) for match in WHERE.finditer(body)]
    return [condition for condition in found if condition]


def parse_recipe(text: str) -> DataScope | None:
    """Phạm vi đọc từ tệp SQL. Không có WHERE thì bảng không bị lọc: không có phạm vi."""
    conditions = _conditions(text)
    rows = ROWS_OUT.search(text)
    if not conditions or rows is None:
        return None
    total = ROWS_IN.search(text)
    return DataScope(
        rows=int(rows.group(1)),
        total=int(total.group(1)) if total else None,
        condition=" và ".join(conditions),
        notes=tuple(NOTE.findall(text)),
    )


def _plain(value: float) -> str:
    return f"{float(value):g}"


def empty_note(sql: str, tables: Mapping[str, pd.DataFrame], rows_out: int) -> list[str]:
    """Dòng ghi chú cho tệp SQL khi lọc ra 0 dòng: vì sao rỗng, bằng khoảng giá trị thật.

    Mỗi cột SỐ có mặt trong điều kiện được ghi khoảng nhỏ nhất đến lớn nhất của nó.
    Hỏi "lợi nhuận âm" trên một cột đã chuẩn hóa về 0 đến 1 thì câu này là cả lời giải
    thích: cột ấy không có giá trị âm nào.
    """
    if rows_out != 0:
        return []
    condition = " ".join(_conditions(sql))
    if not condition:
        return []
    lines = [f"{NOTE_PREFIX}Không có dòng nào thỏa điều kiện lọc."]
    seen: set[str] = set()
    for frame in tables.values():
        for column in frame.columns:
            name = str(column)
            if name in seen or not pd.api.types.is_numeric_dtype(frame[column]):
                continue
            quoted = f'"{name}"' in condition
            bare = re.search(rf"(?<![\w\"]){re.escape(name)}(?![\w\"])", condition) is not None
            values = frame[column].dropna()
            if not (quoted or bare) or values.empty:
                continue
            seen.add(name)
            lines.append(
                f'{NOTE_PREFIX}Cột "{name}" trong dữ liệu chỉ nằm từ {_plain(values.min())} '
                f"đến {_plain(values.max())}."
            )
    return lines


def read_scope(load_text: Callable[[str], str], table_uri: str) -> DataScope | None:
    """Phạm vi của một bảng mart, hoặc None khi không có tệp SQL hay không được đọc."""
    if not table_uri.startswith(MART_PREFIX):
        return None
    try:
        text = load_text(recipe_of(table_uri))
    except (BoundaryViolation, ConfigError, OSError, ValueError, storage.StorageError):
        return None
    return parse_recipe(text)


def scope_sentence(scope: DataScope) -> str:
    """Câu nói phạm vi cho model: số dòng, tổng số dòng, và nguyên văn điều kiện lọc."""
    of = f" trên tổng {scope.total} dòng của bảng gốc" if scope.total else ""
    said = (
        f"Mọi chỉ số được đo trên {scope.rows} dòng{of}: các dòng thỏa điều kiện lọc "
        f"{scope.condition}. Đây KHÔNG phải toàn bộ dữ liệu. Muốn nói 'có bao nhiêu' thì "
        "dùng chỉ số rows.total (số dòng của tập này)."
    )
    if scope.rows == 0:
        said += (
            " KHÔNG có dòng nào thỏa điều kiện: câu trả lời cho 'có bao nhiêu' là 0, và "
            "không có trung bình hay chỉ số nào của nhóm này để tính."
        )
    if scope.notes:
        said += " " + " ".join(scope.notes)
    return said


def scope_text(load_text: Callable[[str], str], table_uri: str) -> str:
    """Câu phạm vi của một bảng, hoặc rỗng khi bảng không bị lọc."""
    scope = read_scope(load_text, table_uri)
    return scope_sentence(scope) if scope else ""


def shown_condition(condition: str) -> str:
    """Điều kiện viết cho người đọc: bỏ dấu nháy kép quanh tên cột."""
    return re.sub(r"\"([^\"]+)\"", r"\1", condition)
