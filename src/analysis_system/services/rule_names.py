"""Tên luật làm sạch, viết bằng tiếng người — kèm ví dụ nó sẽ làm gì.

Trước đây ô duyệt hiện đúng `cast_numeric_safe (Objective, PPF, Gold)`. Người
dùng mới không biết `cast_numeric_safe` nghĩa là gì, và họ đang được hỏi có
đồng ý cho nó **sửa dữ liệu của mình** hay không. Đọc không hiểu thì họ không
duyệt — họ đoán.

Mỗi luật có ba phần, và cả ba đều cần:

* **tên** — việc nó làm, nói bằng một câu tiếng Việt
* **ví dụ** — một giá trị cụ thể trước và sau. Một câu mô tả trừu tượng vẫn để
  người ta phải tưởng tượng; `"34"` thành `34` thì không.
* **mã** — `cast_numeric_safe`. Vẫn hiện, vì nó là thứ khớp với nhật ký chạy
  và với những gì hệ thống ghi lại; người vận hành cần nó.

Tên cột thì **giữ nguyên**, không dịch. Chủ hệ thống đã nói rõ: đó là dữ liệu
của họ, và đổi tên cột đi thì họ không biết đang nói tới mục nào.

Luật nào chưa có tên ở đây thì hiện nguyên mã, không bịa. Một cái tên tiếng
Việt đoán bừa cho một luật không rõ còn tệ hơn một cái mã khó đọc: mã khó đọc
thì người ta hỏi lại, tên sai thì người ta duyệt.
"""

from __future__ import annotations

from typing import Final, NamedTuple


class RuleName(NamedTuple):
    """Một luật, nói bằng tiếng người."""

    title: str
    example: str


NAMES: Final[dict[str, RuleName]] = {
    "trim_whitespace": RuleName(
        "Cắt khoảng trắng thừa ở đầu và cuối ô",
        'ví dụ: "  Hà Nội  " thành "Hà Nội"',
    ),
    "normalize_unicode_nfc": RuleName(
        "Thống nhất cách gõ dấu tiếng Việt",
        'ví dụ: "Hà Nội" gõ hai kiểu khác nhau được đưa về cùng một kiểu, '
        "để hai dòng giống nhau không bị đếm thành hai",
    ),
    "replace_sentinel_with_null": RuleName(
        "Coi các ô đánh dấu là để trống",
        'ví dụ: "N/A", "-", "null" được hiểu là không có dữ liệu, thay vì là một giá trị có thật',
    ),
    "standardize_datetime": RuleName(
        "Đưa ngày tháng về một định dạng",
        'ví dụ: "01/02/2023" và "2023-02-01" thành cùng một ngày',
    ),
    "cast_numeric_safe": RuleName(
        "Chuyển cột đang lưu dạng chữ về dạng số",
        'ví dụ: "34" thành 34, để còn tính trung bình được',
    ),
    "merge_text_variants": RuleName(
        "Gộp các cách viết khác nhau của cùng một giá trị",
        'ví dụ: "Khách hàng", "khach hang" và "KHÁCH HÀNG" được gộp thành một '
        "nhóm, để không bị đếm thành ba nhóm khác nhau",
    ),
    "cast_words_to_numbers": RuleName(
        "Đổi số viết bằng chữ thành chữ số",
        'ví dụ: "một" thành 1, "hai mươi mốt" thành 21, "một triệu" thành 1000000',
    ),
    "drop_exact_duplicates": RuleName(
        "Bỏ những dòng trùng nhau hoàn toàn",
        "ví dụ: hai dòng giống nhau từng ô thì chỉ giữ lại một",
    ),
    "flag_missing_required": RuleName(
        "Đánh dấu những dòng thiếu ô bắt buộc",
        "chỉ đánh dấu để biết mà tránh, không xoá dòng nào",
    ),
    "unpivot_periods": RuleName(
        "Xoay dọc bảng nằm ngang: mỗi kỳ thành một dòng",
        'ví dụ: dòng "Lợi nhuận sau thuế" với các cột Q1-2026, Q2-2026 thành các dòng '
        "Chỉ tiêu | Kỳ báo cáo | Giá trị",
    ),
}


def title_of(rule_id: str) -> str:
    """Tên tiếng Việt của luật, hoặc chính mã nếu chưa đặt tên."""
    named = NAMES.get(rule_id)
    return named.title if named else rule_id


def example_of(rule_id: str) -> str:
    """Ví dụ cụ thể luật này sẽ làm gì, hoặc rỗng."""
    named = NAMES.get(rule_id)
    return named.example if named else ""


def labelled(rule_id: str, columns: str = "") -> str:
    """Dòng người dùng đọc để quyết định có duyệt hay không.

    Tên cột đi kèm nguyên văn: người duyệt cần biết luật này đụng vào mục nào
    trong dữ liệu **của họ**, và cái tên trong tệp là thứ họ nhận ra.
    """
    title = title_of(rule_id)
    return f"{title} ({columns})" if columns else title


def in_plain_words(text: str) -> str:
    """Thay mã luật trong một câu bằng tên tiếng Việt của nó.

    Câu báo lỗi đi thẳng lên màn hình người dùng, và `replace_sentinel_with_null`
    ở đó cũng khó đọc y như ở ô duyệt. Mã luật vẫn còn, trong ngoặc vuông, cho
    người vận hành đối chiếu với nhật ký.
    """
    found = str(text)
    for rule_id, named in NAMES.items():
        for spelling in (f"'{rule_id}'", f'"{rule_id}"', rule_id):
            if spelling in found:
                found = found.replace(spelling, f"'{named.title}' [{rule_id}]")
                break
    return found
