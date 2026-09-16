"""Dashboard: trang trình bày ghép widget từ cả hai luồng.

Widget chỉ giữ nguồn (cấu hình kéo thả, lượt hỏi cùng số thứ tự kết luận, văn bản);
trang tính lại mỗi lần mở. Sổ ghi ở gốc thư mục runs.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from analysis_system.api.replies import SHORT_ID, error
from analysis_system.api.session import Guard, requires_sign_in
from analysis_system.application.workspace import Workspace
from analysis_system.domains.visualization.dashboards import (
    DashboardError,
    Widget,
    WidgetDraft,
    add_widget,
    create_dashboard,
    delete_dashboard,
    get_dashboard,
    list_dashboards,
    replace_dashboard,
)


def router(space: Workspace, guard: Guard) -> APIRouter:
    """Các route của Dashboard, gắn với một workspace."""
    routes = APIRouter()

    def boards_root() -> Path:
        return Path(space.settings.layers.runs)

    def board_missing() -> Response:
        return error("unknown_dashboard", "Không có Dashboard này.", 404, "")

    @routes.get("/api/dashboards")
    def api_dashboards(request: Request) -> Response:
        denied = requires_sign_in(guard, request)
        if denied is not None:
            return denied
        boards = [
            {
                "id": board.id,
                "name": board.name,
                "widgets": len(board.widgets),
                "updated_at": board.updated_at,
            }
            for board in list_dashboards(boards_root())
        ]
        return JSONResponse({"dashboards": boards})

    @routes.post("/api/dashboards")
    async def api_create_dashboard(request: Request) -> Response:
        denied = requires_sign_in(guard, request)
        if denied is not None:
            return denied
        try:
            body = await request.json()
            name = str(body.get("name") or "") if isinstance(body, dict) else ""
            board = create_dashboard(boards_root(), name)
        except DashboardError as failure:
            return error("bad_dashboard", str(failure), 400, "")
        except ValueError:
            return error("bad_dashboard", "Yêu cầu không hợp lệ.", 400, "")
        return JSONResponse(board.model_dump(), status_code=201)

    @routes.get("/api/dashboards/{board_id}")
    def api_dashboard_one(request: Request, board_id: str) -> Response:
        denied = requires_sign_in(guard, request)
        if denied is not None:
            return denied
        board = get_dashboard(boards_root(), board_id) if SHORT_ID.fullmatch(board_id) else None
        return board_missing() if board is None else JSONResponse(board.model_dump())

    @routes.put("/api/dashboards/{board_id}")
    async def api_save_dashboard(request: Request, board_id: str) -> Response:
        """Ghi lại tên và toàn bộ widget: đổi chỗ, đổi cỡ, sửa chữ, xoá widget."""
        denied = requires_sign_in(guard, request)
        if denied is not None:
            return denied
        if not SHORT_ID.fullmatch(board_id):
            return board_missing()
        try:
            body = await request.json()
            if not isinstance(body, dict) or not isinstance(body.get("widgets"), list):
                raise ValueError("can name va widgets")
            widgets = [Widget.model_validate(item) for item in body["widgets"]]
        except ValueError as failure:
            return error("bad_dashboard", "Dashboard không hợp lệ.", 400, str(failure)[:300])
        try:
            board = replace_dashboard(boards_root(), board_id, str(body.get("name") or ""), widgets)
        except DashboardError as failure:
            missing = get_dashboard(boards_root(), board_id) is None
            return board_missing() if missing else error("bad_dashboard", str(failure), 400, "")
        return JSONResponse(board.model_dump())

    @routes.post("/api/dashboards/{board_id}/widgets")
    async def api_pin_widget(request: Request, board_id: str) -> Response:
        """Ghim: thêm một widget vào cuối lưới của Dashboard này."""
        denied = requires_sign_in(guard, request)
        if denied is not None:
            return denied
        if not SHORT_ID.fullmatch(board_id) or get_dashboard(boards_root(), board_id) is None:
            return board_missing()
        try:
            draft = WidgetDraft.model_validate(await request.json())
        except ValueError as failure:
            return error("bad_widget", "Widget không hợp lệ.", 400, str(failure)[:300])
        try:
            board = add_widget(boards_root(), board_id, draft)
        except DashboardError as failure:
            return error("bad_widget", str(failure), 400, "")
        return JSONResponse(board.model_dump(), status_code=201)

    @routes.delete("/api/dashboards/{board_id}")
    def api_delete_dashboard(request: Request, board_id: str) -> Response:
        denied = requires_sign_in(guard, request)
        if denied is not None:
            return denied
        if not SHORT_ID.fullmatch(board_id) or not delete_dashboard(boards_root(), board_id):
            return board_missing()
        return JSONResponse({"deleted": board_id})

    return routes
