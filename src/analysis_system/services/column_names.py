"""Dọn tên cột ngay ở cửa vào, một lần, cho cả hệ thống.

Bốn lỗi liên tiếp trên bốn bộ dữ liệu đều là **một họ**: một giả định về tên
cột, đóng cứng từ hồi hệ thống chỉ được thử trên dữ liệu sạch sẽ. Chủ hệ thống
vấp từng cái, mỗi bộ dữ liệu một lỗi — và đó là cách tệ nhất để tìm ra chúng.

Một lượt dò có chủ đích, ném vào những cái tên tệ nhất còn gặp trong thực tế,
chỉ ra đúng hai chỗ còn vỡ. Cả hai đều là **tên cột**, không phải dữ liệu: mọi
hình dạng bảng khác — một dòng, cột toàn rỗng, mỗi dòng một nhóm, NaN, vô cực —
đều đã chịu được.

Ba việc, và mỗi việc chữa một lỗi có thật:

* **Cắt khoảng trắng hai đầu.** ` ROA(A) before interest and % after tax` mang
  một dấu cách vô hình ở đầu, và model phải chép lại đúng ký tự không nhìn thấy
  đó vào placeholder thì con số mới hiện ra. Đòi hỏi ấy là một cái bẫy.
* **Đổi `{` `}` thành ngoặc đơn.** Placeholder viết bằng ngoặc nhọn, nên một
  tên cột chứa ngoặc nhọn thì không tài nào trỏ tới được. Trong lượt dò, 31 chỉ
  số của một cột như thế không chèn nổi vào một câu.
* **Tách tên trùng.** Hai cột cùng tên làm pandas trả về một bảng con thay vì
  một cột, và tầng thống kê vỡ với `TypeError` — một lỗi không nói gì về nguyên
  nhân.

**Không đổi gì khác.** Không hạ chữ hoa, không thay dấu cách bằng gạch dưới,
không bỏ dấu tiếng Việt. Chủ hệ thống đã nói rõ: tên cột phải giữ nguyên để
người đọc biết đang nói tới mục nào trong tệp của họ. Ba việc trên đều **không
đổi cái tên người ta đọc thấy** — một dấu cách đầu dòng và một cặp ngoặc nhọn
là thứ không ai đánh mất khi nhìn.

Và mọi thay đổi đều được **kể lại**. Đổi tên cột trong im lặng là chuyện người
dùng chỉ phát hiện ra khi câu hỏi của họ không khớp cột nào.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

import pandas as pd

# Ngoặc nhọn là cú pháp của placeholder. Một tên cột chứa chúng thì không trỏ
# tới được, nên chúng đổi thành ngoặc đơn — đọc lên vẫn y hệt.
BRACES: Final[dict[str, str]] = {"{": "(", "}": ")"}

# Cột không có tên. Xảy ra khi tệp có cột thừa hoặc dòng tiêu đề khuyết.
UNNAMED: Final[str] = "cot"


def _swap_braces(name: str) -> str:
    for old, new in BRACES.items():
        name = name.replace(old, new)
    return name


def tidied_names(raw_names: Sequence[object]) -> tuple[list[str], list[str]]:
    """Tên cột đã dọn, và những gì đã đổi — chỉ làm việc trên TÊN.

    Tách khỏi `tidy` để cùng một luật trả lời được hai câu hỏi khác nhau: *"dọn
    bảng này đi"* và *"bảng đã nằm trên đĩa kia có cần dọn không"*. Hai bản sao
    của một luật là hai câu trả lời đang chờ để mâu thuẫn với nhau.
    """
    notes: list[str] = []
    seen: dict[str, int] = {}
    names: list[str] = []

    for position, raw in enumerate(raw_names, start=1):
        was = str(raw)
        name = _swap_braces(was.strip())
        if not name:
            name = f"{UNNAMED}_{position}"

        if name != was:
            notes.append(f"cột {was!r} đổi thành {name!r}")

        # Tach ten trung. Hai cot cung ten lam pandas tra ve mot bang con thay
        # vi mot cot, va tang thong ke vo voi mot TypeError khong noi gi ve
        # nguyen nhan.
        seen[name] = seen.get(name, 0) + 1
        if seen[name] > 1:
            unique = f"{name}__{seen[name]}"
            notes.append(f"cột {name!r} bị trùng tên, cột thứ {seen[name]} đổi thành {unique!r}")
            name = unique
            seen[name] = 1

        names.append(name)

    return names, notes


def would_change(raw_names: Sequence[object]) -> list[str]:
    """Những gì việc dọn tên sẽ đổi, nếu chạy trên bộ tên này.

    Dùng để hỏi một bảng **đã làm sạch từ trước**: nó có mang những cái tên mà
    bản hôm nay đã biết cách dọn không.

    Chuyện này có thật và nó im lặng. Một bảng 96 cột được làm sạch bằng bản cũ
    giữ nguyên 95 cái tên có dấu cách thừa ở đầu; bản sửa ra đời sau đó **không
    quay lại sửa những bảng đã nằm trên đĩa**. Người dùng hỏi, cột không khớp,
    và không có gì trên màn hình nối hai chuyện đó lại với nhau.
    """
    return tidied_names(raw_names)[1]


def tidy(frame: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Tên cột đã dọn, và những gì đã đổi.

    Args:
        frame: bảng vừa đọc từ tệp.

    Returns:
        (bảng mới, danh sách thay đổi để kể lại). Danh sách rỗng nghĩa là tên
        cột vốn đã dùng được — trường hợp thường gặp, và không nói gì là đúng.
    """
    names, notes = tidied_names(list(frame.columns))
    if not notes:
        return frame, []
    tidied = frame.copy()
    tidied.columns = pd.Index(names)
    return tidied, notes
