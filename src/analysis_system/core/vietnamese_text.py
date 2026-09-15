"""Chữ tiếng Việt viết mỗi nơi một kiểu, và số viết bằng chữ.

Dữ liệu Kaggle sạch nên hai chuyện này chưa từng lộ ra. Dữ liệu thị trường Việt
thì lộ ngay dòng đầu — chủ hệ thống nói thẳng: *"chữ, số nhiều khi không theo
quy luật"*.

Đo trên đúng bốn hình dạng đó, hệ thống trước khi có tệp này phân biệt được
**bảy nhóm** trên một cột đáng lẽ có **hai**:

    Khách hàng · khach hang · KHÁCH HÀNG · Khách  hàng · Đại lý · dai ly

Và `một`, `hai`, `ba` thì không phải số, nên cả cột bị từ chối.

## Hai việc, hai bản chất khác nhau

**Gộp biến thể** — hoàn toàn xác định, và **không có một từ tiếng Việt nào được
viết cứng trong đây**. Nó không biết "khách hàng" nghĩa là gì, cũng không cần
biết: bỏ dấu, hạ chữ thường, gom khoảng trắng, rồi hai ô nào ra cùng một khoá
thì là một. Luật ấy chạy y hệt trên "Đại lý", "Nhà cung cấp", hay bất cứ chữ
nào chưa ai nghĩ tới.

**Số viết bằng chữ** — chỗ này *phải* có danh sách, nhưng nó là **hệ đếm tiếng
Việt**, một tập đóng và hữu hạn: mười chữ số, bốn bậc, vài biến thể đọc trại
(`mốt`, `lăm`, `tư`). Không phải từ vựng của một bộ dữ liệu nào cả — nó đúng
với mọi bộ, hôm nay và mai sau.

## Cái nào được giữ làm tên hiển thị

Chủ hệ thống hỏi đúng chỗ khó: *"chữ nào mang ý nghĩa nhiều nhất"*. Trả lời
được mà không cần từ điển, vì **dấu là thông tin một chiều** — từ "Khách hàng"
luôn suy ra được "khach hang", còn chiều ngược lại thì không. Nên bản có dấu
thắng, rồi mới tới cách viết hoa, rồi tới cái xuất hiện nhiều nhất.

Và mọi ô bị đổi đều được ghi lại từng dòng một. Gộp nhầm hai nhóm thật thành
một là mất dữ liệu, nên nó phải soi ngược được.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Final

# --- bỏ dấu, nhận ra chữ có dấu -------------------------------------------------------
#
# Hai hàm này từng nằm trong `relevance` (chấm câu trả lời theo câu hỏi), và tệp này
# import ngược lên đó. Chúng không phải nghiệp vụ chấm điểm: chỉ là cách đọc chữ tiếng
# Việt, dùng chung cho khớp câu hỏi, gộp biến thể, chú giải. Nên chúng ở đây, tầng dưới
# cùng, và `relevance` gọi xuống (plans/refactor-ddd.md, Phase 2).


def fold(text: str) -> str:
    """Lowercase, strip diacritics, keep only words.

    Diacritics are folded because the two sides rarely agree about them: a
    person types "thoi quen hoc tap" and the model writes "thói quen học tập",
    and to a word counter those share nothing at all. Folding loses a little
    precision - Vietnamese diacritics do distinguish words - and gains far more
    than it loses on input that mixes both.
    """
    plain = unicodedata.normalize("NFD", text.lower())
    plain = "".join(char for char in plain if unicodedata.category(char) != "Mn")
    return " ".join(re.findall(r"[a-z0-9_]+", plain.replace("đ", "d")))


def accented(text: str) -> bool:
    """Whether this text is written with Vietnamese diacritics."""
    return any(unicodedata.category(char) == "Mn" for char in unicodedata.normalize("NFD", text))


# --- gộp biến thể cách viết -------------------------------------------------------


def variant_key(text: str) -> str:
    """Khoá để hai cách viết của cùng một chữ gặp nhau.

    Dùng lại đúng phép gấp của tầng khớp câu hỏi. Hai bản sao của một luật là
    hai câu trả lời đang chờ để mâu thuẫn với nhau — mà ở đây thì mâu thuẫn ấy
    có nghĩa là câu hỏi tìm ra một nhóm mà bảng dữ liệu không có.
    """
    return fold(str(text))


def _informativeness(form: str, seen: int) -> tuple[int, int, int, str]:
    """Chấm một cách viết: cách nào giữ được nhiều thông tin nhất.

    Dấu đứng trước tất cả, vì nó là thông tin **một chiều**: từ "Khách hàng"
    luôn suy ra được "khach hang", còn từ "khach hang" thì không ai dựng lại
    được dấu. Chọn bản mất dấu là vứt đi thứ không lấy lại được.

    Rồi mới tới cách viết hoa — CHỮ HOA TOÀN BỘ thường là do gõ ẩu hoặc do hệ
    thống nguồn, ít khi là cách người ta thật sự viết. Rồi tới cái xuất hiện
    nhiều nhất, và cuối cùng xếp theo chữ cái để hai lần chạy cho cùng kết quả.
    """
    letters = [char for char in form if char.isalpha()]
    all_upper = bool(letters) and all(char.isupper() for char in letters)
    mixed = any(char.isupper() for char in letters) and not all_upper
    case_score = 2 if mixed else (0 if all_upper else 1)
    return (int(accented(form)), case_score, seen, form)


def best_form(counts: Mapping[str, int]) -> str:
    """Cách viết được giữ lại làm tên hiển thị của cả nhóm."""
    return max(counts, key=lambda form: _informativeness(form, counts[form]))


def canonical_forms(values: Iterable[str]) -> dict[str, str]:
    """Mỗi cách viết trỏ tới cách viết đại diện cho nhóm của nó.

    Returns:
        Chỉ những cách viết **sẽ bị đổi**. Rỗng nghĩa là cột này vốn đã thống
        nhất — trường hợp thường gặp, và không đổi gì là đúng.
    """
    groups: dict[str, Counter[str]] = {}
    for value in values:
        text = str(value)
        key = variant_key(text)
        if not key:
            # Ô rỗng, hoặc chỉ có dấu câu. Không có gì để gộp, và gộp chúng lại
            # với nhau là trộn những ô không liên quan.
            continue
        groups.setdefault(key, Counter())[text] += 1

    changes: dict[str, str] = {}
    for counts in groups.values():
        if len(counts) < 2:
            continue
        keep = best_form(counts)
        for form in counts:
            if form != keep:
                changes[form] = keep
    return changes


# --- số viết bằng chữ -------------------------------------------------------------
#
# Đây là HỆ ĐẾM tiếng Việt, không phải từ vựng của một bộ dữ liệu: mười chữ số,
# bốn bậc, và vài biến thể đọc trại. Một tập đóng, đúng với mọi bộ dữ liệu.
#
# Khoá viết ở dạng đã bỏ dấu, nên "một" và "mot" đều tra được — người nhập liệu
# gõ kiểu nào cũng vậy.

DIGITS: Final[dict[str, int]] = {
    "khong": 0,
    "mot": 1,  # một, và "mốt" trong "hai mươi mốt"
    "hai": 2,
    "ba": 3,
    "bon": 4,
    "tu": 4,  # "hai mươi tư"
    "nam": 5,
    "lam": 5,  # "mười lăm"
    "nham": 5,
    "sau": 6,
    "bay": 7,  # bảy, và "bẩy"
    "tam": 8,
    "chin": 9,
}

# Bậc, xếp từ lớn xuống — cắt ở bậc lớn nhất trước thì phần còn lại tự đúng.
SCALES: Final[tuple[tuple[str, int], ...]] = (
    ("ty", 1_000_000_000),
    ("ti", 1_000_000_000),
    ("trieu", 1_000_000),
    ("nghin", 1_000),
    ("ngan", 1_000),
)

HUNDRED: Final[str] = "tram"
TEN: Final[str] = "muoi"  # cả "mười" lẫn "mươi" đều gấp về đây
FILLERS: Final[frozenset[str]] = frozenset({"linh", "le"})

_ONLY_DIGITS: Final[re.Pattern[str]] = re.compile(r"^\d+$")


def _digit(token: str) -> int | None:
    if _ONLY_DIGITS.match(token):
        return int(token)
    return DIGITS.get(token)


def _under_hundred(tokens: list[str]) -> int | None:
    """Phần dưới một trăm: `mười lăm`, `hai mươi mốt`, `linh năm`."""
    if not tokens:
        return 0
    if tokens[0] in FILLERS:
        # "một trăm linh năm" - chỗ hàng chục để trống.
        return _digit(tokens[1]) if len(tokens) == 2 else None

    if TEN in tokens:
        at = tokens.index(TEN)
        before, after = tokens[:at], tokens[at + 1 :]
        # "mười" đứng đầu là số 10; "hai mươi" là hai chục. Cùng một chữ sau khi
        # bỏ dấu, phân biệt được bằng chỗ đứng chứ không cần dấu.
        if not before:
            tens = 10
        elif len(before) == 1 and (value := _digit(before[0])) is not None:
            tens = value * 10
        else:
            return None
        if not after:
            return tens
        if len(after) == 1 and (unit := _digit(after[0])) is not None:
            return tens + unit
        return None

    if len(tokens) == 1:
        return _digit(tokens[0])
    return None


def _under_thousand(tokens: list[str]) -> int | None:
    if HUNDRED not in tokens:
        return _under_hundred(tokens)
    at = tokens.index(HUNDRED)
    before, after = tokens[:at], tokens[at + 1 :]
    if not before:
        hundreds = 1
    elif len(before) == 1 and (value := _digit(before[0])) is not None:
        hundreds = value
    else:
        return None
    rest = _under_hundred(after)
    return None if rest is None else hundreds * 100 + rest


def _parse(tokens: list[str]) -> int | None:
    if not tokens:
        return None
    for word, size in SCALES:
        if word in tokens:
            at = tokens.index(word)
            before, after = tokens[:at], tokens[at + 1 :]
            head = 1 if not before else _parse(before)
            tail = 0 if not after else _parse(after)
            if head is None or tail is None:
                return None
            return head * size + tail
    return _under_thousand(tokens)


def number_from_words(text: str) -> int | None:
    """Số mà cụm chữ này nói tới, hoặc None nếu nó không phải một con số.

    Nhận cả có dấu lẫn không dấu, và nhận cả cách viết trộn: `1 triệu`.

    None là câu trả lời an toàn và nó được dùng nhiều: chỉ những ô mà **cả ô**
    đọc lên là một con số mới được đổi. `một số khách hàng` không đọc ra số nào,
    nên nó không bị đụng tới.
    """
    tokens = fold(str(text)).split()
    if not tokens:
        return None
    if any(_ONLY_DIGITS.match(token) is None and token not in _KNOWN for token in tokens):
        return None
    return _parse(tokens)


_KNOWN: Final[frozenset[str]] = (
    frozenset(DIGITS) | {word for word, _ in SCALES} | {HUNDRED, TEN} | FILLERS
)
