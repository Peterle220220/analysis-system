"""Chọn chỉ số nào được gửi cho model, và nói ra cái nào bị bỏ.

Số dòng KHÔNG phải vấn đề. Không agent nào nhìn thấy một dòng dữ liệu nào -
`max_sample_rows: 0` trong manifest của cả A7 lẫn A9 - nên bốn mươi dòng và bốn
triệu dòng sinh ra **cùng một danh sách chỉ số**. Đọc bốn triệu dòng là chuyện
của pandas và DuckDB, không phải của prompt.

Số **cột** mới là vấn đề, và nó tăng theo bình phương: mỗi cặp cột số cho một hệ
số tương quan, mỗi cột nhóm nhân mỗi cột số cho một bảng so sánh. 12 cột cho 316
chỉ số; 25 cột cho 73.096 token đầu vào và một lần chạy chết.

Cái chết đó cụ thể như sau, lấy nguyên văn từ phản hồi của OpenRouter:

    finish_reason : "length"
    content       : null

Model tiêu hết ngân sách đầu ra vào phần suy nghĩ - nó đang cân nhắc rất cẩn
thận, tự nhắc mình không được bịa số - rồi bị cắt trước khi kịp viết câu trả
lời. Prompt càng to thì càng nhiều thứ để cân nhắc.

Nên phần này đặt một **ngân sách** cho prompt thay vì hy vọng nó vừa. Ba luật,
theo thứ tự:

1. Chỉ số nhắc tới cột người dùng hỏi thì lên trước. Đối chiếu bằng chữ, cố ý:
   người ta gõ tên cột y như nó nằm trong tệp.
2. Chỉ số tổng quát trước chỉ số chi tiết. Một cái trung bình chung đáng giá hơn
   trung bình của nhóm thứ mười bảy.
3. Hết ngân sách thì dừng - và **nói ra đã bỏ bao nhiêu**. Một con số vắng mặt
   và một con số không ai được báo trông giống hệt nhau, và đó là luật của cả hệ
   thống này chứ không riêng chỗ nào.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Final

# Ngân sách cho riêng danh sách chỉ số, tính bằng ký tự. Bốn ký tự đổi khoảng
# một token, nên 40.000 ký tự vào cỡ 10.000 token - đủ rộng cho một bảng bình
# thường, và còn xa mới chạm trần 120.000 của một lần gọi.
DEFAULT_BUDGET: Final[int] = 40_000

# Chỉ số nói về cả bảng, hoặc là con số đầu tiên người ta hỏi tới. Luôn ưu tiên.
HEADLINE: Final[tuple[str, ...]] = (
    "rows.total",
    ".mean",
    ".median",
    ".share_pct",
    ".count",
    ".corr.",
    ".r2.",
    ".p_value",
    ".eta_sq",
    ".f_stat",
)

# Chi tiết theo từng nhóm. Có ích, nhưng chỉ khi còn chỗ.
DETAIL: Final[str] = ".by."


def fold(text: str) -> str:
    """Chữ thường, bỏ dấu, để so tên cột với câu hỏi mà không vướng dấu."""
    stripped = "".join(
        char for char in unicodedata.normalize("NFD", text) if unicodedata.category(char) != "Mn"
    )
    return stripped.replace("đ", "d").replace("Đ", "D").lower()


def named_in(question: str, keys: list[str]) -> set[str]:
    """Những cột mà câu hỏi gọi tên.

    Đối chiếu bằng chữ chứ không bằng nghĩa, và đó là chủ ý: người dùng gõ tên
    cột y như nó nằm trong tệp - `Reason_Equity`, `Source` - nên so chữ là so
    đúng thứ họ vừa gõ. Đoán nghĩa ở đây là thêm một chỗ để đoán sai.
    """
    folded = fold(question)
    words = set(re.findall(r"[a-z0-9_]+", folded))
    found: set[str] = set()
    for key in keys:
        head = fold(key.split(".", 1)[0])
        if not head:
            continue
        # Khớp cả khi cột la `Reason_Equity` con cau hoi viet `reason_equity`,
        # va ca khi cau hoi chi noi `equity`.
        if head in words or any(part and part in words for part in head.split("_")):
            found.add(key.split(".", 1)[0])
    return found


def rank(key: str, wanted: set[str]) -> tuple[int, int, str]:
    """Thứ hạng của một chỉ số. Nhỏ hơn là được gửi trước."""
    head = key.split(".", 1)[0]
    about_asked = 0 if head in wanted else 1
    if key == "rows.total":
        kind = 0
    elif any(mark in key for mark in HEADLINE) and DETAIL not in key:
        kind = 1
    elif any(mark in key for mark in HEADLINE):
        kind = 2
    else:
        kind = 3
    return (about_asked, kind, key)


def choose(
    metrics: list[dict[str, Any]],
    question: str,
    budget: int = DEFAULT_BUDGET,
) -> tuple[list[dict[str, Any]], str]:
    """Chọn chỉ số vừa ngân sách, ưu tiên cái câu hỏi nhắc tới.

    Args:
        metrics: cả danh sách, dạng đã sẵn sàng đưa cho model.
        question: câu hỏi của người dùng.
        budget: số ký tự tối đa dành cho danh sách chỉ số.

    Returns:
        (danh sách được gửi, một dòng nói đã bỏ bao nhiêu). Dòng đó rỗng khi
        không bỏ gì - không có gì để nói thì không nói.
    """
    if not metrics:
        return [], ""

    keys = [str(item.get("key", "")) for item in metrics]
    wanted = named_in(question, keys)
    ordered = sorted(metrics, key=lambda item: rank(str(item.get("key", "")), wanted))

    kept: list[dict[str, Any]] = []
    used = 0
    for item in ordered:
        cost = len(str(item)) + 2
        if kept and used + cost > budget:
            break
        used += cost
        kept.append(item)

    # Tra ve theo dung thu tu khoa, o ca hai duong ra. Viec sap xep o tren chi
    # de CHON, khong phai de trinh bay - va hai duong ra cho hai thu tu khac
    # nhau la mot cai bay cho bat ky ai doc ket qua.
    shown = sorted(kept, key=lambda item: str(item.get("key", "")))
    if len(kept) == len(metrics):
        return shown, ""

    dropped = len(metrics) - len(kept)
    note = (
        f"Bảng có {len(metrics):,} chỉ số, chỉ đưa {len(kept):,} cái liên quan nhất "
        f"vào phân tích — {dropped:,} cái còn lại không được xét. Prompt quá lớn thì "
        "model tiêu hết chỗ vào việc cân nhắc và không kịp trả lời."
    )
    if wanted:
        note += f" Ưu tiên các cột câu hỏi nhắc tới: {', '.join(sorted(wanted))}."
    return shown, note


def rankings_for(
    ranked: list[dict[str, str]],
    shown: list[dict[str, Any]],
    question: str = "",
) -> list[dict[str, str]]:
    """Bảng xếp hạng, cắt về đúng những chỉ số đã thật sự được gửi.

    Trên một lượt chạy thật: 698 chỉ số, 511 cái được gửi vừa ngân sách, nhưng
    bảng xếp hạng vẫn đủ 352 dòng — **52 dòng trong đó trỏ tới chỉ số model
    chưa từng nhìn thấy**. Bảo ai đó "X cao nhất" về một con số không có trong
    tầm mắt họ là mời họ tin mà không kiểm được.

    Và xếp lại: cột nào câu hỏi gọi tên thì lên trước. Cùng một lượt chạy đó,
    hỏi *"kênh thông tin nào nhiều nhất"*, model đọc trúng dòng
    `Equity_Market.mean.by.Source.Television` — một xếp hạng của **đo lường
    khác** chia theo Source — rồi nói Television là kênh phổ biến nhất. Dòng
    đúng, `Source.Financial_Consultants.count`, nằm lẫn trong ba trăm dòng
    cùng chữ "cao nhat".

    Không thêm trường nào vào mỗi dòng. Hai hình dạng trước đã thử và đều
    hỏng — xem chú thích trong `findings.rankings`: thứ gì trông giống một khoá
    nằm trong cấu trúc này thì sẽ bị trích như một khoá.
    """
    seen = {str(entry.get("key", "")) for entry in shown}
    kept = [row for row in ranked if str(row.get("khoa", "")) in seen]
    if not question:
        return kept
    wanted = named_in(question, [str(row.get("khoa", "")) for row in kept])
    return sorted(kept, key=lambda row: str(row.get("khoa", "")).split(".", 1)[0] not in wanted)
