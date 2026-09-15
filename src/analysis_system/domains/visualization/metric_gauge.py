"""Thẻ một con số: luôn kèm thang đo và một đánh giá bằng lời.

Một con số đứng một mình ("1.17", "0.8", "-0.5") không nói gì với người đọc báo
cáo: cao hay thấp, tốt hay đáng lo, họ không biết. Mỗi thẻ ở đây có ba thứ:

1. Số, in to.
2. Đánh giá định tính kèm ký hiệu: "Tương quan thuận rất mạnh (r = 0.80)".
3. Một thanh đo: các vùng ngưỡng, và chấm đánh dấu con số nằm ở đâu.

Thang đo đọc từ HÌNH DẠNG metric key, không hỏi model: tương quan chạy từ -1 tới
1, p-value đọc trên thang log, độ lớn tác động dùng ngưỡng Cohen... Trung bình,
trung vị và mức chênh thì so với khoảng giá trị thật của chính cột đó (cần min và
max đã đo). Không viết cứng tên cột nào: thang đo đi theo loại chỉ số.

Con số nào không có thang để đọc (tổng số dòng, một tổng cộng...) thì KHÔNG dựng
thẻ: thà không có thẻ còn hơn một thẻ số trọc. Con số ấy vẫn nằm trong câu kết
luận.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from html import escape
from typing import Final

GAUGE_STYLE: Final[str] = (
    ".chart.gauge{margin:.4rem 0;padding:.9rem 1rem 1rem;border:1px solid #e5e7eb;"
    "border-radius:.5rem;background:#fcfcfb;color:#0b0b0b;"
    'font-family:system-ui,-apple-system,"Segoe UI",sans-serif}'
    ".chart.gauge .chart-title{margin:0 0 .45rem;font-size:.95rem;font-weight:650;"
    "line-height:1.35;color:#0b0b0b}"
    ".chart.gauge .gauge-value{font-size:2rem;font-weight:700;line-height:1.1}"
    ".chart.gauge .gauge-verdict{margin:.2rem 0 .85rem;font-size:1rem;line-height:1.4}"
    ".chart.gauge .gauge-track{position:relative;height:14px;margin:0 .6rem}"
    ".chart.gauge .gauge-band{position:absolute;top:0;bottom:0;background:#e5e7eb;"
    "border-left:2px solid #fcfcfb}"
    ".chart.gauge .gauge-band.hit{background:#86b6ef}"
    ".chart.gauge .gauge-zero{position:absolute;top:-5px;bottom:-5px;width:1px;background:#52514e}"
    ".chart.gauge .gauge-marker{position:absolute;top:50%;width:24px;height:24px;"
    "margin:-12px 0 0 -12px;border-radius:50%;cursor:pointer;outline-offset:2px;"
    "background:radial-gradient(circle,#2a78d6 0 6px,#fcfcfb 6px 8px,transparent 8px)}"
    ".chart.gauge .gauge-ticks{position:relative;height:1.2rem;margin:.4rem .6rem 0;"
    "font-size:.8rem;color:#52514e;font-variant-numeric:tabular-nums}"
    ".chart.gauge .gauge-ticks span{position:absolute;transform:translateX(-50%);"
    "white-space:nowrap}"
    ".chart.gauge .gauge-ends{display:flex;justify-content:space-between;gap:1rem;"
    "margin:.15rem 0 0;font-size:.8rem;color:#898781}"
    ".chart.gauge .gauge-note{margin:.55rem 0 0;font-size:.85rem;line-height:1.4;color:#52514e}"
)

# p-value: thang log từ 1e-4 tới 1. Nhỏ hơn 1e-4 thì dồn về mép trái.
P_FLOOR: Final[float] = 1e-4


@dataclass(frozen=True)
class Reading:
    """Mọi thứ một thẻ cần: số, lời đánh giá, và thang đo tính bằng phần trăm bề ngang."""

    value: str
    verdict: str
    position: float
    bands: tuple[float, ...]
    ticks: tuple[tuple[float, str], ...]
    ends: tuple[str, str]
    note: str = ""
    zero: float | None = None


def _num(value: float) -> str:
    """Số in cho người đọc: số nguyên giữ nguyên, số rất nhỏ giữ đủ chữ số, còn lại 2 chữ số."""
    if float(value).is_integer():
        return f"{value:,.0f}"
    if 0 < abs(value) < 0.01:
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return f"{value:,.2f}"


def _pct(value: float, low: float, high: float) -> float:
    """Vị trí của một giá trị trên thang, tính bằng phần trăm, kẹp trong 0-100."""
    if high <= low:
        return 0.0
    return max(0.0, min(100.0, 100.0 * (value - low) / (high - low)))


def _level(value: float, edges: Sequence[float], names: Sequence[str]) -> str:
    """Tên vùng mà giá trị rơi vào: `edges` là ranh giới trên của từng vùng trừ vùng cuối."""
    for edge, name in zip(edges, names, strict=False):
        if value < edge:
            return name
    return names[-1]


def _tidy(text: str) -> str:
    return " ".join(str(text).split())


def _context(context: Mapping[str, float] | None, key: str) -> float | None:
    if not context:
        return None
    if key in context:
        return float(context[key])
    wanted = _tidy(key)
    return next((float(value) for name, value in context.items() if _tidy(name) == wanted), None)


def _column_range(context: Mapping[str, float] | None, column: str) -> tuple[float, float] | None:
    low, high = _context(context, f"{column}.min"), _context(context, f"{column}.max")
    if low is None or high is None or high <= low:
        return None
    return low, high


# --- tung loai chi so ----------------------------------------------------------


def _correlation(value: float, *, trend: bool) -> Reading:
    strength = abs(value)
    level = _level(strength, (0.1, 0.3, 0.5, 0.7), ("", "yếu", "vừa phải", "mạnh", "rất mạnh"))
    if trend:
        direction = "tăng" if value > 0 else "giảm"
        said = "Gần như không có xu hướng" if not level else f"Xu hướng {direction} {level}"
        ends = ("Giảm dần", "Tăng dần")
    else:
        sign = "thuận" if value > 0 else "nghịch"
        said = "Gần như không có tương quan" if not level else f"Tương quan {sign} {level}"
        ends = ("Nghịch", "Thuận")
    edges = (-1.0, -0.7, -0.5, -0.3, -0.1, 0.1, 0.3, 0.5, 0.7, 1.0)
    return Reading(
        value=_num(value),
        verdict=f"{said} (r = {_num(value)})",
        position=_pct(value, -1.0, 1.0),
        bands=tuple(_pct(edge, -1.0, 1.0) for edge in edges),
        ticks=tuple((_pct(tick, -1.0, 1.0), _num(tick)) for tick in (-1.0, -0.5, 0.0, 0.5, 1.0)),
        ends=ends,
        note="Tương quan chỉ đo mức hai chỉ số cùng biến động, không nói cái nào gây ra cái nào.",
        zero=50.0,
    )


def _effect_size(value: float) -> Reading:
    size = abs(value)
    high = max(2.0, size * 1.1)
    level = _level(size, (0.2, 0.5, 0.8, 1.2), ("không đáng kể", "nhỏ", "vừa", "lớn", "rất lớn"))
    edges = (0.0, 0.2, 0.5, 0.8, 1.2, high)
    return Reading(
        value=_num(value),
        verdict=f"Khác biệt {level} giữa các nhóm (d = {_num(value)})",
        position=_pct(size, 0.0, high),
        bands=tuple(_pct(edge, 0.0, high) for edge in edges),
        ticks=tuple((_pct(tick, 0.0, high), _num(tick)) for tick in (0.2, 0.5, 0.8, 1.2)),
        ends=("Không đáng kể", "Rất lớn"),
        note="Độ lớn tác động đo mức chênh theo độ phân tán của dữ liệu, không phụ thuộc số dòng.",
    )


def _p_value(value: float) -> Reading:
    low, high = math.log10(P_FLOOR), 0.0

    def at(p: float) -> float:
        return _pct(math.log10(max(p, P_FLOOR)), low, high)

    level = _level(
        value,
        (0.001, 0.01, 0.05),
        (
            "Có ý nghĩa thống kê rất mạnh",
            "Có ý nghĩa thống kê mạnh",
            "Có ý nghĩa thống kê",
            "Chưa đủ bằng chứng thống kê",
        ),
    )
    shown = "< 0.001" if value < 0.001 else f"{value:.3f}"
    return Reading(
        value=shown,
        verdict=f"{level} (p {shown if shown.startswith('<') else '= ' + shown})",
        position=at(value),
        bands=tuple(at(edge) for edge in (P_FLOOR, 0.001, 0.01, 0.05, 1.0)),
        ticks=tuple((at(tick), _num(tick)) for tick in (0.001, 0.01, 0.05, 1.0)),
        ends=("Khó là ngẫu nhiên", "Có thể do ngẫu nhiên"),
        note="p nhỏ nghĩa là kết quả khó xảy ra do ngẫu nhiên, không có nghĩa là khác biệt lớn.",
    )


def _t_stat(value: float) -> Reading:
    size = abs(value)
    high = max(5.0, size * 1.1)
    level = _level(
        size,
        (1.96, 2.58, 3.29),
        (
            "chưa vượt ngưỡng ngẫu nhiên",
            "vượt ngưỡng ngẫu nhiên 5 %",
            "vượt ngưỡng ngẫu nhiên 1 %",
            "vượt xa ngưỡng ngẫu nhiên",
        ),
    )
    edges = (0.0, 1.96, 2.58, 3.29, high)
    return Reading(
        value=_num(value),
        verdict=f"Chênh lệch {level} (t = {_num(value)})",
        position=_pct(size, 0.0, high),
        bands=tuple(_pct(edge, 0.0, high) for edge in edges),
        # Hai moc, khong ba: tren be ngang dien thoai 1.96 va 2.58 dung chong nhau.
        ticks=tuple((_pct(tick, 0.0, high), _num(tick)) for tick in (1.96, 3.29)),
        ends=("Như ngẫu nhiên", "Vượt xa ngẫu nhiên"),
    )


def _eta_squared(value: float) -> Reading:
    high = max(30.0, value * 1.1)
    level = _level(value, (1.0, 6.0, 14.0), ("không đáng kể", "nhỏ", "vừa", "lớn"))
    edges = (0.0, 1.0, 6.0, 14.0, high)
    return Reading(
        value=f"{_num(value)} %",
        verdict=f"Cách chia nhóm giải thích phần biến động {level} (η² = {_num(value)} %)",
        position=_pct(value, 0.0, high),
        bands=tuple(_pct(edge, 0.0, high) for edge in edges),
        ticks=tuple((_pct(tick, 0.0, high), f"{_num(tick)} %") for tick in (6.0, 14.0)),
        ends=("Không đáng kể", "Lớn"),
    )


def _r_squared(value: float) -> Reading:
    ratio = value / 100.0 if value > 1.0 else value
    level = _level(ratio, (0.02, 0.13, 0.26), ("rất ít", "ít", "vừa phải", "đáng kể"))
    edges = (0.0, 0.02, 0.13, 0.26, 1.0)
    return Reading(
        value=_num(ratio),
        verdict=f"Mô hình giải thích {level} biến động (R² = {_num(ratio)})",
        position=_pct(ratio, 0.0, 1.0),
        bands=tuple(_pct(edge, 0.0, 1.0) for edge in edges),
        ticks=tuple((_pct(tick, 0.0, 1.0), _num(tick)) for tick in (0.0, 0.26, 0.5, 1.0)),
        ends=("Không giải thích gì", "Giải thích hết"),
    )


def _share(value: float) -> Reading:
    level = _level(
        value, (5.0, 20.0, 50.0, 80.0), ("rất nhỏ", "nhỏ", "đáng kể", "đa số", "gần như toàn bộ")
    )
    edges = (0.0, 5.0, 20.0, 50.0, 80.0, 100.0)
    return Reading(
        value=f"{_num(value)} %",
        verdict=f"Chiếm tỷ trọng {level} ({_num(value)} %)",
        position=_pct(value, 0.0, 100.0),
        bands=tuple(_pct(edge, 0.0, 100.0) for edge in edges),
        ticks=tuple((tick, f"{_num(tick)} %") for tick in (25.0, 50.0, 75.0)),
        ends=("0 %", "100 %"),
    )


STAT_WORDS: Final[dict[str, str]] = {
    "mean": "Trung bình",
    "median": "Trung vị",
    "min": "Giá trị nhỏ nhất",
    "max": "Giá trị lớn nhất",
}


def _in_range(value: float, stat: str, span: tuple[float, float]) -> Reading:
    low, high = span
    position = _pct(value, low, high)
    level = _level(
        position,
        (20.0, 40.0, 60.0, 80.0),
        (
            "gần mức thấp nhất",
            "dưới giữa khoảng",
            "quanh giữa khoảng",
            "trên giữa khoảng",
            "gần mức cao nhất",
        ),
    )
    return Reading(
        value=_num(value),
        verdict=f"{STAT_WORDS[stat]} nằm {level} giá trị ({_num(value)})",
        position=position,
        bands=(0.0, 20.0, 40.0, 60.0, 80.0, 100.0),
        ticks=((0.0, _num(low)), (100.0, _num(high))),
        ends=("Thấp nhất", "Cao nhất"),
    )


def _gap(value: float, span: tuple[float, float]) -> Reading:
    low, high = span
    share = round(min(100.0, 100.0 * abs(value) / (high - low)), 1)
    level = _level(share, (5.0, 15.0, 30.0), ("rất nhỏ", "nhỏ", "đáng kể", "lớn"))
    edges = (0.0, 5.0, 15.0, 30.0, 100.0)
    return Reading(
        value=_num(abs(value)),
        verdict=(
            f"Chênh lệch {level} so với biên độ của chỉ số "
            f"({_num(abs(value))}, khoảng {_num(share)} % biên độ)"
        ),
        position=share,
        bands=edges,
        ticks=tuple((tick, f"{_num(tick)} %") for tick in (15.0, 30.0)),
        ends=("0 % biên độ", "100 % biên độ"),
    )


def read_metric(
    key: str, value: float, context: Mapping[str, float] | None = None
) -> Reading | None:
    """Thang đo và lời đánh giá cho một con số, theo loại chỉ số đọc từ khóa.

    None khi không có thang để đọc con số này: người gọi KHÔNG dựng thẻ.
    """
    name = _tidy(key)
    leaf = name.rsplit(".", 1)[-1]
    if leaf == "p_value":
        return _p_value(value)
    if leaf == "t_stat":
        return _t_stat(value)
    if leaf == "n":
        return None
    if ".corr.with." in name:
        return _correlation(value, trend=False)
    if ".trend.with." in name:
        return _correlation(value, trend=True)
    if ".effect_size.by." in name:
        return _effect_size(value)
    if ".eta_sq.by." in name:
        return _eta_squared(value)
    if ".r2." in name or name.endswith(".r2"):
        return _r_squared(value)
    if name.endswith(".share_pct") or ".share_pct." in name:
        return _share(value)
    head = name.split(".by.", 1)[0]
    column, _, stat = head.rpartition(".")
    if not column:
        return None
    if stat == "diff" and ".by." in name:
        span = _column_range(context, column)
        return _gap(value, span) if span else None
    if stat in STAT_WORDS:
        span = _column_range(context, column)
        return _in_range(value, stat, span) if span else None
    return None


def gauge_html(title: str, reading: Reading) -> str:
    """Thẻ HTML: tiêu đề, số to, lời đánh giá, thanh đo có vùng ngưỡng và chấm vị trí."""
    hit = next(
        (
            index
            for index in range(len(reading.bands) - 1)
            if reading.bands[index] <= reading.position <= reading.bands[index + 1]
        ),
        -1,
    )
    bands = "".join(
        f'<span class="gauge-band{" hit" if index == hit else ""}" '
        f'style="left:{start:.1f}%;width:{end - start:.1f}%"></span>'
        for index, (start, end) in enumerate(zip(reading.bands, reading.bands[1:], strict=False))
    )
    zero = (
        f'<span class="gauge-zero" style="left:{reading.zero:.1f}%"></span>'
        if reading.zero is not None
        else ""
    )
    marker = (
        f'<span class="gauge-marker" style="left:{reading.position:.1f}%" tabindex="0" '
        f'data-tip-label="{escape(reading.verdict)}" data-tip-value="{escape(reading.value)}">'
        "</span>"
    )
    ticks = "".join(
        f'<span style="left:{place:.1f}%">{escape(text)}</span>' for place, text in reading.ticks
    )
    note = f'<p class="gauge-note">{escape(reading.note)}</p>' if reading.note else ""
    return (
        f'<figure class="chart gauge" aria-label="{escape(title)}: {escape(reading.verdict)}">'
        f"<style>{GAUGE_STYLE}</style>"
        f'<p class="chart-title">{escape(title)}</p>'
        f'<div class="gauge-value">{escape(reading.value)}</div>'
        f'<p class="gauge-verdict">{escape(reading.verdict)}</p>'
        f'<div class="gauge-track">{bands}{zero}{marker}</div>'
        f'<div class="gauge-ticks">{ticks}</div>'
        f'<div class="gauge-ends"><span>{escape(reading.ends[0])}</span>'
        f"<span>{escape(reading.ends[1])}</span></div>"
        f"{note}</figure>"
    )


def gauge_for(
    key: str, value: float, title: str, context: Mapping[str, float] | None = None
) -> str:
    """Thẻ cho một con số, hoặc rỗng khi con số ấy không có thang để đọc."""
    reading = read_metric(key, value, context)
    return gauge_html(title, reading) if reading else ""
