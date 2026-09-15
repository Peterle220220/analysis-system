"""Những gì câu hỏi gọi tên trong bảng: giá trị một cột, mốc thời gian, "từng" kỳ, phép chia.

Dùng chung cho Lọc & Tính (A7, `point_values`) và phép xoay ngang tạm thời (A4,
`cross_row`): cả hai phải đọc câu hỏi giống hệt nhau, nếu không thì A4 dựng một bảng mà
A7 không nhận ra là bảng của câu hỏi đó.

Chỉ so chữ, không đoán nghĩa. Câu hỏi gõ có dấu thì so có dấu: "năm 2024" không khớp
nhóm "Nam", "mối quan hệ" không phải "mỗi". Câu hỏi gõ không dấu thì so không dấu.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from typing import Any, Final

import pandas as pd

from analysis_system.domains.ai_planner.shortlist import fold

# Cot co nhieu gia tri hon the nay khong phai cot nhom de tra cuu.
MAX_LABELS: Final[int] = 5000
# "Tung ky" chi co nghia khi so ky dem duoc tren mot trang.
MAX_EACH: Final[int] = 24
# Mot cot so chi duoc coi la cot nhom (nam) khi moi gia tri la mot nam.
YEAR_RANGE: Final[tuple[int, int]] = (1900, 2100)
MIN_LABEL_CHARS: Final[int] = 2
TWO_DIGIT_YEAR: Final[int] = 100

EACH_MARKED: Final[tuple[str, ...]] = (
    "từng",
    "mỗi",
    "hàng quý",
    "hàng tháng",
    "hàng năm",
    "each",
    "every",
    "per",
)
EACH_PLAIN: Final[tuple[str, ...]] = (
    "tung",
    "moi",
    "hang quy",
    "hang thang",
    "hang nam",
    "each",
    "every",
    "per",
)
RATIO_MARKED: Final[tuple[str, ...]] = ("trên", "chia", "over", "divided by")
RATIO_PLAIN: Final[tuple[str, ...]] = ("tren", "chia", "over", "divided by")

# Moc thoi gian doc tu chu da bo dau: "Q2-2026" -> "q2 2026", "Tháng 12/2025" ->
# "thang 12 2025". Tra ve (nam, thang cuoi ky) de sap theo thoi gian.
_PERIODS: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    (re.compile(r"^(?:q|quy)\s?([1-4])\s(\d{2}|\d{4})$"), "quarter"),
    (re.compile(r"^(\d{4})\s(?:q|quy)\s?([1-4])$"), "year_quarter"),
    (re.compile(r"^(?:h|ban nien)\s?([12])\s(\d{4})$"), "half"),
    (re.compile(r"^(?:t|thang)\s?(\d{1,2})\s(\d{2}|\d{4})$"), "month"),
    (re.compile(r"^(\d{1,2})\s(\d{4})$"), "month"),
    (re.compile(r"^(\d{4})\s(\d{1,2})$"), "year_month"),
    (re.compile(r"^(?:nam\s|fy\s?)?(\d{4})$"), "year"),
)

# (vi tri bat dau, vi tri ket thuc, gia tri) cua mot ten trong cau hoi da chuan hoa.
Hit = tuple[int, int, object]


def has_marks(text: str) -> bool:
    """Câu này có gõ dấu tiếng Việt không."""
    plain = unicodedata.normalize("NFD", text)
    return any(unicodedata.category(char) == "Mn" for char in plain) or "đ" in text.lower()


def spoken(text: object, *, marked: bool) -> str:
    """Chữ để so: giữ dấu (marked) hoặc bỏ dấu, chữ thường, chỉ còn chữ và số."""
    if marked:
        lowered = unicodedata.normalize("NFC", str(text)).lower()
        return " ".join(re.findall(r"\w+", lowered))
    return " ".join(re.findall(r"[a-z0-9]+", fold(str(text))))


def asked_text(question: str) -> tuple[str, bool]:
    """Câu hỏi đã chuẩn hoá, bọc một dấu cách hai đầu để so trọn từ; và có dấu hay không."""
    marked = has_marks(question)
    return f" {spoken(question, marked=marked)} ", marked


def _year(text: str) -> int:
    number = int(text)
    return number + 2000 if number < TWO_DIGIT_YEAR else number


def period_key(value: object) -> tuple[int, int] | None:
    """(năm, tháng cuối kỳ) của một mốc thời gian, hoặc None khi nó không phải mốc."""
    text = spoken(value, marked=False)
    for pattern, kind in _PERIODS:
        found = pattern.match(text)
        if not found:
            continue
        first, *rest = [part or "" for part in found.groups()]
        if kind == "quarter":
            return _year(rest[0]), int(first) * 3
        if kind == "year_quarter":
            return _year(first), int(rest[0]) * 3
        if kind == "half":
            return _year(rest[0]), int(first) * 6
        if kind in ("month", "year_month"):
            year, month = (rest[0], first) if kind == "month" else (first, rest[0])
            return (_year(year), int(month)) if 1 <= int(month) <= 12 else None
        return _year(first), 12
    return None


def all_periods(values: Iterable[object]) -> bool:
    """Mọi giá trị đều là mốc thời gian (và có ít nhất một)."""
    items = list(values)
    return bool(items) and all(period_key(value) is not None for value in items)


def by_time(values: Sequence[object]) -> list[object]:
    """Sắp theo thời gian khi mọi giá trị là mốc; không thì giữ nguyên thứ tự."""
    items = list(values)
    if all_periods(items):
        return sorted(items, key=lambda value: period_key(value) or (0, 0))
    return items


def candidates(series: pd.Series[Any]) -> list[object]:
    """Những giá trị một câu hỏi có thể gọi tên trong cột này."""
    values = series.dropna()
    if values.empty or pd.api.types.is_bool_dtype(values):
        return []
    if pd.api.types.is_numeric_dtype(values):
        numbers = pd.to_numeric(values, errors="coerce").dropna()
        low, high = YEAR_RANGE
        whole = (numbers == numbers.round()) & numbers.between(low, high)
        return [int(number) for number in numbers.unique()] if bool(whole.all()) else []
    unique = list(values.unique())
    return [] if len(unique) > MAX_LABELS else unique


def _outermost(hits: list[Hit]) -> list[Hit]:
    # "lợi nhuận sau thuế" nằm trong "lợi nhuận sau thuế của cổ đông": câu hỏi gọi cái
    # dài thì cái ngắn không phải là cái được gọi.
    return sorted(
        (
            hit
            for hit in hits
            if not any(
                other is not hit
                and other[0] <= hit[0]
                and hit[1] <= other[1]
                and other[1] - other[0] > hit[1] - hit[0]
                for other in hits
            )
        ),
        key=lambda hit: hit[0],
    )


def _find(asked: str, marked: bool, items: Iterable[object]) -> list[Hit]:
    hits: list[Hit] = []
    for item in items:
        said = spoken(item, marked=marked)
        if len(said.replace(" ", "")) < MIN_LABEL_CHARS:
            continue
        start = asked.find(f" {said} ")
        if start >= 0:
            hits.append((start, start + len(said) + 1, item))
    return _outermost(hits)


def named_positions(frame: pd.DataFrame, question: str) -> dict[str, list[Hit]]:
    """Với mỗi cột, những giá trị câu hỏi gọi đích danh, kèm vị trí, theo thứ tự trong câu."""
    asked, marked = asked_text(question)
    found: dict[str, list[Hit]] = {}
    for column in frame.columns:
        hits = _find(asked, marked, candidates(frame[column]))
        if hits:
            found[str(column)] = hits
    return found


def named_values(frame: pd.DataFrame, question: str) -> dict[str, list[object]]:
    """Với mỗi cột, những giá trị câu hỏi gọi đích danh, theo thứ tự trong câu."""
    return {
        column: [hit[2] for hit in hits]
        for column, hits in named_positions(frame, question).items()
    }


def names_in_order(question: str, names: Iterable[object]) -> list[Hit]:
    """Những tên (thường là tên cột) câu hỏi gọi trọn, theo thứ tự trong câu."""
    asked, marked = asked_text(question)
    return _find(asked, marked, names)


def asks_each(question: str) -> bool:
    """Câu hỏi đòi từng mốc một: "từng quý", "mỗi kỳ", "hàng tháng", "each", "per"."""
    asked, marked = asked_text(question)
    return any(f" {word} " in asked for word in (EACH_MARKED if marked else EACH_PLAIN))


def is_ratio_gap(question: str, first: Hit, second: Hit) -> bool:
    """Giữa hai tên có một phép chia không: "A trên B", "A chia cho B", "A/B", "ratio of A to B"."""
    asked, marked = asked_text(question)
    gap = f" {asked[first[1] : second[0]].strip()} "
    if any(f" {word} " in gap for word in (RATIO_MARKED if marked else RATIO_PLAIN)):
        return True
    if not gap.strip() and "/" in question:
        return True
    return " ratio " in asked and " to " in gap


def period_columns(frame: pd.DataFrame) -> list[str]:
    """Cột mà mọi giá trị là một mốc thời gian, và số mốc đếm được (2 tới MAX_EACH)."""
    found: list[str] = []
    for column in frame.columns:
        labels = candidates(frame[column])
        if 2 <= len(labels) <= MAX_EACH and all_periods(labels):
            found.append(str(column))
    return found
