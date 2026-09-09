"""Người trình bày thứ ba: gọi Workspace rồi trả JSON thuần.

Dòng lệnh là người trình bày thứ nhất, `render.py` là người thứ hai, và file này
là người thứ ba — cái mà một giao diện Next.js sẽ gọi thay vì gọi thẳng
`Workspace`. Mọi thứ ở đây chỉ chuyển dữ liệu thành dict, **không quyết định**
luật nào: câu nào được duyệt, lượt nào đang chạy, kết luận nào bị chặn — tất cả
đều do tầng dưới nói, và nơi nào render.py cũng phải nói thì cả hai cùng gọi một
hàm dưới đây, để một luật có một nguồn.

Quy tắc tách (đã ghi trong plans/nextjs-migration.md §2.2): một `if` nói về *dữ
liệu* (đang chạy/chưa/đã xong, có kết quả hay không, claim bị chặn hay không)
thì thành một flag trong JSON; render.py vẽ HTML bằng cùng flag, React vẽ bằng
cùng flag. Không có hai luật.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from analysis_system.api import (
    CleanReport,
    GateReport,
    RunReport,
    ServiceError,
    TableReport,
    Workspace,
)
from analysis_system.contracts.agents import ManagerAnswer
from analysis_system.services import retention
from analysis_system.services.retention import RunInfo
from analysis_system.services.updater import Update, Version
from analysis_system.web.naming import ROUND_MARK
from analysis_system.web.tree import Node, build_tree, read_lineage


def datestamp(value: datetime) -> str:
    """Một thời điểm, dưới dạng JSON an toàn (ISO 8601)."""
    return value.astimezone(UTC).isoformat()


# --- phiên -------------------------------------------------------------------


def session_payload(signed_in: bool) -> dict[str, Any]:
    """Hình dạng trả về của GET /api/session.

    Giữ nguyên ngữ nghĩa của `Guard`: đăng nhập nội bộ là một cờ `signed_in`.
    Không có hồ sơ người dùng — một dashboard, một mật khẩu.
    """
    return {"signed_in": signed_in}


# --- RunInfo và các dataclass báo cáo ----------------------------------------


def run_info(run: RunInfo) -> dict[str, Any]:
    """Một bộ dữ liệu / một lượt chạy, dưới dạng JSON cho bảng, cây và trang Home."""
    return {
        "run_id": run.run_id,
        "started": datestamp(run.started),
        "phase": run.phase,
        "tasks": run.tasks,
        "files": run.files,
        "bytes_used": run.bytes_used,
        "age_days": run.age_days,
    }


def run_report(report: RunReport) -> dict[str, Any]:
    """Kết quả của một lần chạy, gói gọn trong JSON cho giao diện."""
    return {
        "run_id": report.run_id,
        "status": report.status,
        "is_complete": report.is_complete,
        "pending_gate": report.pending_gate,
        "escalation": report.escalation,
        "can_replan": report.can_replan,
        "tasks": [
            {
                "task_id": task.task_id,
                "agent_id": task.agent_id,
                "status": task.status,
                "message": task.message,
            }
            for task in report.tasks
        ],
        "declined": [
            {"agent_id": declined.agent_id, "note": declined.note} for declined in report.declined
        ],
        "spend": (
            {
                "tokens": report.spend.tokens,
                "cost_usd": report.spend.cost_usd,
                "warnings": list(report.spend.warnings),
            }
            if report.spend is not None
            else None
        ),
    }


def table_report(table: TableReport) -> dict[str, Any]:
    """Một bảng đã mô tả: nguồn gốc, số dòng, tên cột."""
    return {
        "uri": table.uri,
        "rows": table.rows,
        "columns": list(table.columns),
    }


def gate_report(gate: GateReport) -> dict[str, Any]:
    """Một câu hỏi còn nợ câu trả lời, cho giao diện vẽ phiếu duyệt."""
    return {
        "gate_id": gate.gate_id,
        "task_id": gate.task_id,
        "agent_id": gate.agent_id,
        "title": gate.title,
        "question": gate.question,
        "options": [
            {
                "option_id": option.option_id,
                "label": option.label,
                "detail": option.detail,
            }
            for option in gate.options
        ],
        "examined": list(gate.examined),
    }


def manager_answer(answer: ManagerAnswer) -> dict[str, Any]:
    """Câu trả lời của Manager, vốn là một BaseModel — serialize thuần JSON."""
    # ManagerAnswer đã là Pydantic; model_dump(mode="json") biến datetime/Decimal
    # thành thứ JSON nói được. Một nơi duy nhất, ai cần cũng đi qua đây.
    return answer.model_dump(mode="json")


def clean_report(report: CleanReport) -> dict[str, Any]:
    """Kết quả một lần làm sạch: lần chạy và bảng sạch nó để lại (nếu có)."""
    return {
        "run": run_report(report.run),
        "table": table_report(report.table) if report.table is not None else None,
    }


def root_runs(space: Workspace) -> list[RunInfo]:
    """Mọi bộ dữ liệu gốc (bỏ các lượt hỏi), theo thứ tự retention trả về."""
    return [run for run in retention.runs(space.settings) if ROUND_MARK not in run.run_id]


def round_runs(space: Workspace, dataset: str) -> list[RunInfo]:
    """Mọi lượt hỏi (phân tích) thuộc một bộ dữ liệu, cũ trước."""
    return [
        run for run in retention.runs(space.settings) if run.run_id.startswith(dataset + ROUND_MARK)
    ]


def _round_number(run_id: str) -> tuple[int, str]:
    """Số thứ tự của lượt hỏi, để xếp cũ trước (số so bằng số, không bằng chữ)."""
    _, mark, tail = run_id.partition(ROUND_MARK)
    if mark and tail.isdigit():
        return (int(tail), "")
    return (10**9, run_id)


def _has_result(space: Workspace, run_id: str) -> bool:
    """Lượt này có ra được cái gì để đọc không — câu trả lời, hoặc một gate đang chờ."""
    try:
        if space.gates(run_id):
            return True
    except ServiceError:
        pass
    try:
        return space.answer(run_id) is not None
    except ServiceError:
        return False


def split_rounds(
    space: Workspace, rounds: list[tuple[str, str]]
) -> dict[str, list[dict[str, str]]]:
    """Chia lượt hỏi thành ba nhóm và trả JSON.

    Đây là nguồn duy nhất của phép chia "đã ra kết quả / đang chạy / chưa xong".
    render.py có hàm cùng tên và cùng logic; nếu một bên đổi thì hai cây vẽ ra
    từ hai bên lệch nhau. Khi chuyển xong sang Next, render.py sẽ ngừng gọi bản
    HTML riêng và đi qua đây.
    """
    oldest_first = sorted(rounds, key=lambda item: _round_number(item[0]))
    groups: dict[str, list[dict[str, str]]] = {"done": [], "running": [], "broken": []}
    for run_id, question in oldest_first:
        if _has_result(space, run_id):
            groups["done"].append({"run_id": run_id, "question": question})
        elif _running_or_pending(space, run_id):
            groups["running"].append({"run_id": run_id, "question": question})
        else:
            groups["broken"].append({"run_id": run_id, "question": question})
    return groups


def _running_or_pending(space: Workspace, run_id: str) -> bool:
    try:
        if space.gates(run_id):
            return True
    except ServiceError:
        pass
    try:
        return space.running(run_id)
    except ServiceError:
        return False


def _pending_count(space: Workspace, run_id: str) -> int:
    """Còn bao nhiêu việc đang chờ duyệt, hoặc 0 nếu không đọc được."""
    try:
        return len(space.gates(run_id))
    except ServiceError:
        return 0


def dataset_state(space: Workspace, run_id: str) -> dict[str, Any]:
    """Bộ dữ liệu này đang ở đâu, thành một bộ cờ JSON.

    render.py vẽ HTML từ các chuỗi tiếng Việt; React vẽ từ các cờ này. Cùng một
    quyết định: đang chạy / chờ duyệt / đã dừng / sẵn sàng / chưa làm sạch.
    """
    try:
        if space.running(run_id):
            return {"key": "running", "label": "đang làm sạch"}
        gates = space.gates(run_id)
        if gates:
            return {"key": "waiting", "label": "chờ bạn duyệt"}
        stopped = space.why_stopped(run_id)
        if stopped:
            return {"key": "stopped", "label": "đã dừng — xem chi tiết"}
        if space.clean_table(run_id):
            return {"key": "ready", "label": "sẵn sàng để hỏi"}
        return {"key": "unclean", "label": "chưa làm sạch"}
    except ServiceError:
        return {"key": "unreadable", "label": "không đọc được"}


def round_state(space: Workspace, run_id: str) -> dict[str, Any]:
    """Một dòng nói lượt hỏi này đang ở đâu — kể cả khi nó hỏng."""
    if _pending_count(space, run_id):
        return {"key": "waiting", "label": "Đang chờ bạn duyệt."}
    answer = space.answer(run_id)
    if answer is not None:
        return {"key": "answered", "label": f"{len(answer.claims)} kết luận."}
    reason = _why_no_answer(space, run_id)
    return {"key": "unanswered", "label": reason}


def _why_no_answer(space: Workspace, run_id: str) -> str:
    """Vì sao lượt này không có câu trả lời."""
    try:
        reason = space.why_stopped(run_id)
    except ServiceError:
        return "Chưa có câu trả lời."
    return reason


# --- cây việc ----------------------------------------------------------------


def tree(space: Workspace, dataset: str, rounds: list[tuple[str, str]]) -> dict[str, Any]:
    """Cây việc của một bộ dữ liệu, thành JSON để React vẽ nguyên cây."""
    runs_root = Path(space.settings.layers.runs)
    lineage = {run_id: read_lineage(runs_root / run_id) for run_id, _ in rounds}
    return _node_dict(build_tree(dataset, rounds, lineage))


def _node_dict(node: Node) -> dict[str, Any]:
    return {
        "run_id": node.run_id,
        "label": node.label,
        "href": node.href,
        "number": node.number,
        "children": [_node_dict(child) for child in node.children],
    }


# --- bốn trang chính ---------------------------------------------------------


def home(space: Workspace) -> dict[str, Any]:
    """Dữ liệu cho trang `/`: bộ dữ liệu gốc và có bao nhiêu bộ đang chờ duyệt."""
    runs = root_runs(space)
    waiting = sum(1 for run in runs if _pending_count(space, run.run_id))
    return {
        "runs": [run_info(run) for run in runs],
        "count": len(runs),
        "waiting": waiting,
    }


def data_page(space: Workspace) -> dict[str, Any]:
    """Dữ liệu cho trang `/du-lieu`: từng bộ với trạng thái và số phân tích."""
    runs = root_runs(space)
    return {
        "datasets": [
            {
                **run_info(run),
                "state": dataset_state(space, run.run_id),
                "analyses": len(round_runs(space, run.run_id)),
            }
            for run in runs
        ]
    }


def dashboard(space: Workspace) -> dict[str, Any]:
    """Dữ liệu cho trang `/bang-dieu-khien`: nguyên liệu sẵn để ghép báo cáo."""
    ready: list[dict[str, Any]] = []
    for run in root_runs(space):
        rounds = [other.run_id for other in round_runs(space, run.run_id)]
        answered = sum(1 for round_id in rounds if space.answer(round_id) is not None)
        if answered:
            ready.append({"dataset": run.run_id, "answers": answered})
    return {"material": ready}


def system(version: Version, update: Update, note: str = "") -> dict[str, Any]:
    """Dữ liệu cho trang `/he-thong`: bản đang chạy và tình trạng cập nhật."""
    return {
        "ok": bool(version.sha),
        "note": note,
        "version": {
            "sha": version.sha,
            "subject": version.subject,
            "when": version.when,
            "branch": version.branch,
            "dirty": version.dirty,
        },
        "update": {
            "behind": update.behind,
            "available": update.available,
            "problem": update.problem,
            "commits": list(update.commits),
        },
    }


# --- dataset/round payloads --------------------------------------------------


def question_of(space: Workspace, run_id: str) -> str:
    """Read the user question from the round plan, if one exists."""
    path = Path(space.settings.layers.runs) / run_id / "plan.json"
    if not path.is_file():
        return ""
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    for task in plan.get("tasks", []):
        question = (task.get("params") or {}).get("question")
        if question:
            return str(question)
    return ""


def dataset_rounds(space: Workspace, dataset: str) -> list[dict[str, Any]]:
    """All rounds for a dataset, with one shared state decision each."""
    rounds = round_runs(space, dataset)
    pairs = [(run.run_id, question_of(space, run.run_id)) for run in rounds]
    groups = split_rounds(space, pairs)
    states = {item["run_id"]: "done" for item in groups["done"]} | {
        item["run_id"]: "running" for item in groups["running"]
    }
    states.update({item["run_id"]: "broken" for item in groups["broken"]})
    return [
        {
            "run": run_info(run),
            "question": question,
            "state": states.get(run.run_id, "broken"),
            "detail": round_state(space, run.run_id),
        }
        for run, (_, question) in zip(rounds, pairs, strict=True)
    ]


def dataset_payload(space: Workspace, dataset: str) -> dict[str, Any]:
    """Dataset page data: source, clean output, gates, context and round tree."""
    rounds = round_runs(space, dataset)
    pairs = [(run.run_id, question_of(space, run.run_id)) for run in rounds]
    staged = space.staged_table(dataset)
    clean = space.clean_table(dataset)
    gates = [gate_report(gate) for gate in space.gates(dataset)]
    return {
        "dataset_id": dataset,
        "context": space.context(dataset),
        "state": dataset_state(space, dataset),
        "staged": table_report(staged) if staged is not None else None,
        "clean": table_report(clean) if clean is not None else None,
        "examination": list(space.examination(dataset)),
        "gates": gates,
        "rounds": dataset_rounds(space, dataset),
        "tree": tree(space, dataset, pairs),
    }


def clean_payload(space: Workspace, dataset: str) -> dict[str, Any]:
    """Data for the dedicated clean-table page."""
    table = space.clean_table(dataset)
    return {
        "dataset_id": dataset,
        "state": dataset_state(space, dataset),
        "table": table_report(table) if table is not None else None,
        "examination": list(space.examination(dataset)),
        "gates": [gate_report(gate) for gate in space.gates(dataset)],
        "tree": tree(
            space,
            dataset,
            [(run.run_id, question_of(space, run.run_id)) for run in round_runs(space, dataset)],
        ),
    }


def round_payload(space: Workspace, dataset: str, run_id: str) -> dict[str, Any]:
    """One analysis round, including the answer exactly as Python produced it."""
    rounds = round_runs(space, dataset)
    questions = {run.run_id: question_of(space, run.run_id) for run in rounds}
    if run_id not in questions:
        raise ServiceError("Không có phân tích này.")
    answer = space.answer(run_id)
    return {
        "dataset_id": dataset,
        "round_id": run_id,
        "question": questions[run_id],
        "state": round_state(space, run_id),
        "running": space.running(run_id),
        "stopped_reason": _why_no_answer(space, run_id),
        "gates": [gate_report(gate) for gate in space.gates(run_id)],
        "answer": manager_answer(answer) if answer is not None else None,
        "measured": space.measured(run_id),
        "tree": tree(space, dataset, [(run.run_id, questions[run.run_id]) for run in rounds]),
    }
