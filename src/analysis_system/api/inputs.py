"""Đọc những gì trình duyệt gửi lên thành thứ tầng dưới nhận được.

Chỉ nắn hình dạng đầu vào, không quyết định luật nào: tên luật sai thì tầng làm sạch từ
chối, và kiểm lại ở đây là làm hai lần một việc để rồi hai bên nói khác nhau.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any, Final

from fastapi import UploadFile

# Tên bộ dữ liệu do người dùng đặt. Nó trở thành mã lần chạy và một phần đường
# dẫn tệp, nên chỉ nhận chữ, số và gạch dưới.
SAFE_NAME: Final[re.Pattern[str]] = re.compile(r"[^a-z0-9_]+")
MAX_NAME: Final[int] = 40
# Gioi han kich thuoc tep tai len. Phai KHOP voi middlewareClientMaxBodySize trong
# frontend/next.config.ts va MAX_UPLOAD_BYTES trong frontend/src/lib/api.ts.
# Khong co gioi han thi mot tep lon bi doc tron vao bo nho; con o tang proxy, mot
# tep vuot muc bi cat cut roi treo toi khi het gio - va bao sai nguyen nhan.
MAX_UPLOAD_BYTES: Final[int] = 200 * 1024 * 1024


def dataset_name(raw: str, filename: str) -> str:
    """Mã lần chạy cho một tệp vừa tải lên.

    Tên người dùng gõ nếu có, không thì lấy theo tên tệp. Chỉ giữ chữ, số và
    gạch dưới: cái tên này đi thẳng vào đường dẫn tệp và mã lần chạy, và một
    tên chứa dấu gạch chéo là một tên trỏ ra ngoài thư mục nó thuộc về.
    """
    chosen = _without_marks((raw or Path(filename).stem or "du_lieu").strip()).lower()
    cleaned = SAFE_NAME.sub("_", chosen).strip("_")[:MAX_NAME]
    return cleaned or "du_lieu"


def _without_marks(text: str) -> str:
    """Bỏ dấu tiếng Việt: "báo cáo" thành "bao cao", "đ" thành "d".

    Trước đây mọi chữ có dấu bị lọc thành "_", nên "báo cáo tài chính" thành
    "b_o_c_o_t_i_ch_nh": mất chữ, và tên không còn đọc được.
    """
    plain = unicodedata.normalize("NFD", text)
    kept = "".join(char for char in plain if unicodedata.category(char) != "Mn")
    return kept.replace("đ", "d").replace("Đ", "D")


def added_rules(text: str) -> tuple[dict[str, Any], ...]:
    """Những yêu cầu làm sạch người dùng tự ghi thêm.

    Mỗi dòng một yêu cầu, dạng `tên_luật:cột1,cột2`. Dòng trống bỏ qua. Tên
    luật sai thì `decide` từ chối — kiểm tra đó thuộc về tầng dưới, và làm lại
    ở đây là làm hai lần một việc để rồi hai bên nói khác nhau.
    """
    rules: list[dict[str, Any]] = []
    for line in (text or "").splitlines():
        entry = line.strip()
        if not entry:
            continue
        rule_id, _, columns = entry.partition(":")
        named = tuple(name.strip() for name in columns.split(",") if name.strip())
        rules.append(
            {
                "rule_id": rule_id.strip(),
                "columns": named,
                "reason": "người dùng yêu cầu trực tiếp tại cổng duyệt",
            }
        )
    return tuple(rules)


def too_large(tep: UploadFile) -> str:
    """Câu báo nếu tệp vượt giới hạn, hoặc rỗng.

    Kiểm TRƯỚC khi đọc tệp vào bộ nhớ. Kích thước lấy từ chính phần multipart
    máy chủ đã nhận, không tin một con số trình duyệt tự khai.
    """
    size = tep.size or 0
    if size <= MAX_UPLOAD_BYTES:
        return ""
    return (
        f"Tệp nặng {size / 1048576:.1f} MB, vượt giới hạn "
        f"{MAX_UPLOAD_BYTES // 1048576} MB. Hãy chia nhỏ tệp hoặc bỏ bớt cột "
        "không cần rồi tải lại."
    )
