"""Ai được phép gọi API này.

Một dashboard, một mật khẩu. Phiên đăng nhập nằm trong bộ nhớ tiến trình, nên khởi động
lại máy chủ là hết phiên: với một người dùng trên một máy thì đó là toàn bộ yêu cầu, và
nó tránh được một kho lưu phiên mà chính nó lại phải được bảo vệ và dọn dẹp.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Final

from fastapi import Request
from fastapi.responses import JSONResponse

from analysis_system.api.auth import Credential

SESSION_COOKIE: Final[str] = "asys_session"
_SESSIONS: dict[str, str] = {}


@dataclass(frozen=True)
class Guard:
    """Ai được phép nhìn vào đây."""

    credential: Credential
    secret: str

    def issue(self) -> str:
        """Một phiên mới cho người vừa chứng minh được họ là ai."""
        token = secrets.token_urlsafe(32)
        _SESSIONS[token] = self.secret
        return token

    def admits(self, token: str | None) -> bool:
        """True khi phiên này do chính máy chủ đang chạy cấp ra."""
        return bool(token) and _SESSIONS.get(token or "") == self.secret

    def forget(self, token: str | None) -> None:
        """Bỏ một phiên khi người dùng đăng xuất."""
        _SESSIONS.pop(token or "", None)


def signed_in(guard: Guard, request: Request) -> bool:
    """Request này có mang cookie phiên do máy chủ đang chạy cấp không."""
    return guard.admits(request.cookies.get(SESSION_COOKIE))


def requires_sign_in(guard: Guard, request: Request) -> JSONResponse | None:
    """Trả lỗi JSON nếu chưa đăng nhập, hoặc None khi được phép đọc."""
    if signed_in(guard, request):
        return None
    return JSONResponse(
        {
            "error": {
                "code": "unauthorized",
                "message": "Bạn cần đăng nhập để xem bảng điều khiển.",
                "hint": "Đăng nhập rồi thử lại.",
            }
        },
        status_code=401,
    )
