"""Lọc & Tính: giá trị của một chỉ số tại những mốc câu hỏi gọi tên, và chênh lệch giữa chúng.

Hỏi "lợi nhuận sau thuế Q2-2026 so với Q1-2026, chênh lệch bao nhiêu" là hỏi một phép
lọc và một phép trừ. Tầng thống kê không có phép đó: nó đo trung bình, tương quan, so
sánh nhóm, những thứ dành cho một mẫu nhiều dòng. Trên báo cáo tài chính MBB (4 kỳ) nó
đo tám cặp tương quan không ai hỏi và không một con số nào gắn với tên kỳ, nên câu trả
lời thành "chưa nói được gì" (bao_cao_tai_chinh_mb_cua_4_quy_gan_nhat__q1, 2026-09-15).

Ở đây code đọc câu hỏi, tìm những GIÁ TRỊ của cột nhóm được gọi đích danh ("Q2-2026",
"Lợi nhuận sau thuế", "North"), lọc đúng những dòng đó và tính. Không model nào chạm vào
con số. Tên khoá theo mẫu `<chỉ số>.<phép>.by.<cột>.<nhãn>`, nên nhãn (kể cả nhãn có chữ
số như Q2-2026) được nói ra bằng `{ten:...}` và không bị coi là số gõ tay.

Hai điều không đoán:

* Nhiều dòng cùng một nhãn thì cộng (doanh thu một tháng là tổng các đơn), trừ khi câu
  hỏi nói "trung bình"; khoá nói rõ đã cộng (`sum`) hay lấy trung bình (`mean`).
* Câu hỏi gõ có dấu thì so có dấu: "năm 2024" không được khớp vào nhóm "Nam".
"""

from __future__ import annotations

import itertools
import re
import unicodedata
from typing import Any, Final

import pandas as pd

from analysis_system.contracts.agents import MetricValue
from analysis_system.services.shortlist import fold, named_in

DECIMALS: Final[int] = 4
# Cot co nhieu gia tri hon the nay khong phai cot nhom de tra cuu.
MAX_LABELS: Final[int] = 5000
# Cau hoi khong goi ten cot so nao ma bang co nhieu hon chung nay cot so thi khong doan.
MAX_MEASURES: Final[int] = 5
MAX_COMBINATIONS: Final[int] = 10
# Mot cot so chi duoc coi la cot nhom (nam) khi moi gia tri la mot nam.
YEAR_RANGE: Final[tuple[int, int]] = (1900, 2100)
MEAN_WORDS: Final[tuple[str, ...]] = ("trung binh", "binh quan", "average", "mean")
MIN_LABEL_CHARS: Final[int] = 2
TWO_DIGIT_YEAR: Final[int] = 100

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


def _plain(text: object) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", fold(str(text))))


def _marked(text: object) -> str:
    lowered = unicodedata.normalize("NFC", str(text)).lower()
    return " ".join(re.findall(r"\w+", lowered))


def _has_marks(text: str) -> bool:
    plain = unicodedata.normalize("NFD", text)
    return any(unicodedata.category(char) == "Mn" for char in plain) or "đ" in text.lower()


def _year(text: str) -> int:
    number = int(text)
    return number + 2000 if number < TWO_DIGIT_YEAR else number


def period_key(value: object) -> tuple[int, int] | None:
    """(năm, tháng cuối kỳ) của một mốc thời gian, hoặc None khi nó không phải mốc."""
    text = _plain(value)
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


def _candidates(series: pd.Series[Any]) -> list[object]:
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


def named_values(frame: pd.DataFrame, question: str) -> dict[str, list[object]]:
    """Với mỗi cột, những giá trị câu hỏi gọi đích danh, theo thứ tự xuất hiện trong câu."""
    spoken = _marked if _has_marks(question) else _plain
    asked = f" {spoken(question)} "
    found: dict[str, list[object]] = {}
    for column in frame.columns:
        hits: list[tuple[int, str, object]] = []
        for value in _candidates(frame[column]):
            said = spoken(value)
            if len(said.replace(" ", "")) < MIN_LABEL_CHARS:
                continue
            where = asked.find(f" {said} ")
            if where >= 0:
                hits.append((where, said, value))
        # "lợi nhuận sau thuế" nằm trong "lợi nhuận sau thuế của cổ đông": câu hỏi gọi
        # cái dài thì cái ngắn không phải là cái được gọi.
        kept = [
            hit
            for hit in hits
            if not any(
                len(other[1]) > len(hit[1]) and f" {hit[1]} " in f" {other[1]} " for other in hits
            )
        ]
        if kept:
            found[str(column)] = [value for _, _, value in sorted(kept, key=lambda hit: hit[0])]
    return found


def _measures(question: str, numeric: list[str]) -> list[str]:
    if not numeric:
        return []
    asked = named_in(question, numeric)
    chosen = [name for name in numeric if name in asked]
    if chosen:
        return chosen[:MAX_MEASURES]
    return numeric if len(numeric) <= MAX_MEASURES else []


def _safe(name: object) -> str:
    # Dau cham tach cac doan cua mot khoa; trong ten thi doi thanh dau phay.
    return str(name).replace(".", ",").strip()


def _label(value: object) -> str:
    return str(value).replace(".", "-").strip()


def point_comparison(
    frame: pd.DataFrame, question: str
) -> tuple[dict[str, MetricValue], list[str]]:
    """Giá trị tại từng mốc câu hỏi gọi tên, và chênh lệch giữa các mốc liền nhau.

    Returns:
        (chỉ số, ghi chú). Rỗng khi câu hỏi không gọi tên giá trị nào của bảng.
    """
    if not question.strip() or frame.empty:
        return {}, []
    named = named_values(frame, question)
    if not named:
        return {}, []

    def is_period(column: str) -> bool:
        return all(period_key(value) is not None for value in named[column])

    axis = max(named, key=lambda column: (len(named[column]), is_period(column)))
    filters = {column: values for column, values in named.items() if column != axis}
    numeric = [
        str(column)
        for column in frame.columns
        if str(column) not in named
        and pd.api.types.is_numeric_dtype(frame[column])
        and not pd.api.types.is_bool_dtype(frame[column])
    ]
    shown = ", ".join(str(value) for value in named[axis])
    measures = _measures(question, numeric)
    if not measures:
        if not numeric:
            return {}, [f"Câu hỏi gọi tên {shown} ở cột '{axis}' nhưng bảng không có cột số nào."]
        return {}, [
            f"Câu hỏi gọi tên {shown} ở cột '{axis}' nhưng không gọi tên cột số nào, và bảng "
            f"có {len(numeric)} cột số, nên không đoán nên tính trên cột nào."
        ]

    labels = list(named[axis])
    if is_period(axis):
        labels.sort(key=lambda value: period_key(value) or (0, 0))
    use_mean = any(word in _plain(question) for word in MEAN_WORDS)
    combinations = list(
        itertools.product(
            *[[(column, value) for value in values] for column, values in filters.items()]
        )
    )[:MAX_COMBINATIONS]

    out: dict[str, MetricValue] = {}
    notes: list[str] = []

    def add(key: str, value: float, unit: str, source: str) -> None:
        out[key] = MetricValue(key=key, value=round(value, DECIMALS), unit=unit, source=source)

    for combination in combinations:
        rows = frame
        for column, value in combination:
            rows = rows[rows[column] == value]
        where = ", ".join(f"{column} = {value}" for column, value in combination)
        suffix = f" ({', '.join(str(value) for _, value in combination)})" if combination else ""
        for measure in measures:
            prefix = _safe(f"{measure}{suffix}")
            seen: list[tuple[object, float]] = []
            for label in labels:
                picked = pd.to_numeric(rows.loc[rows[axis] == label, measure], errors="coerce")
                picked = picked.dropna()
                if picked.empty:
                    notes.append(
                        f"Không có số của '{measure}' tại {axis} = {label}"
                        + (f" ({where})" if where else "")
                        + "."
                    )
                    continue
                if len(picked.index) == 1:
                    stat, number, how = "value", float(picked.iloc[0]), "giá trị"
                elif use_mean:
                    stat, number, how = "mean", float(picked.mean()), "trung bình"
                else:
                    stat, number, how = "sum", float(picked.sum()), "tổng"
                add(
                    f"{prefix}.{stat}.by.{_safe(axis)}.{_label(label)}",
                    number,
                    "",
                    f"lọc & tính: {how} của '{measure}' tại {axis} = {label}"
                    + (f", {where}" if where else "")
                    + f" ({len(picked.index)} dòng)",
                )
                seen.append((label, number))
            for (before, old), (after, new) in itertools.pairwise(seen):
                source = f"lọc & tính: '{measure}' tại {after} trừ tại {before}" + (
                    f", {where}" if where else ""
                )
                add(f"{prefix}.change.by.{_safe(axis)}.{_label(after)}", new - old, "", source)
                if old != 0:
                    add(
                        f"{prefix}.pct_change.by.{_safe(axis)}.{_label(after)}",
                        (new - old) / abs(old) * 100,
                        "%",
                        f"{source}, chia cho giá trị tại {before}",
                    )

    if out:
        notes.append(
            f"Lọc & Tính (bằng code, không qua model): {', '.join(measures)} tại {axis} = "
            f"{', '.join(str(label) for label in labels)}"
            + (
                f", lọc {', '.join(f'{c} = {v}' for c, vals in filters.items() for v in vals)}"
                if filters
                else ""
            )
            + "; chênh lệch là mốc sau trừ mốc trước"
            + (" (sắp theo thời gian)." if is_period(axis) else " (theo thứ tự trong câu hỏi).")
        )
    return out, notes
