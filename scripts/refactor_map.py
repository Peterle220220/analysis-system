"""Bảng ánh xạ của đợt tái cấu trúc theo domain (plans/refactor-ddd.md, Mục 3).

Một nguồn duy nhất cho hai nơi: `move_module.py` chuyển file theo từng nhóm, và
`tests/unit/test_architecture.py` biết mỗi module thuộc tầng nào kể cả khi nó chưa được
chuyển. Hai nơi đọc hai bảng khác nhau thì sớm muộn sẽ lệch nhau. Hết đợt tái cấu trúc
(Phase 9) thì xoá file này.
"""

from __future__ import annotations

from typing import Final

SERVICES: Final[str] = "analysis_system.services"

# Nhom dich -> cac module hien nam trong services/.
SERVICE_GROUPS: Final[dict[str, tuple[str, ...]]] = {
    "core": (
        "hashing",
        "pii",
        "vietnamese_text",
        "punctuation",
        "units",
        "storage",
        "scoped_storage",
        "boundary",
        "audit",
        "budget",
        "job_error",
        "updater",
        "retention",
    ),
    "visualization": (
        "charts",
        "chart_choice",
        "svg_chart",
        "dashboards",
        "bi_schema",
        "bi_query",
        "bi_views",
        "reporting",
        "exporters",
        "export_answer",
        "metric_gauge",
    ),
    "data_ingestion": (
        "ingestion",
        "readers",
        "column_names",
        "number_format",
        "diagnosis",
        "rulebook",
        "rule_names",
        "rule_intent",
        "validation",
        "extraction",
        "documents",
        "dataset_origin",
        "dataset_labels",
        "dataset_removal",
        "dataset_context",
        "catalogue",
        "glossary_store",
        "glossary_draft",
        "display_names",
        "value_labels",
    ),
    "execution_engine": (
        "sql_runner",
        "sql_guard",
        "sql_shape",
        "cross_row",
        "point_values",
        "data_scope",
        "metrics",
        "metric_families",
        "statistics",
        "group_means",
        "forecast",
        "modelling",
        "features",
        "digging",
        "thresholds",
        "process_mining",
        "bpmn",
        "timeline",
    ),
    "ai_planner": (
        "llm",
        "prompts",
        "routing",
        "instructions",
        "question_parts",
        "question_labels",
        "asked_columns",
        "answer_shape",
        "shortlist",
        "relevance",
        "relevance_notice",
        "narrowing",
        "salience",
        "findings",
        "direct_answer",
        "risk_notes",
    ),
}

TARGETS: Final[dict[str, str]] = {
    "core": "analysis_system.core",
    "visualization": "analysis_system.domains.visualization",
    "data_ingestion": "analysis_system.domains.data_ingestion",
    "execution_engine": "analysis_system.domains.execution_engine",
    "ai_planner": "analysis_system.domains.ai_planner",
}

# Nhung module khong nam trong services/ ma cung doi cho, theo nhom.
OTHER_MOVES: Final[dict[str, dict[str, str]]] = {
    "core": {"analysis_system.settings": "analysis_system.core.settings"},
    "models": {"analysis_system.contracts": "analysis_system.models"},
    # api.py phai roi cho truoc thi web/ moi lay duoc ten api/.
    "application": {"analysis_system.api": "analysis_system.application.workspace"},
    "api": {"analysis_system.web": "analysis_system.api"},
}

# Chuyen ca goi: moi module con di theo. Cac muc khac chi la mot file.
PACKAGE_MOVES: Final[frozenset[str]] = frozenset(
    {"analysis_system.contracts", "analysis_system.web"}
)

# Thu tu cac phase (plans/refactor-ddd.md, Muc 5).
GROUP_ORDER: Final[tuple[str, ...]] = (
    "core",
    "models",
    "visualization",
    "data_ingestion",
    "execution_engine",
    "ai_planner",
    "application",
    "api",
)

INIT_DOCS: Final[dict[str, str]] = {
    "analysis_system.core": (
        "Hạ tầng dùng chung: cấu hình, lưu trữ, ranh giới, kiểm toán, ngân sách. Không nghiệp vụ."
    ),
    "analysis_system.domains": "Các lĩnh vực nghiệp vụ. Mỗi lĩnh vực chỉ dựa vào core và models.",
    "analysis_system.domains.visualization": "Biểu đồ, bảng điều khiển, Tự phân tích, báo cáo.",
    "analysis_system.domains.data_ingestion": "Nạp, đọc, làm sạch và quản lý bộ dữ liệu.",
    "analysis_system.domains.execution_engine": "Chạy SQL và mọi phép tính tất định.",
    "analysis_system.domains.ai_planner": "Gọi model, prompt, đọc câu hỏi, kiểm chứng đầu ra.",
    "analysis_system.application": "Điều phối các ca sử dụng giữa API và các lĩnh vực.",
}


def moves_for(group: str) -> dict[str, str]:
    """Module cũ -> module mới của một nhóm, theo thứ tự phải chuyển."""
    if group not in GROUP_ORDER:
        raise KeyError(f"khong co nhom {group!r}; cac nhom: {', '.join(GROUP_ORDER)}")
    moves = dict(OTHER_MOVES.get(group, {}))
    target = TARGETS.get(group, "")
    for leaf in SERVICE_GROUPS.get(group, ()):
        moves[f"{SERVICES}.{leaf}"] = f"{target}.{leaf}"
    return moves


ALL_MOVES: Final[dict[str, str]] = {
    old: new for group in GROUP_ORDER for old, new in moves_for(group).items()
}


def final_name(module: str) -> str:
    """Tên module sau đợt tái cấu trúc; module không đổi chỗ thì giữ nguyên tên."""
    for old, new in ALL_MOVES.items():
        if module == old:
            return new
        if old in PACKAGE_MOVES and module.startswith(old + "."):
            return new + module[len(old) :]
    return module
