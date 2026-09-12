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
from collections.abc import Mapping
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
from analysis_system.services.asked_columns import unmatched_lines
from analysis_system.services.column_names import would_change
from analysis_system.services.direct_answer import why_no_summary
from analysis_system.services.display_names import column_aliases, localize
from analysis_system.services.findings import was_repaired
from analysis_system.services.punctuation import plain_dashes
from analysis_system.services.retention import RunInfo
from analysis_system.services.svg_chart import chart_for, chart_keys, chart_title, pairs_from
from analysis_system.services.updater import Update, Version
from analysis_system.services.value_labels import display_name
from analysis_system.web.naming import ROUND_MARK
from analysis_system.web.state import (
    blocked_groups,
    dataset_status,
    forecast_values,
    gap_groups,
    pending_count,
    round_has_result,
    round_is_active,
    round_status,
)
from analysis_system.web.state import (
    split_rounds as shared_split_rounds,
)
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


def table_payload(space: Workspace, table: TableReport, limit: int = 20) -> dict[str, Any]:
    """A table report plus a bounded preview for the browser."""
    payload = table_report(table)
    try:
        preview = json.loads(
            space.table(table.uri, limit=limit).to_json(orient="records", date_format="iso")
        )
    except (OSError, ServiceError, TypeError, ValueError):
        preview = []
    payload["preview"] = preview
    return payload


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


def manager_answer(
    answer: ManagerAnswer, aliases: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """Câu trả lời của Manager, vốn là một BaseModel — serialize thuần JSON.

    `aliases`: tên tiếng Việt của các cột (từ bảng chú giải). Chỉ CHỮ hiển thị
    được đổi sang tên đó; metric key giữ tên gốc để lần ngược về con số.
    """
    # ManagerAnswer đã là Pydantic; model_dump(mode="json") biến datetime/Decimal
    # thành thứ JSON nói được. Một nơi duy nhất, ai cần cũng đi qua đây.
    payload = answer.model_dump(mode="json")
    names = aliases or {}
    # Chu do model viet: bo dau gach ngang dai, doi ten cot goc sang ten tieng
    # Viet truoc khi hien.
    if payload.get("summary"):
        payload["summary"] = localize(plain_dashes(payload["summary"]), names)
    for claim in payload.get("claims", []):
        if isinstance(claim, dict) and claim.get("claim"):
            claim["claim"] = localize(plain_dashes(claim["claim"]), names)
    payload["warnings"] = [localize(str(line), names) for line in answer.warnings]
    unanswered = tuple(localize(str(line), names) for line in answer.unanswered)
    payload["unanswered"] = list(unanswered)
    rejected = [localize(str(line), names) for line in answer.rejected]
    payload["blocked"] = [line for line in rejected if not was_repaired(line)]
    payload["repaired"] = [line for line in rejected if was_repaired(line)]
    # Ban Next viet moi, khong dung chung dong nao voi render.py. Moi cach noi
    # lai bang tieng nguoi ma trang Python co thi phai di qua day - neu khong,
    # ban Next in thang cau may cho nguoi dung doc.
    summary = str(answer.summary or "").strip()
    payload["direct_reason"] = "" if summary else why_no_summary(rejected)
    payload["blocked_groups"] = blocked_groups(payload["blocked"])
    payload["gap_groups"] = gap_groups(unanswered)
    return payload


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


def _has_result(space: Workspace, run_id: str) -> bool:
    """Lượt này có ra được cái gì để đọc không — câu trả lời, hoặc một gate đang chờ."""
    return round_has_result(space, run_id)


def split_rounds(
    space: Workspace, rounds: list[tuple[str, str]]
) -> dict[str, list[dict[str, str]]]:
    """Chia lượt hỏi thành ba nhóm và trả JSON.

    Đây là nguồn duy nhất của phép chia "đã ra kết quả / đang chạy / chưa xong".
    render.py có hàm cùng tên và cùng logic; nếu một bên đổi thì hai cây vẽ ra
    từ hai bên lệch nhau. Khi chuyển xong sang Next, render.py sẽ ngừng gọi bản
    HTML riêng và đi qua đây.
    """
    done, running, broken = shared_split_rounds(space, rounds)
    groups: dict[str, list[dict[str, str]]] = {"done": [], "running": [], "broken": []}
    groups["done"] = [{"run_id": run_id, "question": question} for run_id, question in done]
    groups["running"] = [{"run_id": run_id, "question": question} for run_id, question in running]
    groups["broken"] = [{"run_id": run_id, "question": question} for run_id, question in broken]
    return groups


def _running_or_pending(space: Workspace, run_id: str) -> bool:
    return round_is_active(space, run_id)


def _pending_count(space: Workspace, run_id: str) -> int:
    """Còn bao nhiêu việc đang chờ duyệt, hoặc 0 nếu không đọc được."""
    return pending_count(space, run_id)


def dataset_state(space: Workspace, run_id: str) -> dict[str, Any]:
    """Bộ dữ liệu này đang ở đâu, thành một bộ cờ JSON.

    render.py vẽ HTML từ các chuỗi tiếng Việt; React vẽ từ các cờ này. Cùng một
    quyết định: đang chạy / chờ duyệt / đã dừng / sẵn sàng / chưa làm sạch.
    """
    status = dataset_status(space, run_id)
    return {"key": status.key, "label": status.label}


def round_state(space: Workspace, run_id: str) -> dict[str, Any]:
    """Một dòng nói lượt hỏi này đang ở đâu — kể cả khi nó hỏng."""
    status = round_status(space, run_id)
    return {"key": status.key, "label": status.label}


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


def system(version: Version, update: Update, note: str = "", stale: str = "") -> dict[str, Any]:
    """Dữ liệu cho trang `/he-thong`: bản đang chạy và tình trạng cập nhật.

    `stale` là câu nói code trên đĩa đã mới hơn code đang chạy. Không có nó thì
    trang này nói "đang chạy bản mới nhất" trong khi tiến trình vẫn nạp bản cũ
    — và chủ hệ thống đã mất một buổi vì đúng câu đó.
    """
    return {
        "ok": bool(version.sha),
        "note": note,
        "stale": stale,
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
    state = dataset_state(space, dataset)
    return {
        "dataset_id": dataset,
        "context": space.context(dataset),
        "state": state,
        "staged": table_payload(space, staged) if staged is not None else None,
        "clean": table_payload(space, clean) if clean is not None else None,
        "examination": list(space.examination(dataset)),
        "stale_columns": _stale_columns(clean or staged),
        "glossary_unmatched": _glossary_unmatched(space.context(dataset), clean or staged),
        "gates": gates,
        "actions": {
            "can_ask": state["key"] == "ready",
            "can_download_clean": clean is not None,
            "can_approve": bool(gates),
        },
        "rounds": dataset_rounds(space, dataset),
        "tree": tree(space, dataset, pairs),
    }


def _glossary_unmatched(context: str, table: TableReport | None) -> list[str]:
    """Những dòng chú giải không trỏ tới cột nào — để trang nói ra, không im lặng."""
    return [] if table is None else unmatched_lines(context, list(table.columns))


def _stale_columns(table: TableReport | None) -> int:
    """Bao nhiêu tên cột mà bản hôm nay đã biết dọn.

    Bản sửa cách đọc tên cột **không quay lại sửa những bảng đã nằm trên đĩa**.
    Một bảng 96 cột làm sạch từ trước giữ nguyên 95 cái tên có dấu cách thừa ở
    đầu, rồi câu hỏi không khớp được cột — và không có gì nối hai chuyện đó lại.
    """
    return 0 if table is None else len(would_change(list(table.columns)))


def clean_payload(space: Workspace, dataset: str) -> dict[str, Any]:
    """Data for the dedicated clean-table page."""
    table = space.clean_table(dataset)
    gates = [gate_report(gate) for gate in space.gates(dataset)]
    return {
        "dataset_id": dataset,
        "context": space.context(dataset),
        "state": dataset_state(space, dataset),
        "table": table_payload(space, table) if table is not None else None,
        "examination": list(space.examination(dataset)),
        "stale_columns": _stale_columns(table),
        "gates": gates,
        "actions": {
            "can_download_clean": table is not None,
            "can_generate_glossary": table is not None,
        },
        "tree": tree(
            space,
            dataset,
            [(run.run_id, question_of(space, run.run_id)) for run in round_runs(space, dataset)],
        ),
    }


def round_status_payload(space: Workspace, dataset: str, run_id: str) -> dict[str, Any]:
    """Small status response for polling without reloading answer artifacts."""
    rounds = round_runs(space, dataset)
    if run_id not in {run.run_id for run in rounds}:
        raise ServiceError("Không có phân tích này.")
    return {
        "dataset_id": dataset,
        "round_id": run_id,
        "state": round_state(space, run_id),
        "running": space.running(run_id),
        "gates": [gate_report(gate) for gate in space.gates(run_id)],
    }


def _display_words(
    space: Workspace, dataset: str
) -> tuple[dict[str, dict[str, str]], dict[str, str], dict[str, str]]:
    """Nhãn giá trị, tên cột cho nhãn biểu đồ, và tên cột cho chữ, từ bảng chú giải.

    Đọc lỗi thì hiển thị bằng tên gốc: một trang còn đọc được tốt hơn một trang
    hỏng vì thiếu bản dịch.
    """
    try:
        rows = space.glossary_rows(dataset)
        labels = space.value_labels(dataset)
    except ServiceError:
        return {}, {}, {}
    names = {column: display_name(meaning) for column, meaning in rows if meaning.strip()}
    return labels, names, column_aliases(rows)


def _charts(
    answer: ManagerAnswer | None,
    measured: dict[str, float],
    labels: dict[str, dict[str, str]] | None = None,
    names: dict[str, str] | None = None,
    aliases: dict[str, str] | None = None,
) -> list[str]:
    """Một biểu đồ SVG cho mỗi kết luận, cùng thứ tự; rỗng nếu không vẽ được.

    Dùng đúng hàm vẽ của trang Python: bốn loại - cột, tròn, đường, số lớn -
    chọn theo hình dạng chỉ số. Trước đây bản Next chỉ hiện ảnh PNG cũ, nên
    feedback "đa dạng các loại chart" mất đi khi đổi giao diện.
    """
    if answer is None:
        return []
    drawn: list[str] = []
    for claim in answer.claims:
        # Chi ve nhung so dat duoc tren MOT truc; tron nhieu loai so thi thoi.
        keys = chart_keys(list(claim.metric_keys))
        drawn.append(
            chart_for(
                pairs_from(measured or {}, keys, labels, names),
                title=localize(str(claim.claim), aliases or {})[:60],
                story=len(keys) >= 2,
                heading=chart_title(keys, aliases),
            )
            or ""
        )
    return drawn


def round_payload(space: Workspace, dataset: str, run_id: str) -> dict[str, Any]:
    """One analysis round, including the answer exactly as Python produced it."""
    rounds = round_runs(space, dataset)
    questions = {run.run_id: question_of(space, run.run_id) for run in rounds}
    if run_id not in questions:
        raise ServiceError("Không có phân tích này.")
    answer = space.answer(run_id)
    measured = space.measured(run_id)
    gates = [gate_report(gate) for gate in space.gates(run_id)]
    labels, names, aliases = _display_words(space, dataset)
    return {
        "dataset_id": dataset,
        "round_id": run_id,
        "question": questions[run_id],
        "state": round_state(space, run_id),
        "running": space.running(run_id),
        "stopped_reason": _why_no_answer(space, run_id),
        "gates": gates,
        "actions": {
            "can_export": answer is not None,
            "can_follow_up": answer is not None,
            "can_approve": bool(gates),
        },
        "answer": manager_answer(answer, aliases) if answer is not None else None,
        "measured": measured,
        "charts": _charts(answer, measured, labels, names, aliases),
        # Tap nao cac con so thuoc ve, do code doc tu SQL loc; ten cot doi sang
        # tieng Viet chi de hien thi.
        "scope": [
            {**item, "condition": localize(str(item["condition"]), aliases)}
            for item in space.data_scope(run_id)
        ],
        "forecast": [
            {
                "name": item.name,
                "last_period": item.last_period,
                "low": item.low,
                "high": item.high,
                "r2": item.r2,
                "periods": item.periods,
                "caveat": item.caveat,
            }
            for item in forecast_values(measured)
        ],
        "tree": tree(space, dataset, [(run.run_id, questions[run.run_id]) for run in rounds]),
    }
