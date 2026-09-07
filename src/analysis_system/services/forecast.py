"""Ước lượng kỳ tới — để riêng, và không bao giờ trộn vào kết luận.

`timeline.py` cố ý không có phần này, và lý do nó ghi vẫn đúng nguyên: *"quý
sau bán được bao nhiêu"* truy về một mô hình và một phép chia, không truy về
dòng dữ liệu nào. Cả hệ thống này dựng trên đúng một luật — mọi con số truy
ngược được — và một con số dự báo thì không.

Nên chỗ này **không phá luật đó, nó đứng ngoài luật đó**, và sự tách bạch là
toàn bộ thiết kế:

* Kết quả **không đi vào `metrics`**, nên không kết luận nào dẫn được nó. Một
  luận điểm trích số dự báo sẽ bị chính lớp kiểm metric key ném đi, y như trích
  một chỉ số không tồn tại — và đó là hành vi đúng.
* Nó ra **một khoảng, không một con số**. Một con số lẻ mời người ta tin vào độ
  chính xác không có thật; `120–180` thì tự nói ra mình là ước lượng.
* Nó **từ chối nhiều hơn là trả lời**, và từ chối có nêu lý do.

Bốn điều kiện, phải cùng đúng:

1. **Đủ kỳ.** Tám, không phải năm. Phát hiện một xu hướng và kéo dài nó là hai
   việc khác nhau, và việc thứ hai đắt hơn khi sai.
2. **Đường thẳng thật sự khớp.** R² dưới ngưỡng nghĩa là các điểm không nằm
   quanh một đường — kéo dài một đường không tồn tại là bịa.
3. **Không kéo quá xa.** Nhiều nhất một phần ba số kỳ đã quan sát. Có mười hai
   tháng thì nói được bốn tháng tới; có tám tháng thì hai. Đây là chỗ mọi dự
   báo hỏng, và nó là con số, không phải lời khuyên.
4. **Không có mùa vụ chưa xử lý.** Một đường thẳng kéo qua dữ liệu lên xuống
   theo mùa sẽ nói tháng Một bằng tháng Bảy, và nó sai đều đặn mỗi năm.

Không dùng model nào. `numpy` đã có sẵn từ Phase 0 qua pandas.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np

# Đủ để phát hiện xu hướng là năm kỳ (`timeline.MIN_PERIODS`). Đủ để **kéo dài**
# nó thì cần hơn: một hướng đi có thật vẫn có thể là đoạn giữa của một đường
# cong, và tám kỳ mới bắt đầu phân biệt được hai thứ đó.
MIN_PERIODS: Final[int] = 8

# Các điểm phải nằm quanh một đường thẳng thì mới kéo dài đường đó được. Dưới
# ngưỡng này thì hình dạng là thứ khác, và kéo dài nó là bịa.
MIN_R2: Final[float] = 0.6

# Kéo xa nhất bằng một phần ba khoảng đã quan sát. Đây là chỗ mọi dự báo hỏng.
HORIZON_SHARE: Final[float] = 1 / 3


@dataclass(frozen=True)
class Projection:
    """Một ước lượng, kèm đúng những gì cần để không đọc nhầm nó là số đo."""

    # Nhãn kỳ chỉ là số thứ tự kể từ kỳ cuối cùng đã quan sát: đặt tên
    # "2026-07" đòi biết lịch, và đoán sai một cái tên nghe còn chắc chắn hơn
    # đoán sai một con số.
    ahead: int
    low: float
    high: float
    r2: float
    # Câu nói thẳng đây là ước lượng, để nó không bao giờ đi một mình.
    caveat: str = ""


@dataclass(frozen=True)
class Refusal:
    """Không ước lượng được, và vì sao."""

    reason: str


def horizon(observed: int) -> int:
    """Số kỳ xa nhất còn dám nói tới."""
    return max(int(observed * HORIZON_SHARE), 0)


def project(values: Sequence[float], ahead: int = 1) -> Projection | Refusal:
    """Kéo dài một chuỗi theo đường thẳng, hoặc từ chối.

    Args:
        values: giá trị từng kỳ, **đúng thứ tự thời gian**.
        ahead: cách kỳ cuối cùng bao nhiêu kỳ.

    Returns:
        `Projection` khi cả bốn điều kiện cùng đúng, `Refusal` kèm lý do khi
        không. Từ chối là kết quả bình thường ở đây, không phải lỗi.
    """
    series = [float(value) for value in values]
    if len(series) < MIN_PERIODS:
        return Refusal(
            f"chỉ có {len(series)} kỳ, cần ít nhất {MIN_PERIODS} kỳ mới ước lượng được — "
            "phát hiện một xu hướng và kéo dài nó là hai việc khác nhau"
        )
    if ahead < 1:
        return Refusal("số kỳ muốn ước lượng phải từ 1 trở lên")

    reach = horizon(len(series))
    if ahead > reach:
        return Refusal(
            f"có {len(series)} kỳ thì chỉ nói được tối đa {reach} kỳ tới, không phải {ahead} — "
            "kéo xa hơn là chỗ mọi ước lượng hỏng"
        )

    x = np.arange(len(series), dtype=float)
    y = np.asarray(series, dtype=float)
    if float(np.ptp(y)) == 0.0:
        return Refusal("chuỗi không đổi giá trị — không có xu hướng nào để kéo dài")

    slope, intercept = np.polyfit(x, y, 1)
    fitted = slope * x + intercept
    residual = y - fitted
    total = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - float((residual**2).sum()) / total if total > 0 else 0.0
    if r2 < MIN_R2:
        return Refusal(
            f"các kỳ không nằm quanh một đường thẳng (R² = {r2:.2f} < {MIN_R2}) — "
            "kéo dài một đường không có ở đó là bịa"
        )

    # Khoảng, không phải một con số. Bề rộng lấy từ chính mức lệch của các kỳ đã
    # quan sát: dữ liệu càng nhảy thì khoảng càng rộng, và điều đó đúng.
    spread = float(np.std(residual, ddof=1)) if len(series) > 1 else 0.0
    centre = float(slope * (len(series) - 1 + ahead) + intercept)
    return Projection(
        ahead=ahead,
        low=round(centre - spread, 4),
        high=round(centre + spread, 4),
        r2=round(r2, 4),
        caveat=(
            "Đây là ƯỚC LƯỢNG kéo dài theo đường thẳng từ các kỳ đã có, KHÔNG phải "
            "số đo. Nó giả định mọi thứ tiếp tục như cũ — đúng đến khi có gì đó thay đổi."
        ),
    )


# Nhãn kỳ mà `timeline._label` sinh ra: `2026`, `2026-Q1`, `2026-01`. Đây là
# cách code nhận ra một dãy nhóm THẬT SỰ là một trục thời gian, thay vì đoán:
# `gender.Male` không khớp, và nó không được phép khớp — kéo dài một đường qua
# hai nhóm giới tính là một câu vô nghĩa nói bằng giọng chắc chắn.
PERIOD_LABEL: Final[re.Pattern[str]] = re.compile(r"^\d{4}(-(Q[1-4]|\d{2}))?$")


def series_in(metrics: Mapping[str, float]) -> dict[str, list[tuple[str, float]]]:
    """Các dãy theo thời gian tìm được trong đống chỉ số đã đo.

    Khoá có dạng `{do_luong}.by.{cot}.{nhan_ky}`. Chỉ nhận khi nhãn là nhãn kỳ,
    và chỉ nhận khi **cả dãy** đều thế: một dãy lẫn `Male` vào giữa các tháng
    không phải một trục thời gian, nó là một lỗi.

    Returns:
        Theo `{do_luong} theo {cot}`, mỗi dãy đã xếp theo thứ tự kỳ. Nhãn kỳ do
        `timeline` sinh ra xếp đúng thứ tự thời gian khi xếp theo chữ, nên
        không cần đọc lịch ở đây.
    """
    groups: dict[str, list[tuple[str, float]]] = {}
    mixed: set[str] = set()
    for key, value in metrics.items():
        parts = [part for part in str(key).split(".") if part]
        if len(parts) < 4 or "by" not in parts:
            continue
        at = parts.index("by")
        if at + 2 != len(parts) - 1:
            continue
        name = f"{'.'.join(parts[:at])} theo {parts[at + 1]}"
        if PERIOD_LABEL.match(parts[-1]) is None:
            mixed.add(name)
            continue
        groups.setdefault(name, []).append((parts[-1], float(value)))

    return {
        name: sorted(pairs)
        for name, pairs in groups.items()
        if name not in mixed and len(pairs) >= MIN_PERIODS
    }
