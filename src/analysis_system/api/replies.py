"""Hình dạng của một câu trả lời lỗi, và những phép kiểm mọi route đều làm.

Một mã lỗi, một câu cho người đọc, và một gợi ý việc cần làm. Mọi route dùng chung hàm
này để giao diện chỉ phải hiểu đúng một hình dạng.
"""

from __future__ import annotations

import re
from typing import Any, Final

from fastapi import Request
from fastapi.responses import JSONResponse

# Ma trong URL co the tro toi thu muc lan chay, nen tu choi cu phap duong dan.
SAFE_ID: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9_]+$")
MAX_ID: Final[int] = 128
# Ma ngan cua mot ban Tu phan tich da luu hay mot Dashboard: 12 ky tu hex.
SHORT_ID: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{12}")


def error(code: str, message: str, status_code: int, hint: str = "") -> JSONResponse:
    """Một lỗi JSON: mã để máy đọc, câu chữ để người đọc."""
    body: dict[str, Any] = {"code": code, "message": message}
    if hint:
        body["hint"] = hint
    return JSONResponse({"error": body}, status_code=status_code)


def id_is_safe(value: str) -> bool:
    """Mã này có phải là một mã, chứ không phải một đường dẫn."""
    return bool(value) and len(value) <= MAX_ID and SAFE_ID.fullmatch(value) is not None


def invalid_id(value: str) -> JSONResponse:
    """Câu trả lời cho một mã không hợp lệ."""
    return error("invalid_id", f"Mã không hợp lệ: {value!r}.", 400)


def dataset_missing() -> JSONResponse:
    """Câu trả lời cho một bộ dữ liệu không có thật."""
    return error("dataset_not_found", "Không có bộ dữ liệu này.", 404)


async def json_body(request: Request) -> dict[str, Any]:
    """Thân request dạng JSON, hoặc rỗng khi nó không phải một object."""
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}
