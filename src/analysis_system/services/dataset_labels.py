"""Tên bộ dữ liệu người dùng gõ, giữ nguyên dấu và khoảng trắng để hiển thị.

Mã bộ dữ liệu ("bao_cao_tai_chinh_mb_cua_4_quy_gan_nhat") phải an toàn cho đường
dẫn và tên thư mục, nên bỏ dấu và thay khoảng trắng. Nhưng đó là tên của máy, không
phải của người: người dùng gõ "Báo cáo tài chính MB của 4 quý gần nhất" và muốn thấy
đúng như thế. Sổ này giữ tên người gõ; mã vẫn là thứ duy nhất đi vào đường dẫn.

Một sổ JSON ở gốc thư mục runs, như sổ lối vào (dataset_origin): lúc tải lên, thư
mục của bộ chưa có. Bộ tải lên trước khi có sổ thì hiện mã.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path, PurePosixPath
from typing import Final

LABEL_FILE: Final[str] = "ten_bo_du_lieu.json"
MAX_LABEL: Final[int] = 120

# Hai lan tai cung luc cung doc roi ghi so: khoa de lan sau khong xoa dong cua lan truoc.
_LOCK = threading.Lock()


def _tidy(text: str) -> str:
    printable = "".join(char for char in str(text) if char.isprintable())
    return " ".join(printable.split())[:MAX_LABEL]


def display_label(typed: str, filename: str) -> str:
    """Tên hiển thị: tên người dùng gõ, không thì tên tệp bỏ đuôi."""
    # Trinh duyet cu gui ca "C:\\fakepath\\ten.csv".
    stem = PurePosixPath(str(filename or "").replace("\\", "/")).stem
    return _tidy(typed) or _tidy(stem)


def read_labels(runs_root: Path) -> dict[str, str]:
    """Cả sổ: mã bộ dữ liệu thành tên hiển thị. Sổ hỏng hay chưa có thì rỗng."""
    try:
        raw = json.loads((runs_root / LABEL_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items() if isinstance(value, str) and value}


def label_of(runs_root: Path, dataset: str) -> str:
    """Tên hiển thị của một bộ; bộ chưa có tên thì là chính mã của nó."""
    return read_labels(runs_root).get(dataset) or dataset


def record_label(runs_root: Path, dataset: str, label: str) -> str:
    """Ghi tên hiển thị (tải lại thì ghi đè). Trả về đúng tên đã ghi, rỗng thì không ghi."""
    tidy = _tidy(label)
    if not tidy:
        forget_label(runs_root, dataset)
        return ""
    with _LOCK:
        found = read_labels(runs_root)
        found[dataset] = tidy
        _write(runs_root, found)
    return tidy


def forget_label(runs_root: Path, dataset: str) -> None:
    """Bỏ tên của một bộ đã xoá. Không có trong sổ thì thôi."""
    with _LOCK:
        found = read_labels(runs_root)
        if found.pop(dataset, None) is None:
            return
        _write(runs_root, found)


def _write(runs_root: Path, found: dict[str, str]) -> None:
    runs_root.mkdir(parents=True, exist_ok=True)
    target = runs_root / LABEL_FILE
    temporary = target.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(found, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    temporary.replace(target)
