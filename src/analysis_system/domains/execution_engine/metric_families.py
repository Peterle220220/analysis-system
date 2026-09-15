"""Chỉ số gom thành họ theo cột, thay vì một danh sách phẳng dài.

Manager nhận tới bốn mươi nghìn ký tự chỉ số, phẳng, xếp theo tên khoá:

    Source.Financial_Consultants.count
    Source.Financial_Consultants.share_pct
    Source.Internet.count
    ...

Đọc được, nhưng phải tự nhận ra `Source.*` là một bảng phân rã còn
`age.mean` là một con số lẻ. Và trên một lượt chạy thật nó nhận sai: hỏi về
mục tiêu tiết kiệm thì lấy `PPF` — một cột nằm cạnh trong danh sách phẳng.

Gom lại theo cột thì cấu trúc đó hiện ra sẵn, không phải suy ra. Cột nào câu
hỏi có gọi tên thì lên đầu và được đánh dấu — dùng lại đúng `shortlist.named_in`
đã có, so bằng chữ chứ không đoán nghĩa.

**Khoá giữ nguyên vẹn từng ký tự.** Đó là điều kiện duy nhất không được phá:
model trích khoá ra để viết `{khoa}`, và một khoá bị cắt ngắn hay ghép lại là
một khoá không tồn tại. Dự án này đã trả giá cho đúng chuyện đó một lần — khoá
ghép lại từ các mảnh cho ra `cot_2.count.joy` trong khi chỉ số thật là
`cot_2.joy.count`, và mọi kết luận xếp hạng bị loại vì dẫn một chỉ số chưa từng
được tính.

Nên ở đây chỉ **xếp lại chỗ ngồi**, không viết lại gì cả. Mỗi mục đi ra vẫn là
đúng cái dict đã đi vào.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from analysis_system.domains.ai_planner.shortlist import named_in

# Chỉ số lẻ - `rows.total`, `age.mean` - không thuộc bảng phân rã nào. Gom
# chúng vào một họ có tên thay vì để mỗi cái một họ một phần tử.
LOOSE: str = "(chỉ số lẻ)"

# Dưới ngưỡng này thì gọi là họ cũng không giúp gì: một họ một phần tử chỉ thêm
# một tầng ngoặc cho người đọc.
MIN_FAMILY: int = 2


def family_of(key: str) -> str:
    """Cột mà chỉ số này thuộc về — đoạn đầu của khoá."""
    head = str(key).split(".", 1)[0]
    return head or LOOSE


def grouped(metrics: Sequence[dict[str, Any]], question: str = "") -> list[dict[str, Any]]:
    """Các chỉ số, gom theo cột.

    Args:
        metrics: danh sách phẳng, dạng đã sẵn sàng đưa cho model.
        question: câu hỏi, để biết cột nào được gọi tên.

    Returns:
        Một mục cho mỗi cột, cột được hỏi tên đứng trước. Thứ tự các chỉ số bên
        trong giữ nguyên như lúc đi vào - `shortlist.choose` đã xếp theo mức
        quan trọng rồi, và xếp lại lần nữa là hai chỗ cùng trả lời một câu hỏi.
    """
    families: dict[str, list[dict[str, Any]]] = {}
    for entry in metrics:
        families.setdefault(family_of(str(entry.get("key", ""))), []).append(entry)

    # Họ một phần tử gộp về chỗ chỉ số lẻ, giữ nguyên thứ tự chúng đã có.
    loose: list[dict[str, Any]] = []
    kept: dict[str, list[dict[str, Any]]] = {}
    for name, entries in families.items():
        if name == LOOSE or len(entries) < MIN_FAMILY:
            loose.extend(entries)
        else:
            kept[name] = entries

    asked = named_in(question, list(kept)) if question else set()
    ordered = sorted(kept, key=lambda name: (name not in asked, name))

    out: list[dict[str, Any]] = [
        {
            "cot": name,
            # Cột câu hỏi gọi thẳng tên. Đối chiếu bằng chữ, không đoán nghĩa -
            # người dùng gõ tên cột y như nó nằm trong tệp.
            "cau_hoi_co_nhac_toi": name in asked,
            "chi_so": kept[name],
        }
        for name in ordered
    ]
    if loose:
        out.append({"cot": LOOSE, "cau_hoi_co_nhac_toi": False, "chi_so": loose})
    return out
