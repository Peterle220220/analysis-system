"""Câu SQL này có gom dữ liệu lại không — và lúc nào thì không được phép.

Lỗi thật, đo trên chính lượt chạy của chủ hệ thống:

    SELECT poutcome, y, COUNT(*) AS num_customers
    FROM bank_additional_full GROUP BY poutcome, y

**41.176 dòng vào, 6 dòng ra.** Rồi 6 dòng đó được đẩy sang tầng thống kê, và
mọi phép kiểm chết với *"dưới 5 quan sát"*. Không có gì sai trong câu SQL; nó
sai ở chỗ **đứng trước** tầng thống kê.

Thống kê cần dữ liệu **còn tản**, từng dòng một. Một phép kiểm t so hai nhóm là
so hai đám giá trị; gom sẵn thành hai con số thì không còn gì để so, và phương
sai — thứ toàn bộ phép kiểm dựa vào — đã bị xoá trước khi ai kịp đo.

Nên khi bảng đầu ra sẽ đi vào tầng thống kê, câu SQL chỉ được **lọc và tính
thêm cột**, không được gom nhóm. Gom nhóm là việc của tầng thống kê, và nó biết
cách gom mà vẫn giữ lại thứ nó cần.

Nhận diện bằng chữ, không bằng cách hiểu SQL: `GROUP BY`, và các hàm tập hợp
đứng thành từ riêng. Chuỗi trong dấu nháy được gỡ ra trước, để một giá trị tên
`'SUM'` không bị nhầm thành một phép cộng.
"""

from __future__ import annotations

import re
from typing import Final

# Hàm gom nhiều dòng thành một. `CAST`, `CASE`, `ROUND` không nằm đây: chúng
# biến đổi từng dòng một và giữ nguyên số dòng.
AGGREGATES: Final[tuple[str, ...]] = (
    "count",
    "sum",
    "avg",
    "mean",
    "min",
    "max",
    "median",
    "stddev",
    "variance",
    "array_agg",
    "string_agg",
    "group_concat",
)

# Chuỗi trong dấu nháy đơn. Gỡ ra trước khi tìm, để `WHERE job = 'count'` không
# bị đọc thành một phép đếm.
QUOTED: Final[re.Pattern[str]] = re.compile(r"'[^']*'")

GROUP_BY: Final[re.Pattern[str]] = re.compile(r"\bgroup\s+by\b", re.IGNORECASE)


def _bare(sql: str) -> str:
    """Câu lệnh với chuỗi hằng đã gỡ ra."""
    return QUOTED.sub(" ", str(sql))


def aggregates_in(sql: str) -> tuple[str, ...]:
    """Những chỗ gom nhóm tìm thấy trong câu lệnh, theo tên.

    Returns:
        Tên các phép gom, không trùng, đã xếp. Rỗng khi câu lệnh giữ nguyên
        từng dòng.
    """
    text = _bare(sql)
    found: list[str] = []
    if GROUP_BY.search(text):
        found.append("GROUP BY")
    for name in AGGREGATES:
        # Phải là một lời gọi hàm: tên đứng riêng, rồi tới dấu mở ngoặc. Một
        # cột tên `max_duration` hay `sum_total` thì không tính.
        if re.search(rf"(?<![0-9a-z_]){name}\s*\(", text, re.IGNORECASE):
            found.append(name.upper())
    return tuple(sorted(set(found)))


def collapses_rows(sql: str) -> str:
    """Câu giải thích vì sao câu lệnh này không được đứng trước tầng thống kê.

    Returns:
        Câu nói rõ vấn đề, hoặc rỗng nếu câu lệnh giữ nguyên từng dòng.
    """
    found = aggregates_in(sql)
    if not found:
        return ""
    return (
        f"Cau lenh nay gom du lieu lai ({', '.join(found)}), nhung bang ket qua "
        "se di vao tang thong ke - noi can du lieu con tan tung dong. Gom san "
        "thi phuong sai bi xoa truoc khi ai kip do, va moi phep kiem chet vi "
        "'duoi 5 quan sat'. Chi dung WHERE de loc va CASE/CAST de tinh them "
        "cot; viec gom nhom de tang thong ke lo."
    )
