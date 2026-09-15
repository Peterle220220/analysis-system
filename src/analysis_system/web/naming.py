"""Cách mã lần chạy nói lượt hỏi thuộc bộ dữ liệu nào.

`kt1__q4` nói đủ mọi thứ một chương trình cần: bộ dữ liệu nào, lượt hỏi thứ mấy, và
cách tìm lại nó trên đĩa. Tên hiển thị cho người đọc do giao diện Next dựng; phần đặt
tên kiểu cũ ở đây đi theo giao diện HTML đã bỏ (plans/refactor-ddd.md).
"""

from __future__ import annotations

from typing import Final

# Ngăn cách giữa lần làm sạch và lượt hỏi đặt trên nó: `emotions__q3`.
ROUND_MARK: Final[str] = "__q"
