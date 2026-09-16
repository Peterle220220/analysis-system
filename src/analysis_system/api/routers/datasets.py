"""Một bộ dữ liệu: tải lên, xem, làm sạch, chú giải, duyệt, tải về, xoá.

Mỗi route ở đây chỉ nhận yêu cầu, gọi `Workspace`, rồi trả JSON. Việc ghi tệp vừa tải
lên, việc làm sạch chạy nền, và phép kiểm "bộ dữ liệu này có thật không" đều nằm ở tầng
application (plans/refactor-ddd.md, Phase 8).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response

from analysis_system.api.inputs import added_rules, dataset_name, too_large
from analysis_system.api.once import claim, finish, is_malformed, key_of, release
from analysis_system.api.replies import (
    dataset_missing,
    error,
    id_is_safe,
    invalid_id,
    json_body,
)
from analysis_system.api.session import Guard, requires_sign_in
from analysis_system.api.view import (
    clean_payload,
    dataset_payload,
    gate_report,
    glossary_payload,
    rows_payload,
    run_report,
    status_payload,
)
from analysis_system.application.workspace import ServiceError, Workspace
from analysis_system.core.job_error import read_error
from analysis_system.domains.data_ingestion.dataset_labels import display_label
from analysis_system.domains.data_ingestion.glossary_draft import duplicate_meanings


def router(space: Workspace, guard: Guard) -> APIRouter:
    """Các route của một bộ dữ liệu, gắn với một workspace."""
    routes = APIRouter()

    def refused(request: Request, dataset: str) -> Response | None:
        """Ba phép kiểm mở đầu của mọi route có tên bộ dữ liệu, hoặc None khi qua hết."""
        denied = requires_sign_in(guard, request)
        if denied is not None:
            return denied
        if not id_is_safe(dataset):
            return invalid_id(dataset)
        if not space.knows(dataset):
            return dataset_missing()
        return None

    @routes.post("/api/datasets")
    async def api_upload(
        request: Request,
        background: BackgroundTasks,
        tep: Annotated[UploadFile | None, File()] = None,
        ten: Annotated[str, Form()] = "",
        client_request_id: Annotated[str, Form()] = "",
        nguon: Annotated[str, Form()] = "",
    ) -> Response:
        denied = requires_sign_in(guard, request)
        if denied is not None:
            return denied
        if tep is None:
            return error("missing_file", "Hãy chọn một tệp.", 400)
        oversize = too_large(tep)
        if oversize:
            return error("file_too_large", oversize, 413)
        if is_malformed(client_request_id):
            return error("invalid_request_id", "Mã request không hợp lệ.", 400)
        artifacts = Path(space.settings.layers.artifacts)
        request_path, replay, in_progress = claim(artifacts, "upload", key_of(client_request_id))
        if replay is not None:
            return JSONResponse(replay, status_code=202)
        if in_progress:
            return error("request_in_progress", "Yêu cầu này đang được xử lý.", 409)
        name = dataset_name(ten, tep.filename or "")
        try:
            target = space.accept_upload(
                name,
                tep.filename or "",
                await tep.read(),
                origin=nguon,
                label=display_label(ten, tep.filename or ""),
            )
        except ServiceError as failure:
            release(request_path)
            return error("upload_failed", failure.message, 400, failure.hint)
        background.add_task(space.clean_quietly, target, name)
        payload = {"dataset_id": name, "status": "running", "running": True}
        finish(request_path, payload)
        return JSONResponse(payload, status_code=202)

    @routes.get("/api/datasets/{dataset}/status")
    def api_dataset_status(request: Request, dataset: str) -> Response:
        """Trang dang cho hoi lien tuc route nay, nen no khong duoc doi hoi da co thu muc."""
        denied = requires_sign_in(guard, request)
        if denied is not None:
            return denied
        if not id_is_safe(dataset):
            return invalid_id(dataset)
        try:
            payload = status_payload(space, dataset)
        except ServiceError as failure:
            return error("dataset_unreadable", failure.message, 404, failure.hint)
        return dataset_missing() if payload is None else JSONResponse(payload)

    @routes.get("/api/datasets/{dataset}")
    def api_dataset(request: Request, dataset: str) -> Response:
        stop = refused(request, dataset)
        if stop is not None:
            return stop
        try:
            payload = dataset_payload(space, dataset)
        except ServiceError as failure:
            return error("dataset_unreadable", failure.message, 404, failure.hint)
        failed = read_error(Path(space.settings.layers.runs) / dataset)
        if failed:
            payload["error"] = failed
        return JSONResponse(payload)

    @routes.get("/api/datasets/{dataset}/clean")
    def api_clean(request: Request, dataset: str) -> Response:
        stop = refused(request, dataset)
        if stop is not None:
            return stop
        try:
            return JSONResponse(clean_payload(space, dataset))
        except ServiceError as failure:
            return error("clean_unreadable", failure.message, 404, failure.hint)

    @routes.get("/api/datasets/{dataset}/rows")
    def api_rows(
        request: Request, dataset: str, which: str = "clean", offset: int = 0, limit: int = 200
    ) -> Response:
        """Một khối dòng của bảng, cho bảng cuộn ảo: chỉ xin phần đang cần xem."""
        stop = refused(request, dataset)
        if stop is not None:
            return stop
        # Chi hai bang co ten, anh xa ngay tai day: trinh duyet khong bao gio
        # gui duoc mot duong dan tep tuy y.
        if which not in ("clean", "staged"):
            return error("unknown_table", "Chỉ có bảng 'clean' hoặc 'staged'.", 400, "")
        try:
            table = space.clean_table(dataset) if which == "clean" else space.staged_table(dataset)
            if table is None:
                return error("table_missing", "Chưa có bảng này.", 404, "")
            return JSONResponse(rows_payload(space, table, offset, limit))
        except ServiceError as failure:
            return error("table_unreadable", failure.message, 404, failure.hint)
        except (OSError, ValueError) as failure:
            return error("table_unreadable", str(failure), 404, "")

    @routes.put("/api/datasets/{dataset}/context")
    async def api_set_context(request: Request, dataset: str) -> Response:
        stop = refused(request, dataset)
        if stop is not None:
            return stop
        body = await json_body(request)
        try:
            saved = space.set_context(dataset, str(body.get("context") or ""))
        except ServiceError as failure:
            return error("context_failed", failure.message, 400, failure.hint)
        return JSONResponse({"dataset_id": dataset, "context": saved})

    @routes.post("/api/datasets/{dataset}/glossary-draft")
    def api_draft_glossary(request: Request, dataset: str) -> Response:
        stop = refused(request, dataset)
        if stop is not None:
            return stop
        try:
            lines, dropped = space.draft_glossary(dataset)
        except ServiceError as failure:
            return error("glossary_failed", failure.message, 400, failure.hint)
        # MANG cac dong, dung kieu ban Next cho. Truoc day tra nguyen mot chuoi,
        # va trang Next vo o JavaScript roi bao chung chung "Khong soan duoc chu
        # giai" trong khi model da soan xong du 96 dong.
        return JSONResponse(
            {
                "dataset_id": dataset,
                "lines": lines.splitlines(),
                "dropped": dropped,
                "conflicts": duplicate_meanings(lines),
            }
        )

    @routes.get("/api/datasets/{dataset}/glossary")
    def api_glossary(request: Request, dataset: str) -> Response:
        stop = refused(request, dataset)
        if stop is not None:
            return stop
        # Ban da luu, doc lai moi lan mo trang. Truoc day trang Next khong doc
        # lai no: quay lai chi con nut soan nhap, va soan lai la noi vao ban cu.
        try:
            rows = space.glossary_table(dataset)
        except ServiceError as failure:
            return error("glossary_unreadable", failure.message, 404, failure.hint)
        return JSONResponse(glossary_payload(dataset, rows))

    @routes.put("/api/datasets/{dataset}/glossary")
    async def api_set_glossary(request: Request, dataset: str) -> Response:
        stop = refused(request, dataset)
        if stop is not None:
            return stop
        body = await json_body(request)
        raw = body.get("rows")
        if not isinstance(raw, list):
            return error("invalid_glossary", "Bảng chú giải không hợp lệ.", 400)
        rows = [
            (str(item.get("column") or ""), str(item.get("meaning") or ""))
            for item in raw
            if isinstance(item, dict)
        ]
        # Chi dong cua cot phan loai mang o Nhan gia tri. Khong dong nao mang no
        # thi nhan da khai giu nguyen.
        values = {
            str(item.get("column") or ""): str(item.get("values") or "")
            for item in raw
            if isinstance(item, dict) and "values" in item
        }
        try:
            saved, moved = space.set_glossary(dataset, rows, values or None)
        except ServiceError as failure:
            return error("glossary_failed", failure.message, 400, failure.hint)
        payload = glossary_payload(dataset, space.glossary_table(dataset))
        return JSONResponse({**payload, "moved": moved, "conflicts": duplicate_meanings(saved)})

    @routes.post("/api/datasets/{dataset}/approve")
    async def api_approve(request: Request, dataset: str) -> Response:
        stop = refused(request, dataset)
        if stop is not None:
            return stop
        body = await json_body(request)
        gate_id = str(body.get("gate_id") or "")
        chosen = body.get("chosen") or body.get("approved") or []
        if not isinstance(chosen, list):
            return error("invalid_approval", "Danh sách lựa chọn không hợp lệ.", 400)
        raw_added = body.get("added_rules") or body.get("added") or ""
        if isinstance(raw_added, str):
            extra = added_rules(raw_added)
        elif isinstance(raw_added, list):
            extra = tuple(item for item in raw_added if isinstance(item, dict))
        else:
            return error("invalid_approval", "Quy tắc thêm không hợp lệ.", 400)
        raw_key = body.get("client_request_id") or body.get("request_id") or ""
        if is_malformed(raw_key):
            return error("invalid_request_id", "Mã request không hợp lệ.", 400)
        artifacts = Path(space.settings.layers.artifacts)
        request_path, replay, in_progress = claim(
            artifacts, "approve_dataset_" + dataset, key_of(raw_key)
        )
        if replay is not None:
            return JSONResponse(replay)
        if in_progress:
            return error("request_in_progress", "Yêu cầu này đang được xử lý.", 409)
        try:
            space.approve(dataset, gate_id, tuple(str(item) for item in chosen), added=extra)
            report = space.resume(dataset)
        except ServiceError as failure:
            release(request_path)
            return error("approval_failed", failure.message, 400, failure.hint)
        payload = {
            "dataset_id": dataset,
            "run": run_report(report),
            "gates": [gate_report(gate) for gate in space.gates(dataset)],
        }
        finish(request_path, payload)
        return JSONResponse(payload)

    @routes.get("/api/datasets/{dataset}/clean.csv")
    def api_download_clean(request: Request, dataset: str) -> Response:
        denied = requires_sign_in(guard, request)
        if denied is not None:
            return denied
        if not id_is_safe(dataset):
            return invalid_id(dataset)
        try:
            table = space.clean_table(dataset)
        except (OSError, ServiceError):
            table = None
        if table is None:
            return error("clean_not_found", "Chưa có bảng sạch để tải.", 404)
        frame = space.table(table.uri)
        return Response(
            frame.to_csv(index=False).encode("utf-8-sig"),
            media_type="text/csv",
            headers={"content-disposition": f'attachment; filename="{dataset}_sach.csv"'},
        )

    @routes.delete("/api/datasets/{dataset}")
    def api_forget_dataset(request: Request, dataset: str) -> Response:
        """Xoá hẳn một bộ dữ liệu, để người dùng tự bỏ được tệp hỏng."""
        stop = refused(request, dataset)
        if stop is not None:
            return stop
        busy = space.dataset_busy(dataset)
        if busy or space.still_starting(dataset):
            return error(
                "dataset_running",
                "Bộ dữ liệu này đang được xử lý. Đợi xong rồi xoá.",
                409,
                ", ".join(busy),
            )
        try:
            removed = space.forget_dataset(dataset)
        except ServiceError as failure:
            return error("delete_failed", failure.message, 400, failure.hint)
        return JSONResponse({"dataset_id": dataset, "removed": removed})

    return routes
