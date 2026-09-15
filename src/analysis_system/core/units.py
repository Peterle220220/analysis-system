"""Đơn vị hệ thống tự chèn — và lúc nào thì không nên chèn.

Câu thật đã hiện ra trên màn hình: *"40 % số người trả lời (16 **dòng người**
tham gia)"*.

Chỉ số `rows.total` mang đơn vị `dòng`, và code luôn chèn đơn vị ngay sau con
số. Model thì viết mẫu câu `"{rows.total} người tham gia"` — nó đã tự nói cái
đang được đếm là gì. Hai danh từ dính vào nhau thành một cụm không ai đọc được.

Đơn vị tồn tại để một con số trần không mơ hồ. Model đã viết danh từ ngay sau
đó thì con số không còn trần, nên đơn vị hết việc.

Nhưng chỉ với **danh từ đếm** — `dòng`, `nhóm`, `lần`, `từ`. Ký hiệu đo như `%`
thì không bao giờ đụng: không ai đọc *"40 %"* mà tưởng `%` là danh từ.

Và chỉ khi chữ đi ngay sau thật sự là danh từ của model. `"{x.count} trên tổng
số"` mà bỏ `lần` đi thì thành *"5 trên tổng số"* — mất thông tin. Nên có một
danh sách nhỏ các từ nối: gặp chúng thì giữ đơn vị lại. Danh sách ngắn và đọc
được, và nó nghiêng về phía **giữ** — bỏ nhầm thì mất nghĩa, còn giữ nhầm thì
chỉ thừa một chữ.
"""

from __future__ import annotations

import re
from typing import Final

# Từ nối, giới từ, động từ hay đứng ngay sau một con số. Gặp chúng thì chữ tiếp
# theo không phải danh từ của model, nên đơn vị vẫn còn việc.
CONNECTIVES: Final[frozenset[str]] = frozenset(
    {
        "trên",
        "trong",
        "ngoài",
        "dưới",
        "với",
        "của",
        "và",
        "là",
        "cho",
        "từ",
        "theo",
        "ở",
        "tại",
        "sau",
        "trước",
        "khi",
        "nếu",
        "thì",
        "mà",
        "hơn",
        "kém",
        "so",
        "chiếm",
        "đạt",
        "có",
        "được",
        "này",
        "đó",
        "nên",
        "vì",
        "do",
        "bằng",
        "gần",
        "khoảng",
        "tức",
        "nghĩa",
        "tương",
        "cùng",
        "một",
        "hai",
        "ba",
        "các",
        "những",
        "mỗi",
        "cả",
        "toàn",
    }
)

# Chữ đầu tiên sau chỗ chèn. Dấu câu dừng lại ở đây, nên `"... {x}."` không
# tính là có danh từ đi sau.
NEXT_WORD: Final[re.Pattern[str]] = re.compile(r"^\s+([^\W\d_]+)", re.UNICODE)


def is_counting_noun(unit: str) -> bool:
    """Đơn vị này là danh từ đếm, hay là ký hiệu đo.

    Danh từ đếm gọi tên thứ đang được đếm, nên nó tranh chỗ với danh từ model
    tự viết. Ký hiệu như `%` thì không tranh với gì cả.
    """
    return bool(unit) and any(character.isalpha() for character in unit)


def keeps_unit(unit: str, tail: str) -> bool:
    """Có nên chèn đơn vị này vào không, khi câu còn chạy tiếp bằng `tail`.

    Args:
        unit: đơn vị của chỉ số.
        tail: phần mẫu câu nằm ngay sau chỗ con số được chèn vào.

    Returns:
        False chỉ khi cả ba điều cùng đúng: đơn vị là danh từ đếm, ngay sau đó
        là một chữ, và chữ đó không phải từ nối. Ba điều - vì mặc định là giữ.
    """
    if not unit or not is_counting_noun(unit):
        return True
    matched = NEXT_WORD.match(tail)
    if matched is None:
        # Hết câu, hoặc dấu câu ngay sau. Con số đang trần, đơn vị còn việc.
        return True
    word = matched.group(1).lower()
    if word in CONNECTIVES:
        return True
    # Model tự gõ đúng đơn vị đó thì đã có `without_doubled_units` lo, và ở đây
    # giữ lại cũng ra cùng kết quả.
    return word == unit.lower()
