"""Câu trả lời thẳng, đứng trước mọi bằng chứng.

Chủ hệ thống đọc một câu trả lời và viết: *"tôi cảm giác như hệ thống đang hành
xử giống một cỗ máy in báo cáo thống kê hơn là một chuyên gia phân tích"*. Đúng,
và chẩn đoán đi kèm cũng đúng: các lớp chống bịa số đã ép Manager làm việc **từ
dưới lên** — dịch từng phép đo thành một gạch đầu dòng rời rạc, rồi dừng. Không
bước nào ngoảnh lại hỏi *"những con số này đã trả lời câu hỏi chưa"*.

Hỏi *"poutcome hay campaign ảnh hưởng mạnh hơn"*, người ta chờ nghe **"poutcome
mạnh hơn"**. Ba đoạn số liệu đúng mà không có câu đó thì người đọc phải tự làm
nốt việc mà hệ thống đáng lẽ làm hộ.

Nên có một chỗ để nói câu đó, và chỗ đó phải **nới về câu chữ mà không nới về
số**:

* **Không bắt dẫn metric key.** Một câu chốt như *"poutcome ảnh hưởng mạnh hơn
  campaign"* không có con số nào để dẫn, và ép nó dẫn là ép nó nói vòng.
* **Vẫn cấm gõ số trực tiếp.** Đây là chỗ được đọc nhiều nhất trang, nên nó là
  chỗ tệ nhất để một con số bịa lọt qua. Muốn có số thì viết `{ten_chi_so}` như
  mọi chỗ khác, và code chèn giá trị thật vào.

Đó là toàn bộ sự nới lỏng, và nó nới đúng thứ đang trói: **cách diễn đạt**, chứ
không phải **quyền khẳng định một con số**.

Câu chốt hỏng thì bị bỏ, không làm hỏng cả câu trả lời. Mất một câu tóm tắt thì
người đọc vẫn còn đủ bằng chứng bên dưới; mất cả câu trả lời thì không còn gì.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Final

from analysis_system.services.findings import (
    BARE_DIGIT,
    NAME_PLACEHOLDER,
    PLACEHOLDER,
    strip_known_labels,
)

if TYPE_CHECKING:  # pragma: no cover - chỉ dùng cho kiểu
    from analysis_system.contracts.agents import MetricValue

# Dài hơn thế này thì nó không còn là một câu chốt, nó là một đoạn nữa — và cả
# vấn đề ở đây là người đọc có một câu để đọc trước khi đọc mọi thứ.
MAX_LENGTH: Final[int] = 400


def problems_with(summary: str, metrics: Mapping[str, MetricValue]) -> list[str]:
    """Mọi thứ sai với câu chốt này.

    Returns:
        Danh sách vấn đề. Rỗng nghĩa là dùng được.
    """
    text = str(summary).strip()
    if not text:
        return ["cau chot rong"]
    if len(text) > MAX_LENGTH:
        return [f"cau chot dai {len(text)} ky tu, toi da {MAX_LENGTH}"]

    problems: list[str] = []
    bare = PLACEHOLDER.sub("", NAME_PLACEHOLDER.sub("", text))
    if BARE_DIGIT.search(strip_known_labels(bare, metrics)):
        # Cung mot luat nhu moi luan diem khac, va co y giu nguyen: day la cho
        # duoc doc nhieu nhat trang, nen la cho te nhat de mot con so bia lot.
        problems.append("cau chot co con so go truc tiep - moi so phai la placeholder {ten_chi_so}")
    for match in PLACEHOLDER.finditer(text):
        if match.group(1) not in metrics:
            problems.append(f"cau chot dan chi so khong co that: {match.group(1)}")
    return problems


def usable(summary: str, metrics: Mapping[str, MetricValue]) -> bool:
    """Câu chốt này có dùng được không."""
    return not problems_with(summary, metrics)
