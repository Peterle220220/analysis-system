"""Khong co dau gach ngang dai (em dash) trong chu he thong hien thi.

Chu he thong: "toi khong thich co emdash trong he thong cua minh, khong chuyen
nghiep". Doc bang AST nhu test chong viet cung: chi lay CHUOI CHAY THAT, bo chu
thich va docstring - nguoi dung khong bao gio thay nhung cho do.

Chu do model viet thi khong chan duoc bang loi dan, nen duoc don luc hien thi va
luc xuat Word/Excel (services/punctuation.py).
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from analysis_system.services.punctuation import plain_dashes

DASH = chr(8212)


def _runtime_strings(path: pathlib.Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docs.add(id(body[0].value))
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs
    ]


@pytest.mark.parametrize(
    "path", sorted(pathlib.Path("src/analysis_system").rglob("*.py")), ids=lambda p: p.name
)
def test_no_em_dash_in_backend_text(path: pathlib.Path) -> None:
    found = [f"dong {line}: {text[:60]}" for line, text in _runtime_strings(path) if DASH in text]
    assert found == []


def test_no_em_dash_in_frontend_text() -> None:
    found = []
    for path in sorted(pathlib.Path("frontend/src").rglob("*")):
        if path.suffix not in {".ts", ".tsx"}:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if DASH in line and not line.strip().startswith(("//", "/*", "*")):
                found.append(f"{path.name}:{number}")
    assert found == []


# --- chu do model viet ------------------------------------------------------------


def test_a_dash_between_two_clauses_becomes_a_comma() -> None:
    assert plain_dashes(f"ROA cao hơn {DASH} nhóm phá sản thấp hơn") == (
        "ROA cao hơn, nhóm phá sản thấp hơn"
    )


def test_a_dash_at_either_end_leaves_no_stray_comma() -> None:
    assert plain_dashes(f"{DASH} kết luận") == "kết luận"
    assert plain_dashes(f"kết luận {DASH}") == "kết luận"


def test_text_without_a_dash_is_unchanged() -> None:
    assert plain_dashes("Tỷ lệ nợ: 0,25 (n = 6.819).") == "Tỷ lệ nợ: 0,25 (n = 6.819)."


def test_numbers_are_not_touched() -> None:
    """Chi doi dau cau - con so trong ket luan da duoc kiem, khong duoc dong toi."""
    assert plain_dashes(f"-0.26 {DASH} 0.25") == "-0.26, 0.25"
