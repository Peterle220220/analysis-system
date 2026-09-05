"""Đặt tên cho người đọc, không phải cho máy.

`kt1__q4` nói đủ mọi thứ một chương trình cần: bộ dữ liệu nào, lượt hỏi thứ
mấy, và cách tìm lại nó trên đĩa. Nó **không nói gì** với người đang nhìn màn
hình, và đó là người mà giao diện này phục vụ.

Mã vẫn giữ nguyên ở mọi nơi máy dùng — trong đường dẫn tệp, trong lệnh, trong
nhật ký. Chỉ phần **hiển thị** là đổi.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

# Ngăn cách giữa lần làm sạch và lượt hỏi đặt trên nó: `emotions__q3`.
ROUND_MARK: Final[str] = "__q"


@dataclass(frozen=True)
class Named:
    """Một lần chạy, dưới hai cái tên."""

    run_id: str
    title: str
    subtitle: str = ""

    @property
    def is_question(self) -> bool:
        """True khi đây là một lượt hỏi chứ không phải lần làm sạch."""
        return ROUND_MARK in self.run_id


def describe(run_id: str, started: datetime | None = None, question: str = "") -> Named:
    """Tên để hiển thị cho một lần chạy.

    Lượt hỏi được gọi theo **câu hỏi của người dùng** nếu có — đó là thứ họ
    nhớ. Không có câu hỏi thì mới rơi về "lượt hỏi thứ mấy", vẫn hơn hẳn một
    mã như `kt1__q4`.
    """
    dataset, mark, round_no = run_id.partition(ROUND_MARK)
    when = _when(started)
    if not mark:
        return Named(run_id, f"Bộ dữ liệu: {dataset}", when)
    if question:
        short = question if len(question) <= 70 else question[:67] + "…"
        return Named(run_id, short, f"Hỏi trên {dataset}{' · ' + when if when else ''}")
    return Named(
        run_id, f"Lượt hỏi thứ {round_no}", f"Trên {dataset}{' · ' + when if when else ''}"
    )


def _when(moment: datetime | None) -> str:
    """Thời điểm, nói theo cách người ta nói.

    Một dấu thời gian đầy đủ đúng nhưng không giúp gì: cái người đọc muốn biết
    là *mới hay cũ*, và "hôm qua 14:32" trả lời điều đó ngay.
    """
    if moment is None:
        return ""
    now = datetime.now(UTC)
    days = (now.date() - moment.date()).days
    clock = moment.strftime("%H:%M")
    if days == 0:
        return f"hôm nay {clock}"
    if days == 1:
        return f"hôm qua {clock}"
    if days < 7:
        return f"{days} ngày trước, {clock}"
    return moment.strftime("%d/%m/%Y %H:%M")


# Tên các tầng dữ liệu, nói cho người dùng chứ không phải cho lập trình viên.
LAYER_NAMES: Final[dict[str, str]] = {
    "staging": "Bảng thô vừa đọc vào",
    "clean": "Dữ liệu sạch",
    "mart": "Bảng để phân tích",
    "profile": "Hồ sơ mô tả dữ liệu",
    "validation": "Kết quả chấm dữ liệu",
    "artifacts": "Kết luận, biểu đồ, báo cáo",
    "extracted": "Văn bản trích từ tài liệu",
}

# Trạng thái, nói cho người dùng.
PHASES: Final[dict[str, str]] = {
    "COMPLETED": "Xong",
    "PAUSED_AWAITING_APPROVAL": "Đang chờ bạn duyệt",
    "HALTED": "Dừng giữa chừng",
    "RUNNING": "Đang chạy",
    "FAILED": "Lỗi",
}


def phase_of(phase: str) -> str:
    """Trạng thái một lần chạy, bằng tiếng Việt."""
    return PHASES.get(phase, phase)
