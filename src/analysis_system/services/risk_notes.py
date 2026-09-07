"""Rủi ro về độ tin cậy — do code gắn vào câu trả lời, không nhờ model nhớ.

Cảnh báo kiểu *"nhóm này chỉ có 2 dòng, quá ít để nói gì"* trước nay nằm trong
`khong_xac_lap_duoc`, kèm một lời dặn trong prompt: *"nếu nó chạm tới câu hỏi thì
PHẢI nói rõ"*. Lời dặn trong prompt là thứ dự án này đã đo là **không ăn thua** —
cùng một prompt đã ghi *"tuyệt đối không gõ số trực tiếp"* và model vẫn gõ, năm
lần trong bốn lượt chạy.

Nên phần này không nhờ vả gì cả. Code lọc ra những dòng nói về **độ tin cậy**,
và gắn thẳng vào câu trả lời. Model vẫn được đọc chúng và vẫn nên đan vào lời
văn — nhưng nếu nó quên, người đọc vẫn thấy.

Ranh giới: chỉ những dòng nói *"con số này mỏng tới mức đừng tin vội"*. Những
dòng khác trong `khong_xac_lap_duoc` — hệ thống tự giới hạn để tránh p-hacking,
hay đang chờ người dùng khai cấu hình — là chuyện khác, và gộp chung lại thì
người đọc thôi đọc cả cụm.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable
from typing import Final

# Dấu hiệu của một dòng nói về ĐỘ TIN CẬY của con số, không phải về phạm vi
# hay cấu hình. Viết cả hai dạng có dấu và không dấu vì các dòng này đến từ
# nhiều tầng khác nhau và không phải tầng nào cũng giữ dấu.
RISK_MARKS: Final[tuple[str, ...]] = (
    "qua it de noi gi",
    "du lon",
    "can it nhat",
    "khong doi gia tri",
    "bang rong",
    "chi co mot chu ky",
    "mau qua nho",
)


def fold(text: str) -> str:
    """Chữ thường, bỏ dấu — để nhận ra một dòng dù nó có dấu hay không."""
    stripped = "".join(
        char for char in unicodedata.normalize("NFD", text) if unicodedata.category(char) != "Mn"
    )
    return stripped.replace("đ", "d").replace("Đ", "D").lower()


def is_risk(line: str) -> bool:
    """Dòng này có nói rằng con số mỏng tới mức đừng tin vội không."""
    folded = fold(line)
    return any(mark in folded for mark in RISK_MARKS)


def risks(lines: Iterable[str]) -> tuple[str, ...]:
    """Những dòng cảnh báo độ tin cậy, giữ nguyên thứ tự và bỏ trùng.

    Bỏ trùng vì cùng một cảnh báo hay đi ra từ nhiều phép kiểm - đọc lại lần thứ
    năm không thêm được gì và làm người ta thôi đọc cả cụm.
    """
    seen: list[str] = []
    for line in lines:
        text = str(line).strip()
        if text and is_risk(text) and text not in seen:
            seen.append(text)
    return tuple(seen)
