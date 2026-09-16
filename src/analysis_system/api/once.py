"""Một thao tác gửi hai lần vẫn chỉ chạy một lần.

Mạng chập chờn thì trình duyệt gửi lại; người dùng sốt ruột thì bấm lại. Cả hai lần đều
mang cùng một mã do trình duyệt sinh ra, nên lần sau nhận lại đúng câu trả lời của lần
đầu thay vì chạy thêm một lần tải lên, một lần duyệt, hay một lần hỏi model.

Dấu vết nằm trên đĩa chứ không trong bộ nhớ: máy chủ khởi động lại giữa chừng thì lần gửi
lại vẫn phải nhận ra là trùng.
"""

from __future__ import annotations

import json
import re
import time
from contextlib import suppress
from pathlib import Path
from typing import Any, Final

REQUEST_KEY: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
# Qua han nay thi coi nhu lan truoc da chet giua chung, va lan gui lai duoc chay that.
REQUEST_STALE_SECONDS: Final[int] = 3600
FOLDER: Final[str] = ".api_requests"


def key_of(raw: Any) -> str:
    """Mã request trình duyệt gửi, hoặc rỗng khi nó không đúng dạng."""
    value = str(raw or "").strip()
    return value if REQUEST_KEY.fullmatch(value) else ""


def is_malformed(raw: Any) -> bool:
    """Có gửi mã nhưng mã sai dạng: từ chối, vì nhận bừa là mất cơ chế chống trùng."""
    return bool(str(raw or "").strip()) and not key_of(raw)


def claim(
    artifacts: Path, operation: str, key: str
) -> tuple[Path | None, dict[str, Any] | None, bool]:
    """Giữ chỗ cho một thao tác.

    Returns:
        (dấu vết để ghi kết quả, câu trả lời đã lưu của lần trước, lần trước còn đang chạy).
    """
    if not key:
        return None, None, False
    root = artifacts / FOLDER
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{operation}_{key}.json"
    try:
        path.open("x", encoding="utf-8").close()
    except FileExistsError:
        try:
            if time.time() - path.stat().st_mtime > REQUEST_STALE_SECONDS:
                path.unlink()
                path.open("x", encoding="utf-8").close()
            else:
                stored = json.loads(path.read_text(encoding="utf-8"))
                if stored.get("status") == "done" and isinstance(stored.get("payload"), dict):
                    return None, stored["payload"], False
                return None, None, True
        except (OSError, ValueError, FileExistsError):
            return None, None, True
    path.write_text(json.dumps({"status": "processing"}), encoding="utf-8")
    return path, None, False


def finish(path: Path | None, payload: dict[str, Any]) -> None:
    """Ghi lại câu trả lời, để lần gửi lại nhận đúng nó."""
    if path is None:
        return
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"status": "done", "payload": payload}, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def release(path: Path | None) -> None:
    """Bỏ chỗ đã giữ khi thao tác hỏng, để người dùng thử lại được."""
    if path is None:
        return
    with suppress(FileNotFoundError):
        path.unlink()
