"""Xoá hẳn một bộ dữ liệu: tệp gốc, bảng sạch, lượt hỏi, và mọi tệp mang tên nó.

Người dùng tải lên một tệp hỏng thì phải tự bỏ được nó, không phải nhờ người vào
máy chủ xoá tay.

`retention.belongings` khớp theo tiền tố "ten_*". Đủ cho một lượt hỏi, không đủ
cho cả một bộ, vì hai lẽ:

* Bộ "don_hang" và bộ "don_hang_quy_3" chung tiền tố "don_hang_": xoá bộ ngắn sẽ
  cuốn theo tệp của bộ dài.
* Bảng sạch tên là "clean/ten.parquet", không có dấu "_", nên không ai thấy nó.

Nên ở đây mỗi tệp thuộc về bộ có tên DÀI NHẤT khớp với nó, và chỉ tệp của đúng bộ
đang xoá mới đi. Tên bộ lấy từ thư mục runs, tệp gốc, bảng sạch và sổ nguồn, để
một bộ đã mất thư mục chạy vẫn giữ được tệp của mình.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterable
from pathlib import Path
from typing import Final

from analysis_system.core.retention import DERIVED_MARK, WORKING_LAYERS
from analysis_system.core.settings import Settings
from analysis_system.services.dataset_labels import forget_label, read_labels
from analysis_system.services.dataset_origin import forget_origin, read_origins

# retention khong bao gio dung toi raw (tep nguoi dung dua); xoa ca bo thi co.
FILE_LAYERS: Final[tuple[str, ...]] = ("raw", *WORKING_LAYERS)


def _root(settings: Settings, layer: str) -> Path | None:
    value = getattr(settings.layers, layer, None)
    root = Path(value) if value else None
    return root if root is not None and root.is_dir() else None


def _check(dataset: str) -> None:
    # Ten rong thi "khong thuoc bo nao" cung la "thuoc bo nay": xoa sach moi thu.
    if not dataset or DERIVED_MARK in dataset or "/" in dataset or dataset.startswith("."):
        raise ValueError(f"{dataset!r} khong phai ten mot bo du lieu.")


def known_datasets(settings: Settings) -> set[str]:
    """Mọi tên bộ dữ liệu hệ thống còn thấy dấu vết."""
    names: set[str] = set()
    runs_root = _root(settings, "runs")
    if runs_root is not None:
        names.update(
            path.name.split(DERIVED_MARK, 1)[0] for path in runs_root.iterdir() if path.is_dir()
        )
        names.update(read_origins(runs_root))
        names.update(read_labels(runs_root))
    for layer in ("raw", "clean"):
        root = _root(settings, layer)
        if root is not None:
            names.update(path.name.split(".", 1)[0] for path in root.iterdir() if path.is_file())
    names.discard("")
    return names


def owner(name: str, known: Iterable[str]) -> str:
    """Bộ có tên dài nhất mà tên tệp (hay thư mục) này mang; rỗng khi không bộ nào."""
    best = ""
    for dataset in known:
        if len(dataset) <= len(best):
            continue
        if name == dataset or name.startswith((f"{dataset}_", f"{dataset}.")):
            best = dataset
    return best


def _owner_of(relative: Path, known: set[str]) -> str:
    # Ten tep truoc, roi toi thu muc chua no gan nhat: "report/bo__q1.html" la cua
    # "bo", ke ca khi co mot bo ten "report".
    for part in reversed(relative.parts):
        found = owner(part, known)
        if found:
            return found
    return ""


def runs_of(settings: Settings, dataset: str) -> list[str]:
    """Thư mục chạy của bộ: chính nó và mọi lượt hỏi của nó.

    Raises:
        ValueError: tên không phải tên một bộ dữ liệu.
    """
    _check(dataset)
    runs_root = _root(settings, "runs")
    if runs_root is None:
        return []
    known = known_datasets(settings) | {dataset}
    return sorted(
        path.name
        for path in runs_root.iterdir()
        if path.is_dir() and owner(path.name, known) == dataset
    )


def belongings(settings: Settings, dataset: str) -> list[Path]:
    """Mọi đường dẫn tồn tại vì bộ này, và không của bộ nào khác.

    Raises:
        ValueError: tên không phải tên một bộ dữ liệu.
    """
    _check(dataset)
    known = known_datasets(settings) | {dataset}
    runs_root = _root(settings, "runs")
    found = [runs_root / name for name in runs_of(settings, dataset)] if runs_root else []
    for layer in FILE_LAYERS:
        root = _root(settings, layer)
        if root is None:
            continue
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root)
            # Thu muc an (so yeu cau .api_requests...) la cua he thong, khong cua bo nao.
            if not path.is_file() or any(part.startswith(".") for part in relative.parts):
                continue
            if _owner_of(relative, known) == dataset:
                found.append(path)
    return found


def forget(settings: Settings, dataset: str) -> tuple[int, int]:
    """Xoá mọi thứ của bộ này và bỏ nó khỏi sổ nguồn.

    Returns:
        Số đường dẫn đã xoá, và số byte giải phóng.

    Raises:
        ValueError: tên không phải tên một bộ dữ liệu.
        OSError: một đường dẫn không xoá được. Không nuốt lỗi: bộ đã báo là mất
            thì phải mất thật.
    """
    removed = 0
    freed = 0
    for path in belongings(settings, dataset):
        if path.is_dir():
            freed += sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
            shutil.rmtree(path)
        else:
            freed += path.stat().st_size
            path.unlink()
        removed += 1
    runs_root = _root(settings, "runs")
    if runs_root is not None:
        forget_origin(runs_root, dataset)
        forget_label(runs_root, dataset)
    return removed, freed
