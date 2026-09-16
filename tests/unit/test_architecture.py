"""Quy tắc phụ thuộc giữa các tầng (plans/refactor-ddd.md, Mục 4), cưỡng chế kiểu bánh cóc.

    api -> application -> agents / manager / domains -> models, core

Một module chỉ được import tầng thấp hơn hoặc cùng tầng. `core` và `models` cùng tầng dưới
cùng: ranh giới trong core cần hợp đồng `ScopeToken`, và kế hoạch chỉ cấm core import domain,
agents, manager, application, api. Mỗi module được xếp tầng theo chỗ
nó SẼ nằm (`refactor_map.final_name`), nên luật đúng ngay từ trước khi chuyển file, và danh
sách nền không đổi tên khi file được chuyển.

Vi phạm đang có nằm trong `BASELINE`: chúng không làm trượt test. Vi phạm mới thì trượt, và
một mục trong danh sách nền không còn thật cũng trượt, để danh sách chỉ có thể ngắn đi.
"""

from __future__ import annotations

import ast
from collections.abc import Set as AbstractSet
from pathlib import Path
from typing import Final

from refactor_map import ALL_MOVES, SERVICE_GROUPS, final_name

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
    # services/ con lai toi het Phase 7; moi module trong do da co cho trong refactor_map.
    "services": "domain",
    "agents": "orchestration",
    "manager": "orchestration",
    "pipeline": "orchestration",
    "application": "application",
    "api": "api",
    "cli": "entry",
    "": "entry",
}

# (module import, module bi import), theo ten SAU tai cau truc. Vi pham da co truoc Phase 0,
# kem phase se go no.
BASELINE: Final[frozenset[tuple[str, str]]] = frozenset()


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
    """Tầng của một module, đọc theo tên sau tái cấu trúc."""
    parts = final_name(module).split(".")
    top = parts[1] if len(parts) > 1 else ""
    if top not in LAYER_OF_PACKAGE:
        raise AssertionError(f"goi {top!r} chua duoc xep tang trong test_architecture.py")
    return LAYER_OF_PACKAGE[top]


def violations() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for name, path in _modules().items():
        mine = TIERS[layer_of(name)]
        for imported in _imports(path):
            if TIERS[layer_of(imported)] > mine:
                found.add((final_name(name), final_name(imported)))
    return found


def _listed(pairs: AbstractSet[tuple[str, str]]) -> str:
    return "\n".join(f"  {left}  ->  {right}" for left, right in sorted(pairs))


def test_no_new_import_goes_up_a_layer() -> None:
    new = violations() - BASELINE
    assert not new, f"import nguoc tang (tang duoi goi tang tren):\n{_listed(new)}"


def test_the_baseline_only_lists_violations_that_still_exist() -> None:
    stale = BASELINE - violations()
    assert not stale, f"da het vi pham, xoa khoi BASELINE:\n{_listed(stale)}"


def test_every_service_module_has_exactly_one_destination() -> None:
    mapped = [leaf for leaves in SERVICE_GROUPS.values() for leaf in leaves]
    assert len(mapped) == len(set(mapped))
    services = SRC / "analysis_system" / "services"
    on_disk = {path.stem for path in services.glob("*.py")} - {"__init__"}
    assert on_disk <= set(mapped), f"chua xep cho: {sorted(on_disk - set(mapped))}"


def test_every_planned_move_is_on_exactly_one_side() -> None:
    # Truoc khi chuyen: chi co ten cu. Sau khi chuyen: chi co ten moi. Ca hai hay khong ben
    # nao deu la dau hieu mot lan chuyen do dang.
    # Ten `analysis_system.api` duoc dung hai lan (api.py roi di, web/ vao thay), nen voi cac
    # lan chuyen dinh toi no chi doi mot dieu: khong mat module nao.
    reused = set(ALL_MOVES) & set(ALL_MOVES.values())
    wrong: list[tuple[str, str]] = []
    for old, new in ALL_MOVES.items():
        before, after = _exists(old), _exists(new)
        if old in reused or new in reused:
            if not (before or after):
                wrong.append((old, new))
        elif before == after:
            wrong.append((old, new))
    assert wrong == []
