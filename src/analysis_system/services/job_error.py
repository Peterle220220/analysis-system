"""Việc chạy nền hỏng ở chỗ không ai đang nhìn — ghi lại để người quay lại còn thấy.

Làm sạch dữ liệu chạy nền, sau khi trình duyệt đã nhận trang. Nếu nó hỏng thì
không còn request nào để trả lỗi về: `raise` ở đó chỉ vào nhật ký máy chủ, nơi
người dùng không bao giờ đọc.

Trước đây việc này chạy **trong** request, và người dùng gặp đúng hậu quả ngược
lại: trình duyệt quay vòng vòng bốn phút rồi tự bỏ cuộc, trong khi máy chủ vẫn
làm việc — *"tôi không biết nó có đang chạy hay không"*.

Nên lỗi được ghi thành một tệp cạnh lần chạy. Người dùng quay lại trang thì thấy
nó, không phải một trang trống.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

ERROR_FILE: Final[str] = "loi.txt"

# Đủ để nói chuyện gì đã xảy ra. Dài hơn thì nó là một stack trace, và người
# dùng không đọc stack trace - bản đầy đủ vẫn ở nhật ký máy chủ.
MAX_LENGTH: Final[int] = 400


def write_error(run_dir: Path, message: str) -> None:
    """Ghi lại vì sao việc chạy nền hỏng."""
    run_dir.mkdir(parents=True, exist_ok=True)
    text = " ".join(str(message).split())[:MAX_LENGTH]
    (run_dir / ERROR_FILE).write_text(text, encoding="utf-8")


def read_error(run_dir: Path) -> str:
    """Lỗi đã ghi, hoặc rỗng."""
    path = run_dir / ERROR_FILE
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def clear_error(run_dir: Path) -> None:
    """Xoá lỗi cũ trước khi thử lại, để không ai đọc phải lỗi của lần trước."""
    path = run_dir / ERROR_FILE
    if path.is_file():
        path.unlink()
