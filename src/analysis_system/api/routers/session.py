"""Phiên đăng nhập: hỏi phiên, đăng nhập, đăng xuất.

Giao diện Next đăng nhập qua đây. Phiên là cookie do Guard cấp, nằm trong bộ nhớ.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from analysis_system.api.replies import json_body
from analysis_system.api.session import SESSION_COOKIE, Guard, signed_in
from analysis_system.api.view import session_payload


def router(guard: Guard) -> APIRouter:
    """Ba route của phiên, gắn với một Guard."""
    routes = APIRouter()

    @routes.get("/api/session")
    def api_session(request: Request) -> Response:
        """Trạng thái phiên, để trang biết vẽ màn hình nào mà không cần redirect."""
        return JSONResponse(session_payload(signed_in(guard, request)))

    @routes.post("/api/session")
    async def api_session_sign_in(request: Request) -> Response:
        """Đăng nhập bằng JSON: đúng thì cấp cookie, sai thì 401 kèm lỗi."""
        body = await json_body(request)
        password = str(body.get("password") or "")
        if not guard.credential.matches(password):
            # Một câu duy nhất, không nói phần nào sai: chỉ có một tài khoản.
            return JSONResponse(
                session_payload(False) | {"error": "Sai mật khẩu."}, status_code=401
            )
        answer = JSONResponse(session_payload(True))
        answer.set_cookie(SESSION_COOKIE, guard.issue(), httponly=True, samesite="strict")
        return answer

    @routes.delete("/api/session")
    def api_session_sign_out(request: Request) -> Response:
        """Đăng xuất bằng JSON: xoá phiên trong bộ nhớ và cookie trên trình duyệt."""
        guard.forget(request.cookies.get(SESSION_COOKIE))
        answer = JSONResponse(session_payload(False))
        answer.delete_cookie(SESSION_COOKIE)
        return answer

    return routes
