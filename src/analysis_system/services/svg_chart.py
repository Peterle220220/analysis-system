"""Biểu đồ vẽ thẳng bằng SVG, để trình duyệt tự dựng.

Biểu đồ hiện tại là PNG do matplotlib vẽ, và PNG có ba chỗ dở trên một trang
web: chữ mờ khi phóng to, không chọn được để sao chép, và không đổi theo nền
sáng/tối. Cả ba đều là chuyện của **cách hiển thị**, không phải chuyện của số
liệu — nên chúng thuộc về trình duyệt.

SVG là văn bản. Không thêm thư viện nào: không JavaScript, không thư viện vẽ,
không một dòng tải về từ đâu cả. Nó chỉ là chuỗi ký tự, đi thẳng vào HTML.

PNG **vẫn giữ**, và đó là chủ ý chứ không phải quên dọn: bản Word và bản báo
cáo gửi ra ngoài cần một tệp ảnh thật, và một tệp `.docx` nhúng SVG là một tệp
nhiều máy mở ra thấy ô trống.

Con số ở đây không đi qua tay model. Nhãn và giá trị đến từ chính metric key
đã đo, nên biểu đồ không phải là một chỗ nữa để một con số sai lọt qua.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from html import escape
from typing import Final

# Khung vẽ. Toạ độ SVG là toạ độ ảo — trình duyệt co giãn theo bề ngang thật,
# nên đây là tỷ lệ chứ không phải kích thước tính bằng điểm ảnh.
WIDTH: Final[int] = 720
BAR_HEIGHT: Final[int] = 28
GAP: Final[int] = 10
LEFT: Final[int] = 210
RIGHT_PAD: Final[int] = 90
TOP: Final[int] = 12

# Nhãn dài hơn thì cắt. Cắt ở đây chứ không cắt lúc đo: con số vẫn là con số
# đầy đủ, chỉ cái nhãn hiển thị là ngắn lại.
MAX_LABEL: Final[int] = 30

# Quá nhiều cột thì không ai đọc được nữa; phần đuôi thường là những nhóm nhỏ
# nhất và cũng là những nhóm ít nói lên điều gì nhất.
MAX_BARS: Final[int] = 12


def _short(label: str) -> str:
    text = str(label)
    return text if len(text) <= MAX_LABEL else text[: MAX_LABEL - 1] + "…"


def bar_svg(pairs: Sequence[tuple[str, float]], unit: str = "", title: str = "") -> str:
    """Biểu đồ cột ngang, dưới dạng SVG nhúng thẳng vào trang.

    Args:
        pairs: từng cặp (nhãn, giá trị), theo đúng thứ tự muốn hiện.
        unit: đơn vị in sau mỗi con số.
        title: tiêu đề, cũng là nhãn cho trình đọc màn hình.

    Returns:
        Một khối `<svg>`. Chuỗi rỗng khi không có gì để vẽ — một biểu đồ không
        cột trông y như một biểu đồ đang tải, và đó là hiểu nhầm tệ hơn.
    """
    usable = [(str(name), float(value)) for name, value in pairs if value is not None][:MAX_BARS]
    if not usable:
        return ""

    # Thang đo chạy từ 0, không từ giá trị nhỏ nhất. Cắt gốc làm một chênh lệch
    # 2 % trông như gấp đôi, và đó là cách vẽ một biểu đồ nói dối mà không có
    # con số nào sai.
    top = max(max(value for _, value in usable), 0.0)
    span = top if top > 0 else 1.0
    plot = WIDTH - LEFT - RIGHT_PAD

    height = TOP * 2 + len(usable) * (BAR_HEIGHT + GAP)
    rows: list[str] = []
    for index, (name, value) in enumerate(usable):
        y = TOP + index * (BAR_HEIGHT + GAP)
        length = max(plot * (value / span), 0.0) if value > 0 else 0.0
        printed = f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"
        rows.append(
            f'<text x="{LEFT - 8}" y="{y + BAR_HEIGHT * 0.68:.0f}" text-anchor="end" '
            f'class="lbl">{escape(_short(name))}</text>'
            f'<rect x="{LEFT}" y="{y}" width="{length:.1f}" height="{BAR_HEIGHT}" '
            f'rx="3" class="bar"/>'
            f'<text x="{LEFT + length + 8:.1f}" y="{y + BAR_HEIGHT * 0.68:.0f}" '
            f'class="val">{escape(printed)}{escape(" " + unit if unit else "")}</text>'
        )

    label = escape(title or "Biểu đồ")
    return (
        f'<svg viewBox="0 0 {WIDTH} {height}" width="100%" height="{height}" '
        f'role="img" aria-label="{label}" class="chart">'
        "<style>"
        ".chart .bar{fill:#2f6f9f}"
        ".chart .lbl{font:13px system-ui,sans-serif;fill:currentColor}"
        ".chart .val{font:13px system-ui,sans-serif;fill:currentColor;opacity:.75}"
        "</style>" + "".join(rows) + "</svg>"
    )


def pairs_from(metrics: dict[str, float], keys: Sequence[str]) -> list[tuple[str, float]]:
    """Cặp (nhãn, giá trị) lấy từ chính các metric key đã đo.

    Nhãn là **tên nhóm** mà con số đó nói về, và nó đến từ chính khoá — không
    do ai đặt tên lại. Khoá nào không có trong `metrics` thì bỏ qua: vẽ một cột
    không có số đằng sau là bịa một cột.

    Bản đầu lấy đoạn thứ hai của khoá, và trên màn hình mọi cột đều ghi
    **"mean"**: `campaign.mean.by.y.yes` có `mean` ở đúng chỗ đó. Bốn cột cạnh
    nhau mang cùng một cái nhãn thì biểu đồ không nói gì cả — tệ hơn không có
    biểu đồ, vì nó trông như có nói.

    Tên nhóm nằm ở hai chỗ khác nhau tuỳ hình dạng khoá, nên dùng lại đúng
    `findings.split_group` — chỗ đã biết cả hai hình dạng đó.
    """
    # Khop khoa theo CUNG luat voi cho chen so vao cau (findings.tidy_key).
    # Tren luot chay that, khoa trong ket luan da duoc don khoang trang con khoa
    # trong bang so do van mang mot dau cach vo hinh o dau: phan chu hien dung
    # con so, con bieu do thi lang le khong ve. Van phai khop mot chi so CO THAT
    # thi moi ve - khong lop chan nao bi noi.
    from analysis_system.services.findings import tidy_key

    by_tidy = {tidy_key(name): name for name in metrics}
    found: list[tuple[str, float]] = []
    for key in keys:
        real = key if key in metrics else by_tidy.get(tidy_key(key))
        if real is None:
            continue
        found.append((_label_for(str(key)), float(metrics[real])))
    return found


def _label_for(key: str) -> str:
    """Tên nhóm con số này nói về, đọc từ chính khoá."""
    from analysis_system.services.findings import split_group

    split = split_group(key)
    if split is not None:
        family, group = split
        # Kèm tên cột chia nhóm khi có: `y=yes` đọc rõ hơn `yes` đứng một mình,
        # nhất là khi hai cột cùng có nhóm tên `yes`.
        column = family.split(".by.", 1)[1] if ".by." in family else ""
        return f"{column}={group}" if column else group
    parts = [part for part in key.split(".") if part]
    return parts[-1] if parts else key


# --- chon loai bieu do theo HINH DANG chi so, khong hoi model -----------------

# Tong cac phan tram lech khoi 100 nhieu hon the nay thi day khong phai mot
# phep chia mot cai banh - ve hinh tron se noi doi ve mot cai toan the khong
# ton tai.
WHOLE_TOLERANCE: Final[float] = 1.0

# Hinh tron doc duoc toi chung nay lat. Hon nua thi cac lat mong hon net ve.
MAX_SLICES: Final[int] = 6

# Duong gap khuc can du diem de thanh mot duong. Ba diem thi ve gi cung ra mot
# hinh, va hinh do khong noi len xu huong nao.
MIN_POINTS: Final[int] = 4

# Nhan ky do `timeline` sinh ra: `2026`, `2026-Q1`, `2026-01`.
PERIOD: Final[re.Pattern[str]] = re.compile(r"^\d{4}(-(Q[1-4]|\d{2}))?$")


def donut_svg(pairs: Sequence[tuple[str, float]], title: str = "") -> str:
    """Hình vành khuyên, cho những phần cộng lại thành một cái toàn thể.

    Chỉ vẽ khi các phần **thật sự** cộng lại thành 100 %. Một hình tròn của
    những con số không thuộc cùng một cái bánh là một hình nói dối: mắt người
    đọc ra tỷ lệ ngay cả khi tỷ lệ ấy không có nghĩa.
    """
    usable = [(str(name), float(value)) for name, value in pairs if value is not None]
    usable = [(name, value) for name, value in usable if value > 0][:MAX_SLICES]
    if len(usable) < 2:
        return ""
    total = sum(value for _, value in usable)
    if abs(total - 100.0) > WHOLE_TOLERANCE:
        return ""

    size, radius, hole = 240, 100, 58
    centre = size / 2
    shades = ("#2f6f9f", "#57a0d3", "#8fc1e3", "#b8d8ee", "#d6e8f5", "#eef5fb")
    slices: list[str] = []
    legend: list[str] = []
    start = -90.0
    for index, (name, value) in enumerate(usable):
        sweep = 360.0 * value / 100.0
        end = start + sweep
        large = 1 if sweep > 180 else 0
        x1 = centre + radius * math.cos(math.radians(start))
        y1 = centre + radius * math.sin(math.radians(start))
        x2 = centre + radius * math.cos(math.radians(end))
        y2 = centre + radius * math.sin(math.radians(end))
        colour = shades[index % len(shades)]
        slices.append(
            f'<path d="M {centre} {centre} L {x1:.1f} {y1:.1f} '
            f'A {radius} {radius} 0 {large} 1 {x2:.1f} {y2:.1f} Z" fill="{colour}"/>'
        )
        legend.append(
            f'<div><span class=key style="background:{colour}"></span>'
            f"{escape(_short(name))}: {value:,.2f} %</div>"
        )
        start = end

    return (
        '<div class="chart donut">'
        f'<svg viewBox="0 0 {size} {size}" width="240" height="{size}" '
        f'role="img" aria-label="{escape(title or "Biểu đồ tròn")}">'
        + "".join(slices)
        + f'<circle cx="{centre}" cy="{centre}" r="{hole}" fill="var(--bg,#111)"/>'
        "</svg>"
        f"<div class=legend>{''.join(legend)}</div></div>"
    )


def line_svg(pairs: Sequence[tuple[str, float]], unit: str = "", title: str = "") -> str:
    """Đường gấp khúc, cho những giá trị **có thứ tự**.

    Chỉ vẽ khi nhãn là nhãn kỳ. Nối các nhóm không có thứ tự bằng một đường là
    vẽ ra một xu hướng không tồn tại — mắt đọc độ dốc trước khi kịp đọc nhãn.
    """
    usable = [(str(name), float(value)) for name, value in pairs if value is not None]
    if len(usable) < MIN_POINTS or not all(PERIOD.match(name) for name, _ in usable):
        return ""
    usable.sort()

    width, height, pad = 720, 200, 34
    values = [value for _, value in usable]
    low, high = min(values), max(values)
    span = (high - low) or 1.0
    step = (width - pad * 2) / (len(usable) - 1)

    points = [
        (pad + index * step, height - pad - (value - low) / span * (height - pad * 2))
        for index, (_, value) in enumerate(usable)
    ]
    path = " ".join(
        f"{'M' if index == 0 else 'L'} {x:.1f} {y:.1f}" for index, (x, y) in enumerate(points)
    )
    dots = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" class="dot"/>' for x, y in points)
    ticks = "".join(
        f'<text x="{x:.1f}" y="{height - 8}" text-anchor="middle" class="lbl">{escape(name)}</text>'
        for (x, _), (name, _) in zip(points, usable, strict=True)
    )
    ends = (
        f'<text x="{points[0][0]:.1f}" y="{points[0][1] - 8:.1f}" class="val">'
        f"{values[0]:,.2f}{escape(' ' + unit if unit else '')}</text>"
        f'<text x="{points[-1][0]:.1f}" y="{points[-1][1] - 8:.1f}" text-anchor="end" '
        f'class="val">{values[-1]:,.2f}{escape(" " + unit if unit else "")}</text>'
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" '
        f'role="img" aria-label="{escape(title or "Biểu đồ đường")}" class="chart">'
        "<style>"
        ".chart path{fill:none;stroke:#2f6f9f;stroke-width:2}"
        ".chart .dot{fill:#2f6f9f}"
        ".chart .lbl{font:11px system-ui,sans-serif;fill:currentColor;opacity:.7}"
        ".chart .val{font:12px system-ui,sans-serif;fill:currentColor}"
        f'</style><path d="{path}"/>{dots}{ticks}{ends}</svg>'
    )


def number_svg(pairs: Sequence[tuple[str, float]], unit: str = "") -> str:
    """Một con số, in to. Khi chỉ có một con số thì một cột là thừa."""
    usable = [(str(name), float(value)) for name, value in pairs if value is not None]
    if len(usable) != 1:
        return ""
    name, value = usable[0]
    printed = f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"
    return (
        '<div class="chart big">'
        f"<div class=figure>{escape(printed)}"
        f"{escape(' ' + unit if unit else '')}</div>"
        f"<div class=muted>{escape(_short(name))}</div></div>"
    )


def chart_for(pairs: Sequence[tuple[str, float]], unit: str = "", title: str = "") -> str:
    """Biểu đồ hợp với hình dạng của chính những con số này.

    Chọn bằng **code**, theo hình dạng dữ liệu, không hỏi model. Cùng một lý do
    như mọi chỗ khác trong hệ thống: hình dạng là thứ đối chiếu được, còn ý
    thích của model thì không.

    Thứ tự thử đi từ hẹp tới rộng, và cột đứng cuối vì nó đọc được với **mọi**
    hình dạng — nó là chỗ lui, không phải lựa chọn đầu tiên.
    """
    for drawn in (
        number_svg(pairs, unit),
        line_svg(pairs, unit, title),
        donut_svg(pairs, title),
    ):
        if drawn:
            return drawn
    return bar_svg(pairs, unit, title)
