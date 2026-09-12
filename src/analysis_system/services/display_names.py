"""Tên cột tiếng Việt cho CHỮ hiển thị, chỉ ở lớp hiển thị.

Model viết câu trả lời bằng đúng tên cột trong dữ liệu ("ROA(A) before interest
and % after tax"), vì các metric key mang tên đó. Người đọc báo cáo đã khai nghĩa
tiếng Việt của từng cột trong bảng chú giải; câu trả lời phải dùng tên ấy.

Đổi bằng code, lúc hiển thị, chứ không nhờ model: lời dặn không bảo đảm được model
nghe theo, và đổi lúc hiển thị thì cả những câu trả lời đã lưu từ trước cũng đổi.
Không đụng gì phía sau: metric key, phép tính, và phần kiểm chứng con số vẫn dùng
tên gốc. Chỉ chữ đưa ra trang và ra tệp là đổi.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Final

from analysis_system.services.asked_columns import ALTERNATIVES

# Tên cột ngắn hơn thế này thì không đổi: một cột tên "y" mà đổi thì mọi chữ "y"
# đứng riêng trong câu cũng bị đổi theo.
MIN_NAME: Final[int] = 3

# Tên ngắn thì chỉ đổi khi viết đúng hoa thường: "Age" là một cột, còn một chữ
# "age" viết thường giữa câu thì chưa chắc.
CASELESS_FROM: Final[int] = 6

# Dấu kết thúc câu: tên đứng ngay sau đó thì viết hoa chữ đầu.
SENTENCE_END: Final[tuple[str, ...]] = (".", "!", "?", "\n")


def alias_of(meaning: str) -> str:
    """Tên tiếng Việt của một cột: cách gọi đầu tiên trong chú giải, viết như đã khai."""
    return next((part.strip() for part in ALTERNATIVES.split(meaning) if part.strip()), "")


def column_aliases(rows: Iterable[tuple[str, str]]) -> dict[str, str]:
    """Tên cột (đã gom khoảng trắng) và tên tiếng Việt của nó, cho mọi cột có chú giải."""
    found: dict[str, str] = {}
    for column, meaning in rows:
        name, said = " ".join(str(column).split()), alias_of(meaning)
        if name and said and said != name:
            found[name] = said
    return found


def _pattern(text: str) -> str:
    """Khớp đúng chuỗi này, cho phép khoảng trắng giữa các chữ lệch nhau."""
    return r"\s+".join(re.escape(part) for part in text.split())


def localize(text: str, aliases: Mapping[str, str]) -> str:
    """Đổi tên cột gốc trong một câu thành tên tiếng Việt.

    Tên dài đổi trước, để một tên ngắn nằm trong một tên dài không bị đổi dở. Một
    cặp model đã tự viết cả hai, như "Tỷ lệ nợ (tên gốc)", gộp lại thành một, để
    không ra "Tỷ lệ nợ (tỷ lệ nợ)". Tên đứng đầu câu thì viết hoa chữ đầu.
    """
    if not text or not aliases:
        return text
    for column, alias in sorted(aliases.items(), key=lambda item: len(item[0]), reverse=True):
        if len(column) < MIN_NAME:
            continue
        name, said = _pattern(column), _pattern(alias)

        def swap(found: re.Match[str], alias: str = alias) -> str:
            before = found.string[: found.start()].rstrip()
            if not before or before.endswith(SENTENCE_END):
                return alias[:1].upper() + alias[1:]
            return alias

        both = rf"(?<!\w)(?:{said}\s*\(\s*{name}\s*\)|{name}\s*\(\s*{said}\s*\))(?!\w)"
        text = re.sub(both, swap, text, flags=re.IGNORECASE)
        caseless = re.IGNORECASE if len(column) >= CASELESS_FROM else 0
        text = re.sub(rf"(?<!\w){name}(?!\w)", swap, text, flags=caseless)
    return text
