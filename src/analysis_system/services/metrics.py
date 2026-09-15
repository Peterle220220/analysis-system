"""Every number the analysis is allowed to state, computed here in code.

The spec forbids A7 from producing a figure that is not in its input metrics,
and leaves open how to enforce that. Extracting numbers back out of prose and
comparing them is the obvious approach and a bad one: 4.8 and 4,8 and 4.80 are
the same number written three ways, a rounded figure is neither equal nor wrong,
and a derived number like "12% of total" appears nowhere in the inputs.

So the numbers never enter the prose in the first place. This module computes a
named set of values; the model writes sentences containing placeholders like
{price.mean}; code substitutes the real figures afterwards. A number the model
invented has nowhere to live, because a claim carrying a bare digit is rejected
before it is ever rendered.

Keys are built from column and value names and are stable across runs, so the
same table always produces the same key set.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any, Final

import pandas as pd

from analysis_system.models.agents import MetricValue

# How many values of a dimension get their own metrics.
#
# This was five, and a question that asked for a count of every emotion label
# got five of the six back - `surprise`, the smallest at 572 rows, had no
# metric at all, so no claim could mention it and nothing said it was missing.
# A list that silently omits a member is worse than a refusal.
#
# Twenty, because that is already what the rest of the system calls a grouping:
# the statistics layer refuses a breakdown past twenty groups, and the analyst
# only offers a column as a dimension below the same line. A column that counts
# as groupable everywhere else should not be summarised down to its top five
# here.
TOP_VALUES: Final[int] = 20
NUMERIC_SHARE_REQUIRED: Final[float] = 0.9
ROUNDING: Final[int] = 4


def _clean_key(text: str) -> str:
    """Make a value safe to use inside a metric key."""
    return "".join(char if char.isalnum() or char in "_-" else "_" for char in str(text))[:40]


def _numeric(series: pd.Series[Any]) -> pd.Series[Any] | None:
    """The column as numbers, when nearly all of it parses as one."""
    present = series.dropna()
    if present.empty:
        return None
    parsed = pd.to_numeric(present, errors="coerce")
    if float(parsed.notna().sum()) / float(len(present)) < NUMERIC_SHARE_REQUIRED:
        return None
    return parsed.dropna()


def _round(value: float) -> float:
    """Round to a fixed precision so two runs agree to the last digit."""
    return 0.0 if math.isnan(value) else round(float(value), ROUNDING)


def compute_metrics(
    frame: pd.DataFrame,
    *,
    dimensions: tuple[str, ...] = (),
    measures: tuple[str, ...] = (),
    top_values: int = TOP_VALUES,
) -> dict[str, MetricValue]:
    """Compute the full set of values an analysis may quote.

    Args:
        frame: the mart table.
        dimensions: columns to break measures down by, such as city or vendor.
        measures: numeric columns to summarise. Empty means every column that
            looks numeric.
        top_values: how many values of each dimension to break down by.

    Returns:
        Metric key to value, in a stable order.
    """
    metrics: dict[str, MetricValue] = {}
    total = len(frame.index)
    metrics["rows.total"] = MetricValue(
        key="rows.total", value=float(total), unit="dòng", source="frame"
    )

    numeric_columns: dict[str, pd.Series[Any]] = {}
    for name in sorted(str(column) for column in frame.columns):
        numbers = _numeric(frame[name])
        if numbers is not None and (not measures or name in measures):
            numeric_columns[name] = numbers

    for name in sorted(str(column) for column in frame.columns):
        series = frame[name]
        non_null = int(series.notna().sum())
        metrics[f"{name}.distinct"] = MetricValue(
            key=f"{name}.distinct",
            value=float(series.nunique(dropna=True)),
            unit="gia tri",
            source=name,
        )
        metrics[f"{name}.null_pct"] = MetricValue(
            key=f"{name}.null_pct",
            value=_round(0.0 if total == 0 else 100.0 * (total - non_null) / total),
            unit="%",
            source=name,
        )

    for name, numbers in numeric_columns.items():
        for label, value in (
            ("sum", float(numbers.sum())),
            ("mean", float(numbers.mean())),
            ("median", float(numbers.median())),
            ("min", float(numbers.min())),
            ("max", float(numbers.max())),
        ):
            key = f"{name}.{label}"
            metrics[key] = MetricValue(key=key, value=_round(value), unit="", source=name)

    metrics.update(_flag_counts(numeric_columns, total))

    broken_down = 0
    skipped = 0
    for dimension in dimensions:
        if dimension not in frame.columns:
            continue
        counts = frame[dimension].dropna().astype(str).value_counts()
        ordered = sorted(
            ((str(name), int(number)) for name, number in counts.items()),
            key=lambda item: (-item[1], item[0]),
        )
        # Past the cap the list is a top-N, not a breakdown. Say so as a metric
        # rather than leaving the reader to notice the tail is missing - which
        # is precisely what nobody did when it was five.
        left_out = max(0, len(ordered) - top_values)
        if left_out:
            key = f"{dimension}.categories_omitted"
            metrics[key] = MetricValue(
                key=key, value=float(left_out), unit="nhóm", source=dimension
            )

        for category, count in ordered[:top_values]:
            slug = _clean_key(category)
            metrics[f"{dimension}.{slug}.count"] = MetricValue(
                key=f"{dimension}.{slug}.count",
                value=float(count),
                unit="dòng",
                source=dimension,
            )
            metrics[f"{dimension}.{slug}.share_pct"] = MetricValue(
                key=f"{dimension}.{slug}.share_pct",
                value=_round(0.0 if total == 0 else 100.0 * count / total),
                unit="%",
                source=dimension,
            )
            for measure, numbers in numeric_columns.items():
                if broken_down >= MAX_BREAKDOWNS:
                    skipped += 1
                    continue
                matching = frame[dimension].astype(str).reindex(numbers.index) == category
                subset = numbers[matching]
                if subset.empty:
                    continue
                key = f"{measure}.mean.by.{dimension}.{slug}"
                metrics[key] = MetricValue(
                    key=key,
                    value=_round(float(subset.mean())),
                    unit="",
                    source=f"{measure} theo {dimension}",
                )
                broken_down += 1

    if skipped:
        # Noi ra, khong bo trong im lang. Cung mot cach nhu `categories_omitted`
        # ngay tren: nguoi doc phai biet cai duoi day khong phai tat ca.
        key = "breakdowns_omitted"
        metrics[key] = MetricValue(key=key, value=float(skipped), unit="phép đo", source="gioi han")

    metrics.update(_rates_by_group(frame, dimensions, top_values))
    return metrics


# Nhóm nhỏ hơn thế này thì một tỷ lệ chỉ là tiếng ồn: bốn người mà ba người
# đồng ý thì ra 75 %, và con số đó không nói gì cả. Cùng ngưỡng
# `statistics.MIN_GROUP` dùng, và cùng một lý do.
# Tran cho so phep chia nho `{do luong}.mean.by.{cot}.{nhom}`.
#
# So phep nay la tich cua ba thu - so cot chia nhom, so nhom moi cot, so cot so
# - nen no tang theo BINH PHUONG so cot. Do tren bang tao san:
#
#     100 cot ->   8.276 chi so,   6,8 giay
#     300 cot ->  69.826 chi so,  56,4 giay
#     500 cot -> 191.376 chi so, 155,0 giay
#    1000 cot ->                   19 phut
#
# Trong khi lop cat ngan sach chi gui khoang 540 cai cho model. Tinh 191.376 de
# gui 540 la lang phi 350 lan, va nguoi dung ngoi cho ba phut cho phan lang phi
# do.
#
# Hai nghin la rong rai: bang 21 cot cua chu he thong dung khoang 110 phep, con
# bang 96 cot dung it hon the. Chi bang benh hoan moi cham tran.
MAX_BREAKDOWNS: Final[int] = 2_000

MIN_GROUP_ROWS: Final[int] = 5

# Chỉ bắt chéo với kết quả có ĐÚNG HAI giá trị. "Nhóm nào có tỷ lệ đồng ý cao
# nhất" là câu hỏi về một kết quả có/không; với một cột mười giá trị thì nó
# không còn là một câu hỏi, và số chỉ số sinh ra thì bùng lên theo cấp số nhân.
BINARY: Final[int] = 2


def _flag_counts(numeric_columns: dict[str, pd.Series[Any]], total: int) -> dict[str, MetricValue]:
    """Đếm và tỷ lệ cho một cột cờ 0/1.

    Chỗ trống này làm hỏng một câu trả lời thật. Hỏi *"có bao nhiêu công ty phá
    sản và bao nhiêu công ty không?"*, cột `Bankrupt?` là 0/1 — tức là một cột
    **số**, nên nó chỉ nhận được `sum`, `mean`, `median`, `min`, `max`.

    `Bankrupt?.sum = 220` **chính là** số công ty phá sản, nhưng không ai gọi nó
    như thế, và model không nhận ra. Còn *"bao nhiêu công ty **không** phá sản"*
    thì thật sự không có: nó là `6819 − 220`, một phép trừ, và hệ thống cấm tự
    tính ra số mới.

    Câu trả lời nói thẳng *"chưa được đo"* — trung thực, và đúng. Nhưng đúng vì
    một chỗ trống đáng lẽ không nên có: **cột cờ 0/1 là cách phổ biến nhất để
    lưu một kết quả có/không**, và nó không nhận được lấy một phép đếm nào.

    Một cột chữ hai giá trị thì đã có `count` và `share_pct` từ lâu. Cột số hai
    giá trị đáng được đối xử y hệt — cùng một câu hỏi, cùng một hình dạng dữ
    liệu, chỉ khác kiểu lưu.
    """
    found: dict[str, MetricValue] = {}
    for name, numbers in numeric_columns.items():
        values = sorted(numbers.dropna().unique())
        if len(values) != BINARY:
            continue
        for value in values:
            # Nhãn giữ dạng người đọc: `1`, không phải `1.0`.
            label = _clean_key(str(int(value)) if float(value).is_integer() else str(value))
            count = int((numbers == value).sum())
            for suffix, number, unit in (
                ("count", float(count), "dòng"),
                ("share_pct", 0.0 if total == 0 else 100.0 * count / total, "%"),
            ):
                key = f"{name}.{label}.{suffix}"
                found[key] = MetricValue(key=key, value=_round(number), unit=unit, source=name)
    return found


def _rates_by_group(
    frame: pd.DataFrame, dimensions: Sequence[str], top_values: int
) -> dict[str, MetricValue]:
    """Tỷ lệ của một kết quả hai giá trị, trong từng nhóm.

    Chỗ trống này làm hỏng một câu trả lời thật. Chủ hệ thống hỏi *"nhóm khách
    hàng nào có tỷ lệ 'yes' cao nhất?"*, và nhận về sáu kết luận nói `campaign`
    thay đổi thế nào **theo** `y` — ngược chiều câu hỏi. Không phải model chọn
    sai: **con số trả lời câu hỏi chưa từng được đo.**

    Hệ thống biết đo trung bình một cột SỐ theo nhóm, và tỷ lệ từng giá trị của
    một cột CHỮ đứng một mình. Nó không biết bắt chéo hai cột chữ — mà "nhóm
    nào chốt được nhiều nhất" chính là phép đó, và là câu hỏi thường gặp nhất
    trong phân tích kinh doanh.

    Khoá đặt theo đúng ngữ pháp đang có:

        y.yes.share_pct.by.poutcome.success = 65.11

    nên `findings.split_group` tách được thành họ và nhóm, và `rankings()` tự
    trả lời được "nhóm nào cao nhất" mà không cần model so sánh gì.
    """
    found: dict[str, MetricValue] = {}
    usable = [name for name in dimensions if name in frame.columns]
    for outcome in usable:
        column = frame[outcome].dropna().astype(str)
        values = sorted(column.unique())
        if len(values) != BINARY:
            continue
        for group in usable:
            if group == outcome:
                continue
            counts = frame[group].dropna().astype(str).value_counts()
            for name in list(counts.index)[:top_values]:
                rows = frame[frame[group].astype(str) == str(name)]
                inside = rows[outcome].dropna().astype(str)
                if len(inside) < MIN_GROUP_ROWS:
                    # Bỏ qua trong im lặng ở đây là được: `statistics` đã báo
                    # chuyện nhóm quá nhỏ bằng đúng ngưỡng này rồi, và nói hai
                    # lần cùng một điều làm người ta thôi đọc cả cụm.
                    continue
                group_slug = _clean_key(str(name))
                for value in values:
                    share = 100.0 * float((inside == value).sum()) / len(inside)
                    key = f"{outcome}.{_clean_key(value)}.share_pct.by.{group}.{group_slug}"
                    found[key] = MetricValue(
                        key=key,
                        value=_round(share),
                        unit="%",
                        source=f"ty le {outcome}={value} theo {group}",
                    )
    return found


def metric_catalogue(metrics: dict[str, MetricValue]) -> list[dict[str, Any]]:
    """The metric set as the model is shown it: keys, values and units."""
    return [
        {"key": metric.key, "value": metric.value, "unit": metric.unit, "source": metric.source}
        for metric in sorted(metrics.values(), key=lambda item: item.key)
    ]
