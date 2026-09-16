"""Quy tắc phụ thuộc giữa các tầng, cưỡng chế bằng test.

    api -> application -> agents / manager / domains -> models, core

Một module chỉ được import tầng thấp hơn hoặc cùng tầng. `core` và `models` cùng tầng dưới
cùng: ranh giới trong core cần hợp đồng `ScopeToken`, còn `models` chỉ dựa vào `core`.

Không có danh sách ngoại lệ. Đợt tái cấu trúc theo domain (plans/refactor-ddd.md) kết thúc
với con số 0, và mọi vi phạm mới phải trượt ngay tại đây chứ không phải sáu tháng sau, lúc
một người đọc code và tự hỏi vì sao tầng dưới lại biết tên một route.
"""

from __future__ import annotations

import ast
from collections.abc import Set as AbstractSet
from pathlib import Path
from typing import Final

SRC = Path(__file__).resolve().parents[2] / "src"

TIERS: Final[dict[str, int]] = {
    "core": 0,
    "models": 0,
    "domain": 3,
    "orchestration": 3,
    "application": 4,
    "api": 5,
    "entry": 6,
}

# Goi cap cao nhat (sau analysis_system.) -> tang.
LAYER_OF_PACKAGE: Final[dict[str, str]] = {
    "core": "core",
    "models": "models",
    "domains": "domain",
    "agents": "orchestration",
    "manager": "orchestration",
    "pipeline": "orchestration",
    "application": "application",
    "api": "api",
    "cli": "entry",
    "": "entry",
}


def _exists(name: str) -> bool:
    base = SRC.joinpath(*name.split("."))
    return base.with_suffix(".py").is_file() or (base / "__init__.py").is_file()


def _nearest(name: str) -> str:
    while name and not _exists(name):
        name = name.rpartition(".")[0]
    return name


def _modules() -> dict[str, Path]:
    found: dict[str, Path] = {}
    for path in sorted((SRC / "analysis_system").rglob("*.py")):
        parts = list(path.relative_to(SRC).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        found[".".join(parts)] = path
    return found


def _imports(path: Path) -> set[str]:
    """Mọi module analysis_system mà file này import, kể cả import nằm trong hàm."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(
                _nearest(alias.name)
                for alias in node.names
                if alias.name.startswith("analysis_system")
            )
        elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith("analysis_system"):
            module = node.module or ""
            for alias in node.names:
                child = f"{module}.{alias.name}"
                found.add(child if _exists(child) else _nearest(module))
    return found


def layer_of(module: str) -> str:
    """Tầng của một module, đọc từ tên gói cấp cao nhất."""
    parts = module.split(".")
    top = parts[1] if len(parts) > 1 else ""
    if top not in LAYER_OF_PACKAGE:
        raise AssertionError(f"goi {top!r} chua duoc xep tang trong test_architecture.py")
    return LAYER_OF_PACKAGE[top]


def violations() -> set[tuple[str, str]]:
    """Mọi cặp (module import, module bị import) đi ngược tầng."""
    found: set[tuple[str, str]] = set()
    for name, path in _modules().items():
        mine = TIERS[layer_of(name)]
        for imported in _imports(path):
            if TIERS[layer_of(imported)] > mine:
                found.add((name, imported))
    return found


def _listed(pairs: AbstractSet[tuple[str, str]]) -> str:
    return "\n".join(f"  {left}  ->  {right}" for left, right in sorted(pairs))


def test_no_import_goes_up_a_layer() -> None:
    found = violations()
    assert not found, f"import nguoc tang (tang duoi goi tang tren):\n{_listed(found)}"


def test_every_package_has_a_declared_layer() -> None:
    """Thêm một gói cấp cao mới mà quên xếp tầng thì luật trên bỏ sót nó."""
    tops = {name.split(".")[1] for name in _modules() if len(name.split(".")) > 1}
    assert tops <= set(LAYER_OF_PACKAGE), f"chua xep tang: {sorted(tops - set(LAYER_OF_PACKAGE))}"
