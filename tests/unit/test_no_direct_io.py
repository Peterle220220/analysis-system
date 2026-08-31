"""Layer 2, enforced statically: no agent may reach the filesystem behind ScopedStorage.

Banning open() alone would miss the bigger hole. pandas.read_csv and
DataFrame.to_parquet go straight to disk and bypass the storage gateway
entirely, as does duckdb.connect. This test walks the AST of every agent module
and refuses all of them.

Naming matters here. The low-level gateway (services/storage.py) uses
read_/write_; the agent-facing wrapper (ScopedStorage) uses load_/save_. That
split is deliberate: it means any read_*/to_* call inside an agent is
unambiguously a direct filesystem access, with no false positive to argue about.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

AGENTS_DIR = Path(__file__).resolve().parents[2] / "src" / "analysis_system" / "agents"

BANNED_NAMES = frozenset({"open", "eval", "exec", "compile", "__import__"})
BANNED_MODULES = frozenset({"os", "shutil", "subprocess", "pathlib", "duckdb", "tempfile", "io"})

# pandas readers and writers, named explicitly. A prefix rule would also catch
# harmless in-memory calls such as to_dict() or to_list().
BANNED_ATTRIBUTES = frozenset(
    {
        "read_csv",
        "read_parquet",
        "read_excel",
        "read_json",
        "read_table",
        "read_sql",
        "read_pickle",
        "read_feather",
        "read_hdf",
        "read_fwf",
        "read_html",
        "read_xml",
        "read_stata",
        "read_text",
        "to_csv",
        "to_parquet",
        "to_excel",
        "to_json",
        "to_pickle",
        "to_feather",
        "to_hdf",
        "to_sql",
        "to_stata",
        "write_text",
        "connect",
        "system",
        "popen",
    }
)

# base.py is the harness that applies the boundary, not a worker agent. It needs
# pathlib for a type annotation, and its own behaviour is pinned by the contract
# tests in tests/contract/test_base_agent.py. It is still held to the stricter
# rule below: it may name pathlib, but it may not call any I/O itself.
HARNESS_MODULES = frozenset({"base.py", "__init__.py"})


def agent_modules() -> list[Path]:
    """Every worker agent module under the agents package."""
    if not AGENTS_DIR.is_dir():
        return []
    return sorted(path for path in AGENTS_DIR.rglob("*.py") if path.name not in HARNESS_MODULES)


def _offences(tree: ast.AST) -> list[str]:
    """Collect every direct filesystem access in one module."""
    found: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in BANNED_MODULES:
                    found.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in BANNED_MODULES:
                found.append(f"from {node.module} import ...")
            if node.module == "analysis_system.services.storage":
                found.append("import truc tiep services.storage")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in BANNED_NAMES:
                found.append(f"{func.id}(...)")
            elif isinstance(func, ast.Attribute) and func.attr in BANNED_ATTRIBUTES:
                found.append(f".{func.attr}(...)")
    return found


def _io_calls(tree: ast.AST) -> list[str]:
    """Collect only the direct I/O calls in a module, ignoring imports."""
    return [offence for offence in _offences(tree) if offence.endswith("(...)")]


@pytest.mark.parametrize("module", agent_modules(), ids=lambda path: path.name)
def test_no_agent_touches_the_filesystem_directly(module: Path) -> None:
    tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
    offences = _offences(tree)
    assert not offences, (
        f"{module.name} truy cap filesystem truc tiep: {offences}. "
        "Moi I/O phai di qua ScopedStorage (load_* / save_*)."
    )


def test_the_agent_harness_performs_no_io_of_its_own() -> None:
    harness = AGENTS_DIR / "base.py"
    if not harness.is_file():
        pytest.skip("chua co agents/base.py")
    tree = ast.parse(harness.read_text(encoding="utf-8"), filename=str(harness))
    assert _io_calls(tree) == [], "agents/base.py khong duoc tu doc ghi bat cu thu gi"


def test_the_check_actually_catches_a_violation() -> None:
    # A guard that never fires is worse than no guard: prove it fires.
    source = "\n".join(
        [
            "import pandas as pd",
            "def sneaky():",
            "    frame = pd.read_csv('/etc/passwd')",
            "    frame.to_parquet('/tmp/out.parquet')",
            "    return open('/etc/shadow')",
        ]
    )
    offences = _offences(ast.parse(source))
    assert ".read_csv(...)" in offences
    assert ".to_parquet(...)" in offences
    assert "open(...)" in offences


def test_importing_os_or_duckdb_is_caught() -> None:
    offences = _offences(ast.parse("import os\nimport duckdb\nfrom pathlib import Path\n"))
    assert "import os" in offences
    assert "import duckdb" in offences
    assert "from pathlib import ..." in offences


def test_the_scoped_storage_api_is_not_mistaken_for_a_violation() -> None:
    # The whole reason ScopedStorage uses load_/save_: an agent calling it must
    # produce no offence, so a real violation can never be argued away.
    source = "\n".join(
        [
            "def clean(request, files):",
            "    frame = files.load_parquet('staging://events.parquet')",
            "    counts = frame.to_dict()",
            "    head = files.load_bytes('raw://x.csv', limit=1024)",
            "    return files.save_parquet(frame, 'clean://events.parquet'), counts, head",
        ]
    )
    assert _offences(ast.parse(source)) == []
