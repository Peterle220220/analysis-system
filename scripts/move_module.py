"""Chuyển một module (hay cả một nhóm trong refactor_map) và sửa mọi chỗ gọi tới nó.

    python scripts/move_module.py analysis_system.services.storage analysis_system.core.storage
    python scripts/move_module.py --group core            # chạy thử: chỉ in ra sẽ làm gì
    python scripts/move_module.py --group core --apply    # làm thật

Chạy thử là mặc định. Công cụ này sửa hàng trăm file một lượt, nên trước khi ghi phải thấy
được nó định ghi gì.

Được sửa (file .py trong src/, tests/, scripts/, tasks.py; pyproject.toml, Dockerfile,
docker-compose.yml, config/*.yaml):

- `from analysis_system.services import storage, llm`: tách thành hai câu, tên cục bộ giữ
  nguyên (`from ... import workspace as api` khi module đổi cả tên).
- mọi tên chấm `analysis_system.services.storage...`: câu import, chuỗi trong monkeypatch.
- đường dẫn `analysis_system/services/storage.py` (per-file-ignores, test đọc file).

Tài liệu Markdown chỉ được liệt kê, không tự sửa: chúng kể lại lịch sử, và chỗ nào cần sửa
(BUILD_SPEC) thì sửa bằng tay có chủ đích. File được chuyển bằng `git mv` để giữ lịch sử.
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from refactor_map import GROUP_ORDER, INIT_DOCS, moves_for

ROOT = Path(__file__).resolve().parents[1]
CODE_DIRS = ("src", "tests", "scripts")
CODE_FILES = ("tasks.py",)
TEXT_FILES = ("pyproject.toml", "Dockerfile", "docker-compose.yml")
SKIPPED = frozenset(
    {".git", ".venv", "node_modules", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
)
# Chinh bo cong cu tai cau truc. Chung chua ten module cu lam DU LIEU (bang anh xa, vi du
# trong test, danh sach nen): sua chung la pha bang anh xa. Lan chay thu dau tien tren repo
# that da dinh sua ca refactor_map.py lan chinh file nay.
TOOLING = frozenset(
    {
        "scripts/refactor_map.py",
        "scripts/move_module.py",
        "tests/unit/test_move_module.py",
        "tests/unit/test_architecture.py",
    }
)


@dataclass
class Report:
    """Những gì một lượt chuyển đã (hay sẽ) làm."""

    moves: list[tuple[str, str]] = field(default_factory=list)
    created: list[str] = field(default_factory=list)
    edits: dict[str, int] = field(default_factory=dict)
    mentions: dict[str, int] = field(default_factory=dict)


def _split(dotted: str) -> tuple[str, str]:
    parent, _, leaf = dotted.rpartition(".")
    return parent, leaf


def _alias(alias: ast.alias) -> str:
    return f"{alias.name} as {alias.asname}" if alias.asname else alias.name


def _from_imports(text: str, old: str, new: str) -> tuple[str, int]:
    """Tách những câu `from <gói cha> import <lá>` có nhắc tới module bị chuyển.

    Tên chấm đầy đủ thì phép thay chữ lo được. Dạng này thì không: tên module đứng tách
    khỏi gói cha, có khi chung một câu với module không chuyển. Tên cục bộ giữ nguyên, nên
    không dòng nào khác trong file phải sửa.
    """
    old_parent, old_leaf = _split(old)
    new_parent, new_leaf = _split(new)
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return text, 0
    lines = text.splitlines(keepends=True)
    edits: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.level or node.module != old_parent:
            continue
        moved = [alias for alias in node.names if alias.name == old_leaf]
        if not moved:
            continue
        start, end = node.lineno, node.end_lineno or node.lineno
        head = lines[start - 1][: node.col_offset]
        if head.strip():
            raise SystemExit(f"cau import dung chung dong voi code khac (dong {start}), sua tay")
        tail = lines[end - 1][node.end_col_offset or 0 :].rstrip("\r\n")
        kept = [alias for alias in node.names if alias.name != old_leaf]
        statements = [f"from {old_parent} import {', '.join(map(_alias, kept))}"] if kept else []
        for alias in moved:
            local = alias.asname or old_leaf
            rename = "" if local == new_leaf else f" as {local}"
            statements.append(f"from {new_parent} import {new_leaf}{rename}")
        body = "\n".join(head + statement for statement in statements)
        edits.append((start, end, f"{body}{tail}\n"))
    for start, end, replacement in sorted(edits, reverse=True):
        lines[start - 1 : end] = [replacement]
    return "".join(lines), len(edits)


def rewrite(
    text: str, old: str, new: str, *, package: bool = False, python: bool = True
) -> tuple[str, int]:
    """Sửa một văn bản cho khớp với module đã chuyển.

    Returns:
        Văn bản mới và số chỗ đã sửa.
    """
    count = 0
    if python:
        text, count = _from_imports(text, old, new)
    text, dotted = re.subn(rf"(?<![\w.]){re.escape(old)}(?!\w)", new, text)
    old_path, new_path = old.replace(".", "/"), new.replace(".", "/")
    if package:
        text, paths = re.subn(rf"(?<!\w){re.escape(old_path)}(?=/)", new_path, text)
    else:
        text, paths = re.subn(rf"(?<!\w){re.escape(old_path)}\.py(?!\w)", f"{new_path}.py", text)
    return text, count + dotted + paths


def _walk(root: Path, suffix: str) -> list[Path]:
    found: list[Path] = []
    for folder, dirnames, filenames in root.walk():
        dirnames[:] = [name for name in dirnames if name not in SKIPPED]
        found.extend(folder / name for name in filenames if name.endswith(suffix))
    return sorted(found)


def _files(root: Path) -> tuple[list[Path], list[Path], list[Path]]:
    """(file Python, file cấu hình, tài liệu Markdown) có thể nhắc tới một module."""
    python = [
        path
        for folder in CODE_DIRS
        if (root / folder).is_dir()
        for path in _walk(root / folder, ".py")
        if path.relative_to(root).as_posix() not in TOOLING
    ]
    python += [root / name for name in CODE_FILES if (root / name).is_file()]
    text = [root / name for name in TEXT_FILES if (root / name).is_file()]
    if (root / "config").is_dir():
        text += _walk(root / "config", ".yaml")
    return python, text, _walk(root, ".md")


def _location(root: Path, dotted: str) -> Path | None:
    base = root.joinpath("src", *dotted.split("."))
    if base.with_suffix(".py").is_file():
        return base.with_suffix(".py")
    if (base / "__init__.py").is_file():
        return base
    return None


def _ensure_packages(root: Path, package: str, report: Report, *, apply: bool) -> None:
    """Tạo `__init__.py` cho mọi gói mới trên đường tới `package`."""
    parts = package.split(".")
    for index in range(2, len(parts) + 1):
        name = ".".join(parts[:index])
        init = root.joinpath("src", *parts[:index], "__init__.py")
        if init.is_file() or name in report.created:
            continue
        report.created.append(name)
        if apply:
            init.parent.mkdir(parents=True, exist_ok=True)
            init.write_text(f'"""{INIT_DOCS.get(name, name)}"""\n', encoding="utf-8")


def _move(root: Path, source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if (root / ".git").exists():
        subprocess.run(["git", "mv", str(source), str(target)], cwd=root, check=True)
    else:
        source.rename(target)


def run(root: Path, moves: dict[str, str], *, apply: bool, tidy: bool = True) -> Report:
    """Chuyển các module trong `moves` và sửa mọi chỗ nhắc tới chúng.

    Args:
        apply: False thì chỉ báo cáo, không ghi gì.
        tidy: xếp lại import bằng ruff sau khi ghi (tắt trong test).
    """
    report = Report()
    plan: list[tuple[str, str, Path, Path, bool]] = []
    for old, new in moves.items():
        source = _location(root, old)
        if source is None:
            raise SystemExit(f"khong tim thay module {old}")
        package = source.is_dir()
        base = root.joinpath("src", *new.split("."))
        target = base if package else base.with_suffix(".py")
        if target.exists() or _location(root, new) is not None:
            raise SystemExit(f"da co san {new}, khong ghi de")
        plan.append((old, new, source, target, package))
        report.moves.append((old, new))

    python, text, docs = _files(root)
    for path in [*python, *text]:
        original = path.read_text(encoding="utf-8")
        changed, total = original, 0
        for old, new, _, _, package in plan:
            changed, count = rewrite(
                changed, old, new, package=package, python=path.suffix == ".py"
            )
            total += count
        if total:
            report.edits[str(path.relative_to(root))] = total
            if apply:
                path.write_text(changed, encoding="utf-8")
    for path in docs:
        content = path.read_text(encoding="utf-8")
        hits = sum(content.count(old) + content.count(old.replace(".", "/")) for old, *_ in plan)
        if hits:
            report.mentions[str(path.relative_to(root))] = hits

    for _, new, source, target, _ in plan:
        _ensure_packages(root, _split(new)[0], report, apply=apply)
        if apply:
            _move(root, source, target)
    if apply and tidy:
        folders = [name for name in (*CODE_DIRS, *CODE_FILES) if (root / name).exists()]
        subprocess.run(
            [sys.executable, "-m", "ruff", "check", "--fix", "--select", "I", "--quiet", *folders],
            cwd=root,
            check=False,
        )
    return report


def main(argv: list[str] | None = None) -> int:
    """Dòng lệnh: in ra kế hoạch (hay kết quả) của một lượt chuyển."""
    parser = argparse.ArgumentParser(description="Chuyen module va sua moi cho goi toi no.")
    parser.add_argument("old", nargs="?", help="ten module cu, vd analysis_system.services.llm")
    parser.add_argument("new", nargs="?", help="ten module moi")
    parser.add_argument(
        "--group", choices=GROUP_ORDER, help="chuyen ca mot nhom trong refactor_map"
    )
    parser.add_argument("--apply", action="store_true", help="lam that (mac dinh chi chay thu)")
    args = parser.parse_args(argv)
    if args.group:
        moves = moves_for(str(args.group))
    elif args.old and args.new:
        moves = {str(args.old): str(args.new)}
    else:
        parser.error("can OLD NEW hoac --group")

    report = run(ROOT, moves, apply=bool(args.apply))
    mode = "DA LAM" if args.apply else "CHAY THU (chua ghi gi)"
    print(f"== {mode}: {len(report.moves)} module ==")
    for old, new in report.moves:
        print(f"  {old} -> {new}")
    for name in report.created:
        print(f"  goi moi: {name}")
    print(f"== sua {len(report.edits)} file, {sum(report.edits.values())} cho ==")
    for path, count in sorted(report.edits.items()):
        print(f"  {count:4d}  {path}")
    if report.mentions:
        print("== tai lieu nhac toi module (xem tay, khong tu sua) ==")
        for path, count in sorted(report.mentions.items()):
            print(f"  {count:4d}  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
