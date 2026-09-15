"""Dấu câu hiển thị cho người đọc.

Chủ hệ thống không muốn dấu gạch ngang dài (em dash) xuất hiện trong hệ thống:
trông không chuyên nghiệp. Chữ của chính hệ thống đã được viết lại không dùng
nó; chỗ này lo phần chữ do model viết, vì lời dặn không bảo đảm được model
nghe theo.
"""

from __future__ import annotations

import re
from typing import Final

# Dựng bằng mã ký tự, để chính tệp này không chứa dấu đó trong một chuỗi chạy thật.
EM_DASH: Final[str] = chr(8212)
_AROUND: Final[re.Pattern[str]] = re.compile(rf"\s*{EM_DASH}\s*")


def plain_dashes(text: str) -> str:
    """Thay dấu gạch ngang dài bằng dấu phẩy; bỏ dấu phẩy thừa ở hai đầu."""
    return _AROUND.sub(", ", str(text)).strip(" ,")
