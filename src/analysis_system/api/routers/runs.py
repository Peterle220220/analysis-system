"""Lượt hỏi trên một bộ dữ liệu: hỏi, xem, duyệt, tải về, xoá.

Câu hỏi tiếp mang theo kết luận nó đào sâu; phép ghép đó nằm ở tầng application, vì đó
là cách hệ thống hỏi chứ không phải cách trình bày (plans/refactor-ddd.md, Phase 8).
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from analysis_system.api.inputs import added_rules
from analysis_system.api.once import claim, finish, is_malformed, key_of, release
from analysis_system.api.replies import (
    dataset_missing,
    error,
    id_is_safe,
    invalid_id,
    json_body,
)
from analysis_system.api.session import Guard, requires_sign_in
from analysis_system.api.tree import write_lineage
from analysis_system.api.view import (
    display_words,
    round_payload,
    round_state,
    round_status_payload,
)
from analysis_system.api.view import (
    round_runs as payload_round_runs,
)
from analysis_system.application.workspace import ServiceError, Workspace, question_with_claim
from analysis_system.domains.execution_engine.group_means import with_group_means
from analysis_system.domains.visualization.export_answer import to_excel, to_word

# Cau tra loi con phai di tiep: dan vao mot ban trinh bay, gui cho nguoi khong co tai
# khoan, mo lai sau sau thang. Chup man hinh thi mat moi thu nam sau con so.
FORMATS: Final[dict[str, tuple[str, str]]] = {
    "excel": ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "word": ("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
}


def router(space: Workspace, guard: Guard) -> APIRouter:
    """Các route của lượt hỏi, gắn với một workspace."""
    routes = APIRouter()

    def refused(request: Request, dataset: str) -> Response | None:
        denied = requires_sign_in(guard, request)
        if denied is not None:
            return denied
        if not id_is_safe(dataset):
            return invalid_id(dataset)
        if not space.knows(dataset):
            return dataset_missing()
        return None

    def refused_round(request: Request, dataset: str, run_id: str) -> Response | None:
        denied = requires_sign_in(guard, request)
        if denied is not None:
            return denied
        if not id_is_safe(dataset) or not id_is_safe(run_id):
            return invalid_id(run_id if not id_is_safe(run_id) else dataset)
        return None

    @routes.post("/api/datasets/{dataset}/ask")
    async def api_ask(request: Request, dataset: str) -> Response:
        stop = refused(request, dataset)
        if stop is not None:
            return stop
        body = await json_body(request)
        raw_key = body.get("client_request_id") or body.get("request_id") or ""
        if is_malformed(raw_key):
            return error("invalid_request_id", "Mã request không hợp lệ.", 400)
        artifacts = Path(space.settings.layers.artifacts)
        request_path, replay, in_progress = claim(artifacts, f"ask_{dataset}", key_of(raw_key))
        if replay is not None:
            return JSONResponse(replay, status_code=202)
        if in_progress:
            return error("request_in_progress", "Yêu cầu này đang được xử lý.", 409)
        question = str(body.get("question") or "").strip()
        parent = str(body.get("from") or "").strip()
        claimed = str(body.get("claim") or "").strip()
        if not question:
            release(request_path)
            return error("empty_question", "Hãy nhập một câu hỏi.", 400)
        try:
            report = space.ask(dataset, question_with_claim(question, claimed))
            if parent:
                write_lineage(
                    Path(space.settings.layers.runs) / report.round_id,
                    parent=parent,
                    claim=claimed,
                )
        except ServiceError as failure:
            release(request_path)
            return error("ask_failed", failure.message, 400, failure.hint)
        payload = {
            "dataset_id": dataset,
            "round_id": report.round_id,
            "question": report.question,
            "state": round_state(space, report.round_id),
            "running": space.running(report.round_id),
        }
        finish(request_path, payload)
        return JSONResponse(payload, status_code=202)

    @routes.get("/api/datasets/{dataset}/rounds/{run_id}")
    def api_round(request: Request, dataset: str, run_id: str) -> Response:
        stop = refused_round(request, dataset, run_id)
        if stop is not None:
            return stop
        try:
            return JSONResponse(round_payload(space, dataset, run_id))
        except ServiceError as failure:
            return error("round_not_found", failure.message, 404, failure.hint)

    @routes.get("/api/datasets/{dataset}/rounds/{run_id}/status")
    def api_round_status(request: Request, dataset: str, run_id: str) -> Response:
        stop = refused_round(request, dataset, run_id)
        if stop is not None:
            return stop
        try:
            return JSONResponse(round_status_payload(space, dataset, run_id))
        except ServiceError as failure:
            return error("round_not_found", failure.message, 404, failure.hint)

    @routes.post("/api/datasets/{dataset}/rounds/{run_id}/approve")
    async def api_approve_round(request: Request, dataset: str, run_id: str) -> Response:
        stop = refused_round(request, dataset, run_id)
        if stop is not None:
            return stop
        try:
            round_payload(space, dataset, run_id)
        except ServiceError as failure:
            return error("round_not_found", failure.message, 404, failure.hint)
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
            artifacts, f"approve_round_{dataset}_{run_id}", key_of(raw_key)
        )
        if replay is not None:
            return JSONResponse(replay)
        if in_progress:
            return error("request_in_progress", "Yêu cầu này đang được xử lý.", 409)
        try:
            space.approve(run_id, gate_id, tuple(str(item) for item in chosen), added=extra)
            space.resume(run_id)
        except ServiceError as failure:
            release(request_path)
            return error("approval_failed", failure.message, 400, failure.hint)
        payload = round_payload(space, dataset, run_id)
        finish(request_path, payload)
        return JSONResponse(payload)

    @routes.get("/api/datasets/{dataset}/rounds/{run_id}/export/{kind}")
    def api_export_answer(request: Request, dataset: str, run_id: str, kind: str) -> Response:
        stop = refused_round(request, dataset, run_id)
        if stop is not None:
            return stop
        chosen = FORMATS.get(kind)
        round_ids = {item.run_id for item in payload_round_runs(space, dataset)}
        if chosen is None or run_id not in round_ids:
            return error("export_not_found", "Không có định dạng hoặc phân tích này.", 404)
        found = space.answer(run_id)
        if found is None:
            return error("answer_not_found", "Phân tích chưa có câu trả lời.", 404)
        suffix, media = chosen
        labels, names, aliases = display_words(space, dataset)
        found = with_group_means(found, space.measured(run_id), labels, names)
        body = to_excel(found, aliases) if kind == "excel" else to_word(found, aliases)
        return Response(
            body,
            media_type=media,
            headers={"content-disposition": f'attachment; filename="{run_id}.{suffix}"'},
        )

    @routes.post("/api/datasets/{dataset}/rounds/delete")
    async def api_forget_rounds(request: Request, dataset: str) -> Response:
        stop = refused(request, dataset)
        if stop is not None:
            return stop
        body = await json_body(request)
        selected = body.get("round_ids") or body.get("rounds") or []
        if not isinstance(selected, list):
            return error("invalid_rounds", "Danh sách phân tích không hợp lệ.", 400)
        chosen = [str(item) for item in selected if str(item).strip()]
        busy = [item for item in chosen if space.running(item)]
        if busy:
            return error(
                "round_running",
                "Có phân tích đang chạy trong số bạn chọn.",
                409,
                ", ".join(busy),
            )
        try:
            deleted = space.forget_rounds(dataset, chosen)
        except ServiceError as failure:
            return error("delete_failed", failure.message, 400, failure.hint)
        return JSONResponse({"dataset_id": dataset, "deleted": deleted})

    @routes.get("/api/charts/{name:path}")
    def api_chart(request: Request, name: str) -> Response:
        denied = requires_sign_in(guard, request)
        if denied is not None:
            return denied
        wanted = Path(space.settings.layers.artifacts) / Path(name).name
        if wanted.suffix != ".png" or not wanted.is_file():
            return error("chart_not_found", "Không có biểu đồ này.", 404)
        return Response(wanted.read_bytes(), media_type="image/png")

    return routes
