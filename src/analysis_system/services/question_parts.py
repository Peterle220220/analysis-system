"""Một câu hỏi gõ liền một dòng thường là hai câu hỏi.

Chủ hệ thống hỏi:

    Trong tập dữ liệu, có bao nhiêu công ty bị phá sản và bao nhiêu công ty
    không phá sản? Tỷ lệ công ty phá sản chiếm bao nhiêu phần trăm tổng số mẫu?

Đó là **hai** câu hỏi. Hệ thống nhận về một chuỗi và đối xử với nó như một, nên
nó trả lời được ý này thì bỏ ý kia — và người đọc không có cách nào biết ý nào
đã được trả lời, ý nào bị bỏ.

Tách ra thì cả hai bên đều thấy: model được đưa một danh sách đánh số thay vì
một đoạn văn, và code đếm được có bao nhiêu ý cần trả lời.

Tách bằng **dấu chấm hỏi**, không bằng cách hiểu ngữ nghĩa. Dấu chấm hỏi là thứ
người dùng tự gõ ra, và nó nói đúng một điều: chỗ này kết thúc một câu hỏi. Suy
diễn xa hơn — tách theo "và", theo dấu phẩy — là bắt đầu chia một câu hỏi thành
những mảnh không ai hỏi.
"""

from __future__ import annotations

import re
from typing import Final

# Dấu kết thúc một câu hỏi. Cả hai dạng, vì bàn phím tiếng Việt gõ được cả hai.
ENDING: Final[re.Pattern[str]] = re.compile(r"[?？]")

# Ngắn hơn thế này thì nó không phải một câu hỏi, nó là phần đuôi của câu trước
# — "đúng không?", "phải không?".
MIN_LENGTH: Final[int] = 12

# Nhiều hơn thế này thì việc tách không còn giúp gì: một danh sách mười ý đọc
# lên vẫn là một danh sách mười ý.
MAX_PARTS: Final[int] = 6


def _endings(text: str) -> list[int]:
    """Vị trí những dấu chấm hỏi thật sự kết thúc một câu hỏi.

    Không phải dấu `?` nào cũng kết thúc một câu. Bộ dữ liệu dự đoán phá sản có
    một cột tên đúng là `Bankrupt?`, và người hỏi viết `(Bankrupt? = 1)` ngay
    giữa câu — tách ở đó thì một câu hỏi thành ba mảnh, hai mảnh vô nghĩa.

    Hai điều kiện, và cả hai đều đọc được bằng mắt:

    * **Không nằm trong ngoặc.** Chỗ trong ngoặc là chú thích, không phải câu.
    * **Sau nó phải là một câu mới**, tức hết chuỗi hoặc một chữ viết hoa.
      `Bankrupt? = 1` thì sau dấu hỏi là dấu bằng, không phải câu mới.
    """
    depth = 0
    found: list[int] = []
    for index, char in enumerate(text):
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(depth - 1, 0)
        elif ENDING.match(char) and depth == 0:
            rest = text[index + 1 :].lstrip()
            if not rest or rest[0].isupper():
                found.append(index)
    return found


def parts(question: str) -> tuple[str, ...]:
    """Các ý hỏi riêng biệt trong câu này.

    Returns:
        Từng ý, giữ nguyên dấu chấm hỏi. Một phần tử nghĩa là câu hỏi chỉ có
        một ý — trường hợp thường gặp, và không tách gì là đúng.
    """
    text = " ".join(str(question).split())
    if not text:
        return ()

    found: list[str] = []
    start = 0
    for at in _endings(text):
        piece = text[start : at + 1].strip()
        start = at + 1
        if len(piece) >= MIN_LENGTH:
            found.append(piece)
        elif found:
            # Duoi qua ngan de dung mot minh - "dung khong?" - thi no thuoc ve
            # cau ngay truoc no.
            found[-1] = f"{found[-1]} {piece}".strip()

    tail = text[start:].strip()
    if len(tail) >= MIN_LENGTH:
        found.append(tail)
    elif tail and found:
        found[-1] = f"{found[-1]} {tail}".strip()

    if not found:
        return (text,)
    return tuple(found[:MAX_PARTS])


def is_multi(question: str) -> bool:
    """Câu này có nhiều hơn một ý hỏi không."""
    return len(parts(question)) > 1
