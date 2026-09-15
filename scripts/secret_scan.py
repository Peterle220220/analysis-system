"""Quét phần diff đã stage tìm khoá API trước khi commit.

    python scripts/secret_scan.py

Tự kiểm mẫu trước khi quét: một mẫu hỏng thì im lặng báo "sạch", và đó là lúc nguy hiểm
nhất. Chỉ đọc dòng THÊM MỚI; dòng bị xoá không đi ra khỏi máy thêm lần nào nữa.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterable
from typing import Final

PATTERN: Final[re.Pattern[str]] = re.compile(r"(sk-ant-|AIza|AQ\.|sk-or-v1-)[0-9A-Za-z._-]{20,}")
# In ra bao nhieu ky tu dau cua mot dong bi bat: du de tim dong do, khong du lo khoa.
SHOWN: Final[int] = 12


def self_check() -> None:
    """Mẫu phải bắt được một khoá giả, và bỏ qua chữ thường có tiền tố đó.

    Khoá giả được ghép lúc chạy, để chính file này không chứa một chuỗi trông như khoá.
    """
    fake = "sk-" + "ant-" + "x" * 24
    if not PATTERN.search(fake):
        raise AssertionError("mau khong bat duoc khoa gia")
    if PATTERN.search("tien to sk-ant- trong mot cau thuong"):
        raise AssertionError("mau bat nham chu thuong")


def added_lines(diff: str) -> list[str]:
    """Những dòng thêm mới của một diff, bỏ dòng tiêu đề `+++`."""
    return [
        line for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")
    ]


def hits(lines: Iterable[str]) -> list[str]:
    """Những dòng trông như chứa khoá, chỉ giữ vài ký tự đầu."""
    return [line[:SHOWN] + "..." for line in lines if PATTERN.search(line)]


def main() -> int:
    """Quét diff đã stage; trả 1 khi thấy khoá."""
    self_check()
    diff = subprocess.run(
        ["git", "diff", "--cached", "-U0"], capture_output=True, text=True, check=True
    ).stdout
    added = added_lines(diff)
    found = hits(added)
    if found:
        print(f"CO KHOA: {len(found)} dong")
        return 1
    print(f"SACH: quet {len(added)} dong them moi")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
