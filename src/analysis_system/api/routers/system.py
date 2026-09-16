"""Những trang đọc chung: health, trang chủ, mục Dữ liệu, Dashboard, và trang Hệ thống.

Kết quả kiểm bản mới và câu báo sau khi cập nhật là **của lần bấm vừa rồi**, không phải
trạng thái lâu dài của hệ thống, nên chúng nằm trong bộ nhớ của chính app này. Ghi ra đĩa
thì phải nghĩ chuyện dọn, chuyện cũ mèm, chuyện hai tiến trình cùng ghi, cho một câu chữ
sống đúng vài giây. Mất khi khởi động lại, và điều đó đúng: khởi động lại xong thì câu
"đang khởi động lại" không còn nghĩa gì nữa.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from analysis_system.api.replies import error
from analysis_system.api.session import Guard, requires_sign_in
from analysis_system.api.view import dashboard as dashboard_payload
from analysis_system.api.view import data_page as data_payload
from analysis_system.api.view import home as home_payload
from analysis_system.api.view import system as system_payload
from analysis_system.application.workspace import Workspace
from analysis_system.core import updater


class _Held:
    """Một thứ giữ lại giữa hai request, trong bộ nhớ tiến trình này."""

    def __init__(self, empty: Any) -> None:
        self._empty = empty
        self._value = empty

    def put(self, value: Any) -> None:
        self._value = value

    def get(self) -> Any:
        return self._value


def router(space: Workspace, guard: Guard) -> APIRouter:
    """Các route đọc, cộng hai nút của trang Hệ thống."""
    routes = APIRouter()
    last_check = _Held(updater.Update())
    note = _Held("")

    def version_payload() -> dict[str, Any]:
        repo = updater.repo_root()
        payload: dict[str, Any] = system_payload(
            updater.current(repo), last_check.get(), note.get(), updater.stale(repo)
        )
        return payload

    @routes.get("/api/health")
    def api_health() -> JSONResponse:
        """Liveness check không cần đăng nhập, cho proxy và service."""
        return JSONResponse({"ok": True, "service": "analysis-system"})

    @routes.get("/api/home")
    def api_home(request: Request) -> Response:
        denied = requires_sign_in(guard, request)
        if denied is not None:
            return denied
        return JSONResponse(home_payload(space))

    @routes.get("/api/data")
    def api_data(request: Request) -> Response:
        denied = requires_sign_in(guard, request)
        if denied is not None:
            return denied
        return JSONResponse(data_payload(space))

    @routes.get("/api/dashboard")
    def api_dashboard(request: Request) -> Response:
        denied = requires_sign_in(guard, request)
        if denied is not None:
            return denied
        return JSONResponse(dashboard_payload(space))

    @routes.get("/api/system")
    def api_system(request: Request) -> Response:
        denied = requires_sign_in(guard, request)
        if denied is not None:
            return denied
        return JSONResponse(version_payload())

    @routes.post("/api/system/check")
    def api_check_updates(request: Request) -> Response:
        denied = requires_sign_in(guard, request)
        if denied is not None:
            return denied
        last_check.put(updater.check(updater.repo_root()))
        return JSONResponse(version_payload())

    @routes.post("/api/system/apply")
    def api_apply_update(request: Request) -> Response:
        denied = requires_sign_in(guard, request)
        if denied is not None:
            return denied
        done = updater.apply(updater.repo_root())
        if done.problem:
            return error("update_failed", done.problem, 409)
        last_check.put(updater.Update())
        note.put(f"{done.was} → {done.now}. " + updater.restart_after_reply())
        return JSONResponse(version_payload())

    return routes
