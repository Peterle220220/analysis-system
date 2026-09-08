"""Co cho nao trong code gan cung vao mot bo du lieu cu the khong?

Doc bang AST, khong bang grep: chi lay CHUOI THAT trong code, bo het chu thich
va docstring. Mot chu thich ghi lai bang chung "loi nay lo ra tren bo phá sản"
la dung; mot dieu kien `if column == "Bankrupt?"` thi khong.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

# Ten bo du lieu va ten cot da xuat hien trong cac lan thu that. Khong cai nao
# duoc phep nam trong code - chung chi duoc nam trong CHU THICH, de ghi lai
# bang chung vi sao mot cho duoc sua.
RIENG = re.compile(
    r"bankrupt|finance_data|bank_additional|roa\(|debt ratio|poutcome|"
    r"invest_monitor|y_flag|reason_equity|emp\.var|cons\.price",
    re.IGNORECASE,
)

FILES = sorted(pathlib.Path("src/analysis_system").rglob("*.py"))


def _code_strings(path: pathlib.Path) -> list[tuple[int, str]]:
    """Moi chuoi trong code, tru docstring.

    Doc bang AST chu khong bang grep: mot chu thich ghi lai "loi nay lo ra tren
    bo phá sản" la dung, con mot dieu kien so voi ten cot do thi khong.
    """
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


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_no_code_is_tied_to_one_dataset(path: pathlib.Path) -> None:
    """Moi ban sua phai dung duoc cho du lieu moi, khong chi cho lan nay.

    Da bat duoc that: hai luat gui cho model lay vi du bang ten cot cua mot bo
    cu the. Model doc vi du ay tren mot bang khong co cot do se di trich mot
    chi so khong ton tai, va ca ket luan bi loai.
    """
    found = [
        f"dong {line}: {text[:80]}" for line, text in _code_strings(path) if RIENG.search(text)
    ]
    assert found == []
