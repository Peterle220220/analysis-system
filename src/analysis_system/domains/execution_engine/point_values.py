"""Lọc & Tính: giá trị tại những mốc câu hỏi gọi tên, chênh lệch, và tỷ lệ giữa hai chỉ tiêu.

Hỏi "lợi nhuận sau thuế Q2-2026 so với Q1-2026, chênh lệch bao nhiêu" là hỏi một phép
lọc và một phép trừ; hỏi "ROA từng quý" là một phép chia cho từng quý. Tầng thống kê
không có những phép đó: nó đo trung bình, tương quan, so sánh nhóm, những thứ dành cho
một mẫu nhiều dòng. Trên báo cáo tài chính MBB (4 kỳ) nó đo tám cặp tương quan không ai
hỏi và không một con số nào gắn với tên kỳ (bao_cao_tai_chinh_mb_cua_4_quy_gan_nhat__q1,
2026-09-15).

Ở đây code đọc câu hỏi (`question_labels`), tìm những GIÁ TRỊ của cột nhóm được gọi đích
danh ("Q2-2026", "Lợi nhuận sau thuế", "North"), lọc đúng những dòng đó và tính. Không
model nào chạm vào con số. Tên khoá theo mẫu `<chỉ số>.<phép>.by.<cột>.<nhãn>`, nên nhãn
(kể cả nhãn có chữ số như Q2-2026) được nói ra bằng `{ten:...}` và không bị coi là số gõ
tay.

Không đoán:

* Nhiều dòng cùng một nhãn thì cộng (doanh thu một tháng là tổng các đơn), trừ khi câu
  hỏi nói "trung bình"; khoá nói rõ đã cộng (`sum`) hay lấy trung bình (`mean`).
* Chênh lệch chỉ tính khi câu hỏi hỏi so sánh hoặc xu hướng: "ROA từng quý" là bốn con
  số, không phải ba phép trừ.
* Tỷ lệ A / B chỉ khi câu hỏi đặt một phép chia giữa hai tên ("A trên B", "A chia B",
  "A/B", "ratio of A to B").
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Final

import pandas as pd

from analysis_system.domains.execution_engine.cross_row import CrossRow, read_cross_row
from analysis_system.models.agents import MetricValue
from analysis_system.services.answer_shape import Demand, read_question
from analysis_system.services.question_labels import (
    MAX_EACH,
    all_periods,
    asks_each,
    by_time,
    is_ratio_gap,
    named_values,
    names_in_order,
    period_columns,
    spoken,
)
from analysis_system.services.shortlist import named_in

DECIMALS: Final[int] = 4
# Cau hoi khong goi ten cot so nao ma bang co nhieu hon chung nay cot so thi khong doan.
MAX_MEASURES: Final[int] = 5
MAX_COMBINATIONS: Final[int] = 10
MEAN_WORDS: Final[tuple[str, ...]] = ("trung binh", "binh quan", "average", "mean")
CHANGE_DEMANDS: Final[frozenset[Demand]] = frozenset({Demand.COMPARISON, Demand.TREND})
HOW: Final[dict[str, str]] = {"value": "giá trị", "mean": "trung bình", "sum": "tổng"}


@dataclass
class _Out:
    metrics: dict[str, MetricValue] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def add(self, key: str, value: float, unit: str, source: str) -> None:
        self.metrics[key] = MetricValue(
            key=key, value=round(value, DECIMALS), unit=unit, source=source
        )


def _safe(name: object) -> str:
    # Dau cham tach cac doan cua mot khoa; trong ten thi doi thanh dau phay.
    return str(name).replace(".", ",").strip()


def _label(value: object) -> str:
    return str(value).replace(".", "-").strip()


def _numeric(frame: pd.DataFrame, exclude: set[str]) -> list[str]:
    return [
        str(column)
        for column in frame.columns
        if str(column) not in exclude
        and pd.api.types.is_numeric_dtype(frame[column])
        and not pd.api.types.is_bool_dtype(frame[column])
    ]


def _cell(rows: pd.DataFrame, measure: str, use_mean: bool) -> tuple[str, float, int] | None:
    picked = pd.to_numeric(rows[measure], errors="coerce").dropna()
    if picked.empty:
        return None
    if len(picked.index) == 1:
        return "value", float(picked.iloc[0]), 1
    if use_mean:
        return "mean", float(picked.mean()), len(picked.index)
    return "sum", float(picked.sum()), len(picked.index)


def _changes(
    out: _Out, prefix: str, axis: str, seen: list[tuple[object, float]], what: str, where: str
) -> None:
    for (before, old), (after, new) in itertools.pairwise(seen):
        source = f"lọc & tính: {what} tại {after} trừ tại {before}" + (
            f", {where}" if where else ""
        )
        out.add(f"{prefix}.change.by.{_safe(axis)}.{_label(after)}", new - old, "", source)
        if old != 0:
            out.add(
                f"{prefix}.pct_change.by.{_safe(axis)}.{_label(after)}",
                (new - old) / abs(old) * 100,
                "%",
                f"{source}, chia cho giá trị tại {before}",
            )


def _axis_labels(frame: pd.DataFrame, question: str, axis: str) -> list[object]:
    """Những mốc câu hỏi gọi tên ở cột này; không gọi mốc nào thì mọi mốc (nếu đếm được)."""
    named = named_values(frame, question).get(axis)
    labels = list(named) if named else list(frame[axis].dropna().unique())
    return by_time(labels) if len(labels) <= MAX_EACH else []


def point_comparison(
    frame: pd.DataFrame, question: str
) -> tuple[dict[str, MetricValue], list[str]]:
    """Giá trị tại những mốc câu hỏi gọi tên, chênh lệch, và tỷ lệ A / B khi câu hỏi hỏi.

    Returns:
        (chỉ số, ghi chú). Rỗng khi câu hỏi không gọi tên gì của bảng.
    """
    if not question.strip() or frame.empty:
        return {}, []
    out = _Out()
    changes = read_question(question) in CHANGE_DEMANDS
    use_mean = any(word in spoken(question, marked=False) for word in MEAN_WORDS)

    cross = read_cross_row(frame, question)
    if cross is not None and cross.ratio is not None:
        _cross_ratio(out, frame, question, cross, changes)
        return out.metrics, out.notes
    _wide_ratio(out, frame, question, changes)
    _named_points(out, frame, question, changes, use_mean)
    return out.metrics, out.notes


def _cross_ratio(
    out: _Out, frame: pd.DataFrame, question: str, cross: CrossRow, changes: bool
) -> None:
    """Bảng dài: A / B lấy hai dòng của cột chỉ tiêu về cùng một mốc rồi chia."""
    assert cross.ratio is not None
    top, bottom = cross.ratio
    if len(cross.group_by) != 1:
        out.notes.append(
            f"Câu hỏi hỏi tỷ lệ {top} / {bottom} nhưng bảng chia theo "
            f"{len(cross.group_by)} cột ({', '.join(cross.group_by)}), nên không tự chọn cách gom."
        )
        return
    axis = cross.group_by[0]
    labels = _axis_labels(frame, question, axis)
    prefix = _safe(f"{cross.value} ({top} / {bottom})")
    seen: list[tuple[object, float]] = []
    for label in labels:
        rows = frame[frame[axis] == label]
        cells = {
            item: _cell(rows[rows[cross.label] == item], cross.value, False)
            for item in (top, bottom)
        }
        for item, cell in cells.items():
            if cell is not None:
                stat, number, count = cell
                out.add(
                    f"{_safe(f'{cross.value} ({item})')}.{stat}.by.{_safe(axis)}.{_label(label)}",
                    number,
                    "",
                    f"lọc & tính: {HOW[stat]} của '{cross.value}' tại {axis} = {label}, "
                    f"{cross.label} = {item} ({count} dòng)",
                )
        numerator, denominator = cells[top], cells[bottom]
        if numerator is None or denominator is None or denominator[1] == 0:
            out.notes.append(
                f"Không tính được {top} / {bottom} tại {axis} = {label}: thiếu số hoặc mẫu bằng 0."
            )
            continue
        ratio = numerator[1] / denominator[1]
        source = (
            f"lọc & tính: {top} chia {bottom} tại {axis} = {label} "
            f"(hai dòng của cột '{cross.label}', giá trị ở cột '{cross.value}')"
        )
        out.add(f"{prefix}.ratio.by.{_safe(axis)}.{_label(label)}", ratio, "", source)
        out.add(
            f"{prefix}.ratio_pct.by.{_safe(axis)}.{_label(label)}",
            ratio * 100,
            "%",
            f"{source}, nhân 100",
        )
        seen.append((label, ratio))
    if changes:
        _changes(out, prefix, axis, seen, f"tỷ lệ {top} / {bottom}", "")
    if seen:
        out.notes.append(
            f"Lọc & Tính (bằng code, không qua model): tỷ lệ {top} / {bottom} theo từng {axis} "
            f"({', '.join(str(label) for label, _ in seen)})."
        )


def _wide_ratio(out: _Out, frame: pd.DataFrame, question: str, changes: bool) -> None:
    """Bảng rộng: câu hỏi đặt một phép chia giữa hai tên cột số."""
    hits = names_in_order(question, _numeric(frame, set()))
    pair = next(
        (
            (str(first[2]), str(second[2]))
            for first, second in itertools.pairwise(hits)
            if is_ratio_gap(question, first, second)
        ),
        None,
    )
    periods = period_columns(frame)
    if pair is None or not periods:
        return
    top, bottom = pair
    axis = periods[0]
    prefix = _safe(f"{top} / {bottom}")
    seen: list[tuple[object, float]] = []
    for label in _axis_labels(frame, question, axis):
        rows = frame[frame[axis] == label]
        numerator, denominator = _cell(rows, top, False), _cell(rows, bottom, False)
        if numerator is None or denominator is None or denominator[1] == 0:
            continue
        ratio = numerator[1] / denominator[1]
        source = f"lọc & tính: cột '{top}' chia cột '{bottom}' tại {axis} = {label}"
        out.add(f"{prefix}.ratio.by.{_safe(axis)}.{_label(label)}", ratio, "", source)
        out.add(
            f"{prefix}.ratio_pct.by.{_safe(axis)}.{_label(label)}",
            ratio * 100,
            "%",
            f"{source}, nhân 100",
        )
        seen.append((label, ratio))
    if changes:
        _changes(out, prefix, axis, seen, f"tỷ lệ {top} / {bottom}", "")


def _measures(question: str, numeric: list[str]) -> list[str]:
    if not numeric:
        return []
    asked = named_in(question, numeric)
    chosen = [name for name in numeric if name in asked]
    if chosen:
        return chosen[:MAX_MEASURES]
    return numeric if len(numeric) <= MAX_MEASURES else []


def _named_points(
    out: _Out, frame: pd.DataFrame, question: str, changes: bool, use_mean: bool
) -> None:
    """Giá trị tại những mốc được gọi tên (hay mọi mốc khi hỏi "từng"), lọc theo tên khác."""
    named = named_values(frame, question)
    if asks_each(question):
        # "Từng quý" mà không gọi quý nào: mọi quý của cột thời gian đầu tiên.
        for column in period_columns(frame):
            if column not in named:
                named[column] = by_time(list(frame[column].dropna().unique()))
            break
    if not named:
        return

    axis = max(named, key=lambda column: (len(named[column]), all_periods(named[column])))
    filters = {column: values for column, values in named.items() if column != axis}
    numeric = _numeric(frame, set(named))
    shown = ", ".join(str(value) for value in named[axis])
    measures = _measures(question, numeric)
    if not measures:
        if not numeric:
            out.notes.append(
                f"Câu hỏi gọi tên {shown} ở cột '{axis}' nhưng bảng không có cột số nào."
            )
        else:
            out.notes.append(
                f"Câu hỏi gọi tên {shown} ở cột '{axis}' nhưng không gọi tên cột số nào, và "
                f"bảng có {len(numeric)} cột số, nên không đoán nên tính trên cột nào."
            )
        return

    labels = by_time(named[axis])
    combinations = list(
        itertools.product(
            *[[(column, value) for value in values] for column, values in filters.items()]
        )
    )[:MAX_COMBINATIONS]
    computed = False
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
                cell = _cell(rows[rows[axis] == label], measure, use_mean)
                if cell is None:
                    out.notes.append(
                        f"Không có số của '{measure}' tại {axis} = {label}"
                        + (f" ({where})" if where else "")
                        + "."
                    )
                    continue
                stat, number, count = cell
                out.add(
                    f"{prefix}.{stat}.by.{_safe(axis)}.{_label(label)}",
                    number,
                    "",
                    f"lọc & tính: {HOW[stat]} của '{measure}' tại {axis} = {label}"
                    + (f", {where}" if where else "")
                    + f" ({count} dòng)",
                )
                seen.append((label, number))
                computed = True
            if changes:
                _changes(out, prefix, axis, seen, f"'{measure}'", where)

    if computed:
        out.notes.append(
            f"Lọc & Tính (bằng code, không qua model): {', '.join(measures)} tại {axis} = "
            f"{', '.join(str(label) for label in labels)}"
            + (
                f", lọc {', '.join(f'{c} = {v}' for c, vals in filters.items() for v in vals)}"
                if filters
                else ""
            )
            + (
                "; chênh lệch là mốc sau trừ mốc trước"
                + (" (sắp theo thời gian)." if all_periods(labels) else " (theo thứ tự câu hỏi).")
                if changes
                else "."
            )
        )
