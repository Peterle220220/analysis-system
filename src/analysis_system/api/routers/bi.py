"""Tự phân tích: kéo thả cột thành bảng và biểu đồ, và các bản đã lưu.

Mọi con số ở đây do DuckDB tính từ bảng sạch; không bước nào gọi model.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from analysis_system.api.replies import (
    SHORT_ID,
    dataset_missing,
    error,
    id_is_safe,
    invalid_id,
)
from analysis_system.api.session import Guard, requires_sign_in
from analysis_system.application.workspace import Workspace
from analysis_system.core.settings import resolve
from analysis_system.domains.visualization.bi_query import BiQuery, BiQueryError, field_values
from analysis_system.domains.visualization.bi_query import run_query as run_bi_query
from analysis_system.domains.visualization.bi_schema import FileSchema, schema_of_file
from analysis_system.domains.visualization.bi_views import (
    ViewError,
    ViewState,
    delete_view,
    list_views,
    save_view,
)


def router(space: Workspace, guard: Guard) -> APIRouter:
    """Các route của Tự phân tích, gắn với một workspace."""
    routes = APIRouter()

    def source_of(request: Request, dataset: str) -> tuple[Path, FileSchema] | Response:
        """Tệp Parquet của bảng sạch và schema của nó, hoặc một phản hồi lỗi."""
        denied = requires_sign_in(guard, request)
        if denied is not None:
            return denied
        if not id_is_safe(dataset):
            return invalid_id(dataset)
        if not space.knows(dataset):
            return dataset_missing()
        try:
            table = space.clean_table(dataset)
            if table is None:
                return error(
                    "clean_not_ready",
                    "Bộ dữ liệu này chưa có bảng sạch. Hãy duyệt bước làm sạch trước.",
                    409,
                    "",
                )
            source = resolve(table.uri, space.settings)
            return source, schema_of_file(source)
        except (OSError, ValueError) as failure:
            return error("clean_unreadable", str(failure), 404, "")

    def views_dir(request: Request, dataset: str) -> Path | Response:
        """Thư mục của bộ dữ liệu (nơi lưu các bản), hoặc một phản hồi lỗi."""
        denied = requires_sign_in(guard, request)
        if denied is not None:
            return denied
        if not id_is_safe(dataset):
            return invalid_id(dataset)
        if not space.knows(dataset):
            return dataset_missing()
        return Path(space.settings.layers.runs) / dataset

    @routes.get("/api/bi/{dataset}/schema")
    def api_bi_schema(request: Request, dataset: str) -> Response:
        """Các cột của bảng sạch, đã chia Dimension/Measure, cho thanh bên kéo thả."""
        found = source_of(request, dataset)
        if isinstance(found, Response):
            return found
        _, schema = found
        return JSONResponse(
            {
                "dataset_id": dataset,
                "rows": schema.rows,
                "fields": [field.as_dict() for field in schema.fields],
            }
        )

    @routes.get("/api/bi/{dataset}/values")
    def api_bi_values(request: Request, dataset: str, field: str = "") -> Response:
        """Giá trị để chọn trong bộ lọc của một cột."""
        found = source_of(request, dataset)
        if isinstance(found, Response):
            return found
        source, schema = found
        chosen = next((item for item in schema.fields if item.name == field), None)
        if chosen is None:
            return error("unknown_field", f"Bảng không có cột '{field}'.", 404, "")
        try:
            return JSONResponse(field_values(source, chosen))
        except BiQueryError as failure:
            return error("bi_failed", str(failure), 400, "")

    @routes.post("/api/bi/{dataset}/query")
    async def api_bi_query(request: Request, dataset: str) -> Response:
        """Một cấu hình kéo thả thành một kết quả sẵn để vẽ."""
        found = source_of(request, dataset)
        if isinstance(found, Response):
            return found
        source, schema = found
        try:
            query = BiQuery.model_validate(await request.json())
        except ValueError as failure:
            return error("bad_query", "Cấu hình kéo thả không hợp lệ.", 400, str(failure)[:300])
        try:
            return JSONResponse(run_bi_query(source, query, list(schema.fields)))
        except BiQueryError as failure:
            return error("bi_failed", str(failure), 400, "")

    @routes.get("/api/bi/{dataset}/views")
    def api_bi_views(request: Request, dataset: str) -> Response:
        found = views_dir(request, dataset)
        if isinstance(found, Response):
            return found
        views = [view.model_dump() for view in list_views(found)]
        return JSONResponse({"dataset_id": dataset, "views": views})

    @routes.post("/api/bi/{dataset}/views")
    async def api_bi_save_view(request: Request, dataset: str) -> Response:
        """Tạo bản mới (không có `id`) hoặc ghi đè đúng bản có `id`."""
        found = views_dir(request, dataset)
        if isinstance(found, Response):
            return found
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("can mot object")
            state = ViewState.model_validate(body.get("state"))
        except ValueError as failure:
            return error("bad_view", "Bản phân tích không hợp lệ.", 400, str(failure)[:300])
        view_id = body.get("id") or None
        if view_id is not None and (
            not isinstance(view_id, str)
            or not SHORT_ID.fullmatch(view_id)
            or all(view.id != view_id for view in list_views(found))
        ):
            return error("unknown_view", "Không có bản phân tích này.", 404, "")
        try:
            saved = save_view(found, str(body.get("name") or ""), state, view_id=view_id)
        except ViewError as failure:
            return error("bad_view", str(failure), 400, "")
        return JSONResponse(saved.model_dump(), status_code=201 if view_id is None else 200)

    @routes.delete("/api/bi/{dataset}/views/{view_id}")
    def api_bi_delete_view(request: Request, dataset: str, view_id: str) -> Response:
        found = views_dir(request, dataset)
        if isinstance(found, Response):
            return found
        if not SHORT_ID.fullmatch(view_id) or not delete_view(found, view_id):
            return error("unknown_view", "Không có bản phân tích này.", 404, "")
        return JSONResponse({"deleted": view_id})

    return routes
