"""Biểu đồ vẽ thẳng bằng SVG và HTML, để trình duyệt tự dựng.

Biểu đồ hiện tại là PNG do matplotlib vẽ, và PNG có ba chỗ dở trên một trang
web: chữ mờ khi phóng to, không chọn được để sao chép, và không đổi theo nền
sáng/tối. Cả ba đều là chuyện của **cách hiển thị**, không phải chuyện của số
liệu — nên chúng thuộc về trình duyệt.

Không thêm thư viện nào: không JavaScript, không thư viện vẽ, không một dòng tải
về từ đâu cả. Nó chỉ là chuỗi ký tự, đi thẳng vào HTML.

Biểu đồ CỘT là HTML/CSS chứ không phải SVG. SVG co theo khung: khung vẽ rộng 720
đơn vị, chữ 13 đơn vị, đặt vào một thẻ hẹp thì chữ còn chưa tới 10 điểm ảnh, và
người đọc báo cáo phải nheo mắt. Chữ HTML giữ đúng cỡ ở mọi bề rộng, cột co giãn
theo phần trăm.

PNG **vẫn giữ**, và đó là chủ ý chứ không phải quên dọn: bản Word và bản báo
cáo gửi ra ngoài cần một tệp ảnh thật, và một tệp `.docx` nhúng SVG là một tệp
nhiều máy mở ra thấy ô trống.

Con số ở đây không đi qua tay model. Nhãn và giá trị đến từ chính metric key
đã đo, nên biểu đồ không phải là một chỗ nữa để một con số sai lọt qua. Dòng
kết luận trên biểu đồ cũng do code tính từ đúng những con số đó.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from html import escape
from typing import Final

from analysis_system.services.metric_gauge import gauge_for

# Nhãn dài hơn thì cắt. Cắt ở đây chứ không cắt lúc đo: con số vẫn là con số
# đầy đủ, chỉ cái nhãn hiển thị là ngắn lại; tooltip vẫn mang nhãn đầy đủ.
MAX_LABEL: Final[int] = 30

# Quá nhiều cột thì không ai đọc được nữa; phần đuôi thường là những nhóm nhỏ
# nhất và cũng là những nhóm ít nói lên điều gì nhất.
MAX_BARS: Final[int] = 12

# Một chuỗi số liệu, một sắc xanh (ô 1 của bảng màu đã kiểm cho người mù màu).
# Cột dẫn đầu đậm, các cột còn lại nhạt hơn một bậc cùng sắc: mắt thấy ngay cột
# nào cao nhất mà chưa cần đọc số. Chữ luôn mang màu chữ, không mang màu cột.
BAR_STYLE: Final[str] = (
    ".chart.bars{margin:.4rem 0;padding:.9rem 1rem 1rem;border:1px solid #e5e7eb;"
    "border-radius:.5rem;background:#fcfcfb;color:#0b0b0b;"
    'font-family:system-ui,-apple-system,"Segoe UI",sans-serif}'
    ".chart.bars .takeaway{margin:0 0 .75rem;font-size:.95rem;line-height:1.45;color:#52514e}"
    ".chart.bars .chart-title{margin:0 0 .4rem;font-size:1rem;font-weight:650;"
    "line-height:1.35;color:#0b0b0b}"
    ".chart.bars .takeaway b{color:#0b0b0b}"
    ".chart.bars .bar-row{display:grid;grid-template-columns:minmax(5.5rem,34%) minmax(0,1fr) auto;"
    "align-items:center;gap:.75rem;padding:.35rem .3rem;border-radius:.35rem;outline-offset:2px}"
    ".chart.bars .bar-row:hover,.chart.bars .bar-row:focus-visible{background:#f0efec}"
    ".chart.bars .bar-label{font-size:.95rem;color:#52514e;overflow-wrap:anywhere}"
    ".chart.bars .bar-track{height:22px;border-left:1px solid #c3c2b7}"
    ".chart.bars .bar-fill{display:block;height:100%;border-radius:0 4px 4px 0;background:#86b6ef}"
    ".chart.bars .lead .bar-fill{background:#2a78d6}"
    ".chart.bars .bar-value{font-size:1.05rem;font-weight:700;color:#0b0b0b;"
    "font-variant-numeric:tabular-nums;white-space:nowrap}"
)


def _short(label: str) -> str:
    text = str(label)
    return text if len(text) <= MAX_LABEL else text[: MAX_LABEL - 1] + "…"


def _printed(value: float) -> str:
    """Số in trên cột: số nguyên giữ nguyên, còn lại làm tròn 2 chữ số."""
    return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"


def _precise(value: float) -> str:
    """Số đầy đủ cho tooltip và dòng kết luận: tới 4 chữ số, bỏ số 0 thừa."""
    if float(value).is_integer():
        return f"{value:,.0f}"
    text = f"{value:,.4f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _gap(value: float) -> str:
    """Mức chênh. Làm tròn 2 chữ số thì 0.0096 thành 0.01, và câu chuyện mất."""
    return _printed(value) if abs(value) >= 0.01 else _precise(value)


def _with_unit(text: str, unit: str) -> str:
    return f"{text} {unit}" if unit else text


def _takeaway(usable: Sequence[tuple[str, float]], unit: str) -> str:
    """Một câu nói biểu đồ này kể gì, tính từ chính các con số, không hỏi model."""
    if len(usable) < 2:
        return ""
    ordered = sorted(usable, key=lambda item: item[1], reverse=True)
    (top_name, top), (low_name, low) = ordered[0], ordered[-1]
    if top == low:
        return f"Các nhóm bằng nhau: {escape(_with_unit(_printed(top), unit))}."
    if len(usable) == 2:
        return (
            f"<b>{escape(top_name)}</b> cao hơn {escape(low_name)}: "
            f"{escape(_with_unit(_precise(top), unit))} so với "
            f"{escape(_with_unit(_precise(low), unit))}, "
            f"chênh {escape(_with_unit(_gap(top - low), unit))}."
        )
    return (
        f"Cao nhất: <b>{escape(top_name)}</b> ({escape(_with_unit(_printed(top), unit))}). "
        f"Thấp nhất: {escape(low_name)} ({escape(_with_unit(_printed(low), unit))})."
    )


def bar_chart(
    pairs: Sequence[tuple[str, float]],
    unit: str = "",
    title: str = "",
    *,
    story: bool = False,
    heading: str = "",
) -> str:
    """Biểu đồ cột ngang, bằng HTML/CSS để chữ không co theo khung.

    Args:
        pairs: từng cặp (nhãn, giá trị), theo đúng thứ tự muốn hiện.
        unit: đơn vị in sau mỗi con số.
        title: nhãn cho trình đọc màn hình khi không có tiêu đề.
        heading: tiêu đề nhìn thấy được, nói biểu đồ đo cái gì theo cái gì.
        story: các cột so được với nhau (cùng một phép tính), nên được kèm một
            dòng kết luận. Cột trộn nhiều phép tính thì không: "p_value cao hơn
            mức chênh" là một câu vô nghĩa.

    Returns:
        Một khối `<figure>`. Chuỗi rỗng khi không có gì để vẽ: một biểu đồ không
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
    lead = max(range(len(usable)), key=lambda index: usable[index][1])

    rows: list[str] = []
    for index, (name, value) in enumerate(usable):
        width = 100.0 * value / span if value > 0 else 0.0
        mark = " lead" if index == lead else ""
        # Ca hang la vung di chuot, rong hon cai cot: khong ai phai nham trung
        # mot vach mong. tabindex de ban phim cung xem duoc nhu chuot.
        rows.append(
            f'<div class="bar-row{mark}" tabindex="0" data-tip-label="{escape(name)}" '
            f'data-tip-value="{escape(_with_unit(_precise(value), unit))}">'
            f'<span class="bar-label">{escape(_short(name))}</span>'
            f'<span class="bar-track"><span class="bar-fill" style="width:{width:.1f}%"></span>'
            f'</span><span class="bar-value">{escape(_with_unit(_printed(value), unit))}</span>'
            "</div>"
        )

    caption = _takeaway(usable, unit) if story else ""
    return (
        f'<figure class="chart bars" aria-label="{escape(heading or title or "Biểu đồ")}">'
        f"<style>{BAR_STYLE}</style>"
        + (f'<p class="chart-title">{escape(heading)}</p>' if heading else "")
        + (f'<figcaption class="takeaway">{caption}</figcaption>' if caption else "")
        + "".join(rows)
        + "</figure>"
    )


def chart_keys(keys: Sequence[str]) -> list[str]:
    """Những khóa vẽ chung được trên MỘT trục: nhóm đông nhất cùng một họ chỉ số.

    Một kết luận hay dẫn nhiều loại số cùng lúc: mức chênh, p_value, tổng số
    dòng. Vẽ chúng thành các cột cạnh nhau là đặt những đại lượng khác nhau lên
    cùng một thang đo, và cột 6.819 dòng đè bẹp cột 3,23 %. Trên lượt chạy thật,
    một biểu đồ ghi hai cột "cột nhóm" và "p_value": một bản log, không phải một
    biểu đồ.

    Một khóa thì vẽ một con số. Nhiều khóa mà không có hai khóa nào cùng họ thì
    không vẽ gì: chữ của kết luận đã mang đủ các con số đó.
    """
    from analysis_system.services.findings import split_group

    if len(keys) <= 1:
        return [str(key) for key in keys]
    families: dict[str, list[str]] = {}
    for key in keys:
        split = split_group(str(key))
        if split is not None:
            families.setdefault(split[0], []).append(str(key))
    best = max(families.values(), key=len, default=[])
    return best if len(best) >= 2 else []


# Ten tieng Viet cua phep tinh, dung o tieu de bieu do.
STAT_WORDS: Final[dict[str, str]] = {
    "mean": "Trung bình",
    "median": "Trung vị",
    "sum": "Tổng",
    "count": "Số lượng",
    "share_pct": "Tỷ lệ",
}


def chart_title(keys: Sequence[str], names: Mapping[str, str] | None = None) -> str:
    """Tiêu đề của một biểu đồ: đo cái gì, theo cái gì, bằng tên tiếng Việt.

    Các cột chỉ ghi tên nhóm ("Không phá sản", "Phá sản"); thiếu tiêu đề thì
    người đọc không biết hai cột ấy là trung bình của chỉ số nào. Tên lấy từ
    bảng chú giải, không có thì dùng tên gốc.
    """
    from analysis_system.services.findings import split_group

    if len(keys) < 2:
        return ""
    split = split_group(str(keys[0]))
    if split is None:
        return ""
    family = split[0]
    if ".by." in family:
        head, dimension = family.split(".by.", 1)
        measure, _, stat = head.rpartition(".")
        if not measure:
            return ""
        return (
            f"{STAT_WORDS.get(stat, stat)} {_find(names, measure) or measure} "
            f"theo {_find(names, dimension) or dimension}"
        )
    column, _, stat = family.rpartition(".")
    if not column:
        return ""
    return f"{STAT_WORDS.get(stat, stat)} theo {_find(names, column) or column}"


def pairs_from(
    metrics: dict[str, float],
    keys: Sequence[str],
    labels: Mapping[str, Mapping[str, str]] | None = None,
    names: Mapping[str, str] | None = None,
) -> list[tuple[str, float]]:
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

    Args:
        metrics: các con số đã đo.
        keys: các khóa cần vẽ.
        labels: nhãn tiếng Việt cho giá trị, theo cột (`value_labels`).
        names: tên tiếng Việt của cột, theo cột (từ bảng chú giải).
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
        found.append((_label_for(str(key), labels, names), float(metrics[real])))
    return found


# Ten tieng Viet cua cac phep tinh dung trong khoa `<cot so>.<phep tinh>.by.<cot nhom>`.
STAT_NAMES: Final[dict[str, str]] = {
    "diff": "Mức chênh",
    "effect_size": "Độ lớn tác động",
    "eta_sq": "Tỷ lệ phương sai giải thích",
}

# `<cot>.corr.with.<cot>`: mot he so tuong quan giua hai cot.
CORRELATION: Final[re.Pattern[str]] = re.compile(r"^(.+)\.corr\.with\.(.+)$")


def _tidy(name: str) -> str:
    return " ".join(str(name).split())


def _find(table: Mapping[str, object] | None, column: str) -> object:
    """Tra theo tên cột đã gom khoảng trắng: khóa chỉ số có thể lệch dấu cách."""
    if not table:
        return None
    if column in table:
        return table[column]
    wanted = _tidy(column)
    return next((value for name, value in table.items() if _tidy(name) == wanted), None)


def _label_for(
    key: str,
    labels: Mapping[str, Mapping[str, str]] | None = None,
    names: Mapping[str, str] | None = None,
) -> str:
    """Tên nhóm con số này nói về, đọc từ chính khoá, đổi sang tiếng Việt nếu có."""
    from analysis_system.services.findings import split_group

    # Mot he so tuong quan: noi hai cot nao, khong in moi ten cot thu hai.
    paired = CORRELATION.match(key)
    if paired and not paired.group(2).endswith((".n", ".p_value")):
        left, right = paired.group(1), paired.group(2)
        return f"Tương quan: {_find(names, left) or left} với {_find(names, right) or right}"

    split = split_group(key)
    if split is not None:
        family, group = split
        if family.endswith(".by"):
            # `<cot so>.<phep tinh>.by.<cot nhom>`: phan cuoi la COT NHOM, khong
            # phai mot nhom. Luot chay that in "0.57" voi nhan "cot nhom", va
            # khong ai doc ra do la do lon tac dong cua su khac biet.
            measure, _, stat = family[: -len(".by")].rpartition(".")
            stat_name = STAT_NAMES.get(stat, stat)
            return (
                f"{stat_name}: {_find(names, measure) or measure} "
                f"theo {_find(names, group) or group}"
            )
        column = family.split(".by.", 1)[1] if ".by." in family else family.split(".", 1)[0]
        values = _find(labels, column)
        said = values.get(group) if isinstance(values, Mapping) else None
        if said:
            return str(said)
        if ".by." in family:
            # Kem ten cot chia nhom: "y: yes" doc ro hon "yes" dung mot minh,
            # nhat la khi hai cot cung co nhom ten "yes". Dau hai cham thay cho
            # dau bang: "cot=0" la cach viet cua may, khong phai cua bao cao.
            shown = _find(names, column)
            return f"{shown or column}: {group}"
        return group
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


def _tip(name: str, value: str) -> str:
    """Thuoc tinh cho tooltip: nhan day du va con so day du, da escape."""
    return f'tabindex="0" data-tip-label="{escape(name)}" data-tip-value="{escape(value)}"'


def donut_svg(pairs: Sequence[tuple[str, float]], title: str = "", heading: str = "") -> str:
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
        tip = _tip(name, f"{_precise(value)} %")
        slices.append(
            f'<path d="M {centre} {centre} L {x1:.1f} {y1:.1f} '
            f'A {radius} {radius} 0 {large} 1 {x2:.1f} {y2:.1f} Z" fill="{colour}" {tip}/>'
        )
        legend.append(
            f'<div {tip}><span class=key style="background:{colour}"></span>'
            f"{escape(_short(name))}: <b>{value:,.2f} %</b></div>"
        )
        start = end

    return (
        '<div class="chart donut">'
        + (f'<div class="chart-title">{escape(heading)}</div>' if heading else "")
        + f'<svg viewBox="0 0 {size} {size}" width="240" height="{size}" '
        f'role="img" aria-label="{escape(heading or title or "Biểu đồ tròn")}">'
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

    width, height, pad = 720, 220, 40
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
    dots = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" class="dot"/>' for x, y in points)
    # Vung di chuot 12 don vi quanh moi diem: mot cham 8 diem anh thi khong ai
    # nham trung duoc.
    hits = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="12" class="hit" '
        f"{_tip(name, _with_unit(_precise(value), unit))}/>"
        for (x, y), (name, value) in zip(points, usable, strict=True)
    )
    ticks = "".join(
        f'<text x="{x:.1f}" y="{height - 10}" text-anchor="middle" class="lbl">'
        f"{escape(name)}</text>"
        for (x, _), (name, _) in zip(points, usable, strict=True)
    )
    ends = (
        f'<text x="{points[0][0]:.1f}" y="{points[0][1] - 10:.1f}" class="val">'
        f"{values[0]:,.2f}{escape(' ' + unit if unit else '')}</text>"
        f'<text x="{points[-1][0]:.1f}" y="{points[-1][1] - 10:.1f}" text-anchor="end" '
        f'class="val">{values[-1]:,.2f}{escape(" " + unit if unit else "")}</text>'
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" '
        f'role="img" aria-label="{escape(title or "Biểu đồ đường")}" class="chart">'
        "<style>"
        ".chart path{fill:none;stroke:#2a78d6;stroke-width:2;stroke-linejoin:round}"
        ".chart .dot{fill:#2a78d6;stroke:#fcfcfb;stroke-width:2}"
        ".chart .hit{fill:transparent;cursor:pointer}"
        ".chart .lbl{font:14px system-ui,sans-serif;fill:#52514e}"
        ".chart .val{font:700 16px system-ui,sans-serif;fill:#0b0b0b}"
        f'</style><path d="{path}"/>{dots}{hits}{ticks}{ends}</svg>'
    )


def _lone_key(keys: Sequence[str], context: Mapping[str, float] | None) -> str:
    """Khóa của con số duy nhất được vẽ: khóa có thật trong bộ số, hoặc khóa duy nhất."""
    if context:
        wanted = {_tidy(name) for name in context}
        found = [str(key) for key in keys if _tidy(key) in wanted]
        if found:
            return found[0]
    return str(keys[0]) if len(keys) == 1 else ""


def chart_for(
    pairs: Sequence[tuple[str, float]],
    unit: str = "",
    title: str = "",
    *,
    story: bool = False,
    heading: str = "",
    keys: Sequence[str] = (),
    context: Mapping[str, float] | None = None,
) -> str:
    """Biểu đồ hợp với hình dạng của chính những con số này.

    Chọn bằng **code**, theo hình dạng dữ liệu, không hỏi model. Cùng một lý do
    như mọi chỗ khác trong hệ thống: hình dạng là thứ đối chiếu được, còn ý
    thích của model thì không.

    Một con số đơn lẻ thành một THẺ có thang đo và lời đánh giá (`metric_gauge`),
    đọc theo loại chỉ số trong `keys`. Con số không có thang để đọc thì không vẽ
    gì: quy tắc toàn cục là không một thẻ số trọc nào lên trang.

    Thứ tự thử đi từ hẹp tới rộng, và cột đứng cuối vì nó đọc được với **mọi**
    hình dạng — nó là chỗ lui, không phải lựa chọn đầu tiên.
    """
    usable = [(str(name), float(value)) for name, value in pairs if value is not None]
    if len(usable) == 1:
        key = _lone_key(keys, context)
        name, value = usable[0]
        return gauge_for(key, value, name, context) if key else ""
    for drawn in (
        line_svg(pairs, unit, title),
        donut_svg(pairs, title, heading),
    ):
        if drawn:
            return drawn
    return bar_chart(pairs, unit, title, story=story, heading=heading)
