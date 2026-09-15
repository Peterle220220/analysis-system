"""Mọi module của hệ thống import được.

Lưới an toàn cho đợt tái cấu trúc (plans/refactor-ddd.md, Phase 0): chuyển một file mà
sót một đường import thì module gọi nó hỏng ngay lúc import. Coverage không bắt được chỗ
đó ở những file ít test chạm tới (cli.py mới phủ 53%), nên test này import từng module.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"


def _modules() -> list[str]:
    names: list[str] = []
    for path in sorted((SRC / "analysis_system").rglob("*.py")):
        parts = list(path.relative_to(SRC).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        names.append(".".join(parts))
    return names


def test_the_package_is_found_at_all() -> None:
    assert len(_modules()) > 100


@pytest.mark.parametrize("name", _modules())
def test_every_module_imports(name: str) -> None:
    importlib.import_module(name)
