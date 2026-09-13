"""Thu tu cac lop trong Dockerfile quyet dinh moi lan build de lai bao nhieu rac.

Truoc 2026-09-13, src/ duoc chep vao cung stage voi thu vien, roi ca /opt/venv
2.3 GB duoc chep sang image chay. Sua mot dong code la mot lop 2.3 GB moi, va
build cache giu lai tung lop cu: 81 GB. Cac test nay giu cho code va thu vien
nam o hai lop tach nhau.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "Dockerfile"
STAGE = re.compile(r"FROM\s+(\S+)\s+AS\s+(\S+)", re.IGNORECASE)
VENV_FROM = re.compile(r"COPY\s+--from=(\S+)\s+/opt/venv\s")


def _stages() -> tuple[dict[str, list[str]], dict[str, str]]:
    """Cac dong cua tung stage (bo chu thich), va stage nao dung tren stage nao."""
    lines: dict[str, list[str]] = {}
    bases: dict[str, str] = {}
    current = ""
    for raw in DOCKERFILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        found = STAGE.match(line)
        if found:
            current = found.group(2)
            bases[current] = found.group(1)
            lines[current] = []
            continue
        lines[current].append(line)
    return lines, bases


def _runtime() -> list[str]:
    lines, _ = _stages()
    return list(lines.values())[-1]


def _library_stage() -> str:
    for line in _runtime():
        found = VENV_FROM.match(line)
        if found:
            return found.group(1)
    raise AssertionError("stage cuoi khong chep /opt/venv tu stage nao")


def _chain(stage: str) -> list[str]:
    """Stage do va moi stage no dung len tren."""
    lines, bases = _stages()
    chain = [stage]
    while bases.get(chain[-1]) in lines:
        chain.append(bases[chain[-1]])
    return chain


def test_the_libraries_come_from_a_stage_that_never_sees_the_source() -> None:
    lines, _ = _stages()
    for stage in _chain(_library_stage()):
        copies = [line for line in lines[stage] if line.upper().startswith("COPY")]
        assert not [c for c in copies if "src/" in c], (
            f"stage '{stage}' chep src/: moi lan sua code se tao lai ca lop thu vien 2.3 GB"
        )


def test_the_library_stage_reads_the_dependency_list_not_pyproject() -> None:
    lines, _ = _stages()
    for stage in _chain(_library_stage()):
        copies = [line for line in lines[stage] if line.upper().startswith("COPY")]
        assert not [c for c in copies if "pyproject.toml" in c], (
            f"stage '{stage}' chep pyproject.toml: sua cau hinh ruff cung cai lai torch"
        )


def test_the_application_goes_in_after_the_libraries() -> None:
    runtime = _runtime()
    venv_at = next(i for i, line in enumerate(runtime) if VENV_FROM.match(line))
    wheel_at = [i for i, line in enumerate(runtime) if "/tmp/wheels" in line]
    assert wheel_at, "stage cuoi khong cai ung dung tu wheel"
    assert min(wheel_at) > venv_at


def test_the_application_is_not_copied_in_as_a_whole_venv() -> None:
    copies = [line for line in _runtime() if line.upper().startswith("COPY")]
    assert len([c for c in copies if "/opt/venv" in c]) == 1


def test_the_extracted_list_is_exactly_the_declared_dependencies(tmp_path: Path) -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    found = re.search(r'python -c "([^"]+)" > deps\.txt', text)
    assert found, "khong thay lenh rut danh sach thu vien trong Dockerfile"
    shutil.copy(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    shown = subprocess.run(
        [sys.executable, "-c", found.group(1)],
        cwd=tmp_path, capture_output=True, text=True, check=True,
    ).stdout.split("\n")
    with (ROOT / "pyproject.toml").open("rb") as handle:
        declared = tomllib.load(handle)["project"]["dependencies"]
    assert [line for line in shown if line] == declared
