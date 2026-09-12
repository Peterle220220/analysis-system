"""Ngưỡng người dùng đặt trong câu hỏi phải nằm NGUYÊN VĂN trong SQL lọc.

Hỏi "tỷ lệ nợ lớn hơn 0.2" thì mệnh đề `WHERE` phải so với đúng 0.2: không làm
tròn, không đổi thành trung bình, trung vị hay phân vị. Một màng lọc lệch số là
kiểu sai đắt nhất: mọi con số sau đó đều thật, đều kiểm được, và đều là của một
nhóm khác với nhóm được hỏi.

Code không viết `WHERE` thay model: dịch một câu thành điều kiện là việc đọc hiểu.
Code KIỂM LẠI SAU, bằng chữ: con số nào đứng sau "lớn hơn", "dưới", ">"... trong
câu hỏi thì phải có mặt trong SQL. Thiếu thì trả về để model viết lại.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Final

from analysis_system.services.narrowing import fold

# Chữ so sánh, viết ở dạng đã bỏ dấu. Dài trước ngắn để "lon hon hoac bang" không
# bị khớp thành "lon hon".
WORD_COMPARATORS: Final[tuple[str, ...]] = (
    "lon hon hoac bang",
    "nho hon hoac bang",
    "khong vuot qua",
    "lon hon",
    "nho hon",
    "cao hon",
    "thap hon",
    "nhieu hon",
    "it hon",
    "vuot qua",
    "khong qua",
    "it nhat",
    "toi thieu",
    "toi da",
    "tren",
    "duoi",
)
SYMBOL_COMPARATORS: Final[tuple[str, ...]] = (">=", "<=", "=>", "=<", ">", "<", "=")

# Đơn vị viết sau con số, và số nhân của nó.
UNITS: Final[dict[str, float]] = {"nghin": 1e3, "ngan": 1e3, "k": 1e3, "trieu": 1e6, "ty": 1e9}

_WORDS = "|".join(re.escape(word) for word in WORD_COMPARATORS)
_SYMBOLS = "|".join(re.escape(symbol) for symbol in SYMBOL_COMPARATORS)
THRESHOLD: Final[re.Pattern[str]] = re.compile(
    rf"(?:(?<!\w)(?:{_WORDS})|{_SYMBOLS})\s*(-?\d+(?:[.,]\d+)?)(?!\d)\s*(%|nghin|ngan|trieu|ty|k)?(?!\w)"
)

# Số trong SQL: ngoài dấu nháy (tên cột và chuỗi ký tự không tính).
SQL_NUMBER: Final[re.Pattern[str]] = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])")
QUOTED: Final[re.Pattern[str]] = re.compile(r"\"[^\"]*\"|'[^']*'|`[^`]*`")
HAS_WHERE: Final[re.Pattern[str]] = re.compile(r"\bwhere\b", re.IGNORECASE)


@dataclass(frozen=True)
class Threshold:
    """Một ngưỡng trong câu hỏi: nguyên văn, và những giá trị số nó có thể là."""

    phrase: str
    values: frozenset[float]


def _readings(number: str) -> set[float]:
    """Mọi cách đọc hợp lý của một con số viết tay.

    "0,2" là 0.2 theo cách viết Việt. "6.819" có thể là 6819 (Việt) hoặc 6.819
    (Anh): nhận cả hai, vì chỉ cần MỘT cách đọc có mặt trong SQL là đủ.
    """
    whole, mark, part = number.replace(",", ".").partition(".")
    readings = {float(number.replace(",", "."))}
    if mark and len(part) == 3 and whole.lstrip("-") not in ("", "0"):
        readings.add(float(whole + part))
    return readings


def asked_thresholds(question: str) -> list[Threshold]:
    """Những ngưỡng số người dùng đặt trong câu hỏi."""
    found: list[Threshold] = []
    for matched in THRESHOLD.finditer(fold(question)):
        number, unit = matched.group(1), matched.group(2) or ""
        values: set[float] = set()
        for reading in _readings(number):
            values.add(reading)
            if unit == "%":
                values.add(reading / 100)
            elif unit in UNITS:
                values.add(reading * UNITS[unit])
        found.append(Threshold(" ".join(matched.group(0).split()), frozenset(values)))
    return found


def sql_numbers(sql: str) -> set[float]:
    """Các hằng số trong câu SQL, bỏ qua số nằm trong tên cột hay chuỗi ký tự."""
    return {float(number) for number in SQL_NUMBER.findall(QUOTED.sub(" ", sql))}


def filters(sql: str) -> bool:
    """SQL này có mệnh đề WHERE không."""
    return HAS_WHERE.search(QUOTED.sub(" ", sql)) is not None


def missing_thresholds(question: str, sql: str) -> list[str]:
    """Ngưỡng nào của câu hỏi không có mặt trong SQL."""
    present = sql_numbers(sql)
    return [
        threshold.phrase
        for threshold in asked_thresholds(question)
        if not any(
            math.isclose(value, number, rel_tol=1e-9, abs_tol=1e-12)
            for value in threshold.values
            for number in present
        )
    ]


def threshold_warning(question: str, sql: str) -> str:
    """Câu gửi lại cho model khi SQL lọc không dùng đúng ngưỡng người dùng đặt."""
    missing = missing_thresholds(question, sql)
    if not missing:
        return ""
    return (
        f"cau hoi dat nguong {', '.join(repr(phrase) for phrase in missing)} nhung SQL loc "
        "khong dung dung con so do: phai dua CHINH XAC con so nguoi dung dua vao menh de "
        "WHERE, khong lam tron, khong doi thanh trung binh, trung vi, phan vi hay mot so khac"
    )
