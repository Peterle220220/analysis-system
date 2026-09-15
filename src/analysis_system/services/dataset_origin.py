"""Bộ dữ liệu vào hệ thống từ đâu: mục Dữ liệu, hay tải thẳng vào Tự phân tích.

Hai lối vào dùng chung một đường tải lên và một luồng làm sạch; chỉ khác chỗ người
dùng đứng khi thả tệp. Ghi lại lối vào để trang Tự phân tích chia hai nhóm.

Một sổ ghi JSON ở gốc thư mục runs, không nằm trong thư mục của từng bộ: lúc tải
lên, thư mục đó chưa có, và một thư mục chỉ chứa một tệp ghi chú sẽ trông như một
lần chạy hỏng. Bộ tải lên trước khi có sổ này thì coi là từ mục Dữ liệu.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Final

ORIGIN_FILE: Final[str] = "nguon_bo_du_lieu.json"
DIRECT: Final[str] = "tu_phan_tich"
LIBRARY: Final[str] = "du_lieu"
ORIGINS: Final[frozenset[str]] = frozenset({DIRECT, LIBRARY})

# Hai lần tải cùng lúc cùng đọc rồi ghi sổ: khoá để lần sau không xoá dòng của lần trước.
_LOCK = threading.Lock()


def read_origins(runs_root: Path) -> dict[str, str]:
    """Cả sổ: tên bộ dữ liệu thành lối vào. Sổ hỏng hay chưa có thì rỗng."""
    try:
        raw = json.loads((runs_root / ORIGIN_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(name): str(origin) for name, origin in raw.items() if origin in ORIGINS}


def record_origin(runs_root: Path, dataset: str, origin: str) -> str:
    """Ghi lối vào của một lần tải lên (tải lại thì ghi đè). Trả về đúng giá trị đã ghi."""
    chosen = origin if origin in ORIGINS else LIBRARY
    with _LOCK:
        found = read_origins(runs_root)
        found[dataset] = chosen
        _write(runs_root, found)
    return chosen


def forget_origin(runs_root: Path, dataset: str) -> None:
    """Bỏ một bộ đã xoá khỏi sổ. Không có trong sổ thì thôi."""
    with _LOCK:
        found = read_origins(runs_root)
        if found.pop(dataset, None) is None:
            return
        _write(runs_root, found)


def _write(runs_root: Path, found: dict[str, str]) -> None:
    runs_root.mkdir(parents=True, exist_ok=True)
    target = runs_root / ORIGIN_FILE
    temporary = target.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(found, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    temporary.replace(target)
