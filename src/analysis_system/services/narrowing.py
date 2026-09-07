"""Câu hỏi đòi thu hẹp dữ liệu — SQL có thu hẹp thật không?

Lỗi thật đã xảy ra. Chủ hệ thống hỏi *"tìm những người kỳ vọng lợi nhuận cao
nhất ('20%-30%' hoặc '30%-40%')"*, và SQL viết ra là:

    SELECT ..., CASE WHEN Expect IN ('20%-30%','30%-40%')
                THEN TRUE ELSE FALSE END AS high_expect_flag
    FROM finance_data
    -- 40 dong ra

Nó **thêm một cột cờ** thay vì **lọc bằng `WHERE`**. Cả 40 dòng đi tiếp, và mọi
con số sau đó là của toàn bộ tệp chứ không phải của nhóm được hỏi. Câu trả lời
*"62.50% chọn Returns"* là của cả 40 người, và nó được trình bày như câu trả lời
về nhóm kỳ vọng lợi nhuận cao. Không ai bị báo gì.

`40 dòng vào → 40 dòng ra` lẽ ra phải là một tiếng chuông.

Code **không** quyết được `WHERE` nào — dịch một câu tiếng Việt thành mệnh đề
SQL là việc đọc hiểu, và đó là việc của model. Cái code làm được là **kiểm lại
sau**: chỉ dẫn đòi thu hẹp, SQL không có `WHERE`, và số dòng không đổi — ba điều
đó cùng lúc thì gần như chắc chắn là hỏng.

Đối chiếu bằng **chữ**, cố ý. Cùng lý do `moored_needs` đã chọn như vậy: người ta
gõ ra ý định bằng những từ rất cụ thể, và đoán nghĩa ở đây là thêm một chỗ để
đoán sai.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final

# Từ báo hiệu câu hỏi muốn một TẬP CON, không phải cả bảng. Viết cả hai dạng có
# dấu và không dấu vì chỉ dẫn đi qua nhiều tay và không phải chỗ nào cũng giữ dấu.
NARROWING: Final[tuple[str, ...]] = (
    "loc",
    "chi nhung",
    "chi lay",
    "chi tinh",
    "nhung nguoi",
    "nhom nguoi",
    "tap con",
    "gioi han o",
    "trong so nhung",
    "filter",
    "subset",
    "only",
)

# Một mệnh đề thu hẹp thật. `WHERE` là cách thẳng nhất; `HAVING` và `QUALIFY`
# cũng thu hẹp, và một truy vấn gộp nhóm thì tự nó đã hẹp lại rồi.
NARROWS: Final[tuple[str, ...]] = ("where", "having", "qualify", "group by")


def fold(text: str) -> str:
    """Chữ thường, bỏ dấu — để so ý định mà không vướng dấu tiếng Việt."""
    stripped = "".join(
        char for char in unicodedata.normalize("NFD", text) if unicodedata.category(char) != "Mn"
    )
    return stripped.replace("đ", "d").replace("Đ", "D").lower()


def asks_for_a_subset(instruction: str) -> bool:
    """Chỉ dẫn này có đòi thu hẹp dữ liệu không."""
    folded = fold(instruction)
    return any(mark in folded for mark in NARROWING)


def narrows(sql: str) -> bool:
    """SQL này có thu hẹp gì không.

    Chỉ nhìn từ khóa, không phân tích cú pháp. Một `WHERE` nằm trong chuỗi ký tự
    sẽ bị tính nhầm là có thu hẹp - và nhầm về phía đó là nhầm an toàn: bỏ sót
    một cảnh báo còn hơn báo oan một truy vấn đúng rồi bắt viết lại.
    """
    lowered = " ".join(sql.lower().split())
    return any(re.search(rf"\b{mark}\b", lowered) for mark in NARROWS)


def missed_the_filter(instruction: str, sql: str, rows_in: int, rows_out: int) -> str:
    """Câu cảnh báo khi lẽ ra phải thu hẹp mà không thu hẹp.

    Cả ba điều kiện phải cùng đúng. Thiếu một điều là đủ để im lặng: báo oan một
    truy vấn đúng rồi bắt model viết lại là đốt tiền và làm hỏng một kết quả tốt.

    Returns:
        Câu để đưa vào `RetryFeedback`, hoặc rỗng khi không có gì đáng nói.
    """
    if not asks_for_a_subset(instruction):
        return ""
    if narrows(sql):
        return ""
    if rows_in <= 0 or rows_out != rows_in:
        return ""
    return (
        f"cau hoi doi thu hep du lieu nhung SQL giu nguyen {rows_out} dong - "
        "dung menh de WHERE de loc, dung them mot cot co roi de nguyen ca bang: "
        "moi con so sau do se la cua ca tep chu khong phai cua nhom duoc hoi"
    )
