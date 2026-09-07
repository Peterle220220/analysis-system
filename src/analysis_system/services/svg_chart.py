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
    found: list[tuple[str, float]] = []
    for key in keys:
        if key not in metrics:
            continue
        found.append((_label_for(str(key)), float(metrics[key])))
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
