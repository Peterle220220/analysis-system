"""The single I/O gateway of the system.

Every read and write in the codebase goes through this module. Phase 1 wraps
these functions with a ScopeToken check; it does not replace them, and no other
module is allowed to touch the filesystem directly.

Writes are atomic: content lands in a temporary file inside the destination
directory and is renamed into place only once it is complete, so a process
killed mid-write never leaves a half-written artefact behind.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Final

import pandas as pd

_HASH_CHUNK_BYTES: Final[int] = 1 << 20


class StorageError(RuntimeError):
    """A read or write could not be completed."""


def _require_directory(path: Path) -> Path:
    """Return the parent directory of the target, or fail if it does not exist."""
    parent = path.parent
    if not parent.is_dir():
        raise StorageError(
            f"Thu muc dich khong ton tai: {parent}\n"
            "Storage khong tu tao thu muc - hay kiem tra config/settings.yaml."
        )
    return parent


def _apply_default_permissions(path: Path) -> None:
    """Give a temp file the permissions a normally created file would have.

    tempfile.mkstemp creates its file 0600 for security, and rename preserves
    that, so without this every artefact the pipeline writes would be readable
    only by the user who ran it.
    """
    umask = os.umask(0)
    os.umask(umask)
    path.chmod(0o666 & ~umask)


def _atomic_write(path: Path, writer: Callable[[Path], None]) -> Path:
    """Write via a temporary file in the same directory, then rename into place.

    Args:
        path: final destination.
        writer: callback that writes the full content to the path it is given.

    Returns:
        The destination path.

    Raises:
        StorageError: the destination directory does not exist.
    """
    parent = _require_directory(path)
    handle, temp_name = tempfile.mkstemp(dir=parent, prefix=f".{path.name}.", suffix=".tmp")
    os.close(handle)
    temp_path = Path(temp_name)
    try:
        writer(temp_path)
        _apply_default_permissions(temp_path)
        temp_path.replace(path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
    return path


def read_csv(
    path: Path,
    *,
    encoding: str = "utf-8",
    delimiter: str = ",",
    keep_all_as_text: bool = True,
) -> pd.DataFrame:
    """Read a CSV file.

    Args:
        path: file to read.
        encoding: character encoding of the file.
        delimiter: field separator.
        keep_all_as_text: read every column as text. Ingest keeps this on so no
            value is silently reinterpreted before the cleaning rules run.

    Returns:
        The parsed frame.

    Raises:
        StorageError: the file does not exist or cannot be parsed.
    """
    if not path.is_file():
        raise StorageError(f"Khong tim thay file CSV: {path}")
    try:
        return pd.read_csv(
            path,
            encoding=encoding,
            delimiter=delimiter,
            dtype=str if keep_all_as_text else None,
        )
    except (OSError, UnicodeDecodeError, pd.errors.ParserError) as exc:
        raise StorageError(f"Khong doc duoc CSV {path}: {exc}") from exc


def read_parquet(path: Path) -> pd.DataFrame:
    """Read a Parquet file.

    Raises:
        StorageError: the file does not exist or cannot be read.
    """
    if not path.is_file():
        raise StorageError(f"Khong tim thay file Parquet: {path}")
    try:
        return pd.read_parquet(path)
    except (OSError, ValueError) as exc:
        raise StorageError(f"Khong doc duoc Parquet {path}: {exc}") from exc


def write_parquet(frame: pd.DataFrame, path: Path) -> Path:
    """Write a frame to Parquet atomically, without the index.

    Returns:
        The destination path.
    """

    def _write(target: Path) -> None:
        frame.to_parquet(target, index=False)

    return _atomic_write(path, _write)


def write_text(text: str, path: Path, *, encoding: str = "utf-8") -> Path:
    """Write text atomically with Unix line endings.

    Line endings are pinned so identical content always produces identical bytes
    regardless of platform.

    Returns:
        The destination path.
    """

    def _write(target: Path) -> None:
        target.write_text(text, encoding=encoding, newline="\n")

    return _atomic_write(path, _write)


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 over the bytes of a file, read in chunks.

    Raises:
        StorageError: the file does not exist or cannot be read.
    """
    if not path.is_file():
        raise StorageError(f"Khong tim thay file de bam hash: {path}")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(_HASH_CHUNK_BYTES):
                digest.update(chunk)
    except OSError as exc:
        raise StorageError(f"Khong doc duoc file {path}: {exc}") from exc
    return digest.hexdigest()


def append_line(line: str, path: Path, *, encoding: str = "utf-8") -> Path:
    """Append one line to a file, creating the file if it does not exist.

    Append-only logs deliberately do not use the atomic rewrite path above:
    rewriting the whole file on every event would be slow and would turn each
    event into a chance to lose the history before it. A single small append
    under O_APPEND is atomic on POSIX, which is exactly what an audit log needs.

    Returns:
        The destination path.

    Raises:
        StorageError: the destination directory does not exist.
    """
    _require_directory(path)
    try:
        with path.open("a", encoding=encoding, newline="\n") as stream:
            stream.write(line.rstrip("\n") + "\n")
    except OSError as exc:
        raise StorageError(f"Khong ghi them duoc vao {path}: {exc}") from exc
    return path


def read_lines(path: Path, *, encoding: str = "utf-8") -> list[str]:
    """Read a text file as a list of lines with the line endings stripped.

    Raises:
        StorageError: the file does not exist or cannot be read.
    """
    if not path.is_file():
        raise StorageError(f"Khong tim thay file: {path}")
    try:
        return path.read_text(encoding=encoding).splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise StorageError(f"Khong doc duoc file {path}: {exc}") from exc


def read_text(path: Path, *, encoding: str = "utf-8") -> str:
    """Read a whole text file.

    Raises:
        StorageError: the file does not exist or cannot be read.
    """
    if not path.is_file():
        raise StorageError(f"Khong tim thay file: {path}")
    try:
        return path.read_text(encoding=encoding)
    except (OSError, UnicodeDecodeError) as exc:
        raise StorageError(f"Khong doc duoc file {path}: {exc}") from exc


def read_bytes(path: Path, *, limit: int | None = None) -> bytes:
    """Read raw bytes, optionally only the first *limit* of them.

    Detection has to happen before decoding, so this is the one read that
    returns bytes rather than a frame.

    Raises:
        StorageError: the file does not exist or cannot be read.
    """
    if not path.is_file():
        raise StorageError(f"Khong tim thay file: {path}")
    try:
        with path.open("rb") as stream:
            return stream.read() if limit is None else stream.read(limit)
    except OSError as exc:
        raise StorageError(f"Khong doc duoc file {path}: {exc}") from exc


def read_json(path: Path, *, encoding: str = "utf-8", lines: bool = False) -> pd.DataFrame:
    """Read a JSON or JSON Lines file into a frame.

    Raises:
        StorageError: the file does not exist or cannot be parsed.
    """
    if not path.is_file():
        raise StorageError(f"Khong tim thay file JSON: {path}")
    try:
        # dtype=False stops pandas inventing types of its own; the cast that
        # follows makes JSON arrive as text like every other source, so the
        # cleaning rules see the same thing whatever the file was.
        frame = pd.read_json(path, encoding=encoding, lines=lines, dtype=False)
    except (OSError, ValueError) as exc:
        raise StorageError(f"Khong doc duoc JSON {path}: {exc}") from exc
    return frame.astype("string")


def read_excel(path: Path, *, sheet: str | int = 0) -> pd.DataFrame:
    """Read one sheet of a workbook into a frame, every column as text.

    Raises:
        StorageError: the file does not exist, or openpyxl is not installed.
    """
    if not path.is_file():
        raise StorageError(f"Khong tim thay file Excel: {path}")
    try:
        return pd.read_excel(path, sheet_name=sheet, dtype=str)
    except ImportError as exc:  # pragma: no cover - depends on install
        raise StorageError("Chua cai openpyxl. Cai bang: pip install openpyxl") from exc
    except (OSError, ValueError) as exc:
        raise StorageError(f"Khong doc duoc Excel {path}: {exc}") from exc


def excel_sheets(path: Path) -> list[str]:
    """Names of every sheet in a workbook.

    Raises:
        StorageError: the workbook cannot be opened.
    """
    if not path.is_file():
        raise StorageError(f"Khong tim thay file Excel: {path}")
    try:
        with pd.ExcelFile(path) as book:
            return [str(name) for name in book.sheet_names]
    except (OSError, ValueError, ImportError) as exc:
        raise StorageError(f"Khong doc duoc danh sach sheet cua {path}: {exc}") from exc


def write_bytes(payload: bytes, path: Path) -> Path:
    """Write binary content atomically.

    Returns:
        The destination path.
    """

    def _write(target: Path) -> None:
        target.write_bytes(payload)

    return _atomic_write(path, _write)


def ensure_directory(path: Path) -> Path:
    """Create a directory and its parents.

    Used only for a directory inside a layer the caller already has permission
    to write to; the scope check happens before this is ever reached.
    """
    path.mkdir(parents=True, exist_ok=True)
    return path
