"""Bối cảnh của một bộ dữ liệu — do người biết dữ liệu viết ra, không do máy đoán.

Đề xuất ban đầu là để Planner **đoán** lĩnh vực từ từ khoá rồi gán vai "bạn là
chuyên gia $DOMAIN". Bị bác, và bác đúng: đó là một nhãn mà **code không đối
chiếu được với gì cả**, trong khi cả hệ thống này được dựng trên đúng một luật -
mọi thứ model quyết đều phải kiểm lại được. Thứ hạng đối chiếu với dữ liệu. Bộ
lọc đối chiếu với số dòng. Con số đối chiếu với metric key. `$DOMAIN` đối chiếu
với không gì.

Và đoán sai thì tệ hơn không đoán. Hệ thống này đã có tiền án đúng kiểu ánh xạ
khái niệm sai - lấy cột `PPF` để trả lời về "mục tiêu tiết kiệm", nghe rất hợp lý
và sai. Một tệp nhân sự có cột `Treatment` bị đoán thành lĩnh vực y tế, rồi model
nói về dữ liệu lương bằng giọng bác sĩ: sai mà nghe có thẩm quyền là kiểu sai đắt
nhất.

Nên bối cảnh đến từ **người dùng**, gõ một lần cho mỗi bộ dữ liệu. Đó là sự thật,
không phải suy đoán - và nó tiện thể chữa luôn chuyện tên cột khó hiểu: người
biết `Duration` nghĩa là gì chính là người tải tệp lên.

Để trống cũng không sao. Không có bối cảnh thì hệ thống vẫn chạy y như trước;
tên cột và câu hỏi vẫn đã nói khá nhiều về lĩnh vực rồi.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

CONTEXT_FILE: Final[str] = "boi_canh.txt"

# Đủ cho vài câu mô tả. Dài hơn thì nó thành một tài liệu, và một tài liệu dán
# vào mọi prompt là một cách đốt ngân sách token mà không ai để ý.
MAX_LENGTH: Final[int] = 2_000


def read_context(run_dir: Path) -> str:
    """Bối cảnh người dùng đã ghi cho bộ dữ liệu này, hoặc rỗng."""
    path = run_dir / CONTEXT_FILE
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        # Đọc không được thì coi như chưa có. Bối cảnh là thứ giúp thêm, không
        # phải thứ mà thiếu nó là hỏng.
        return ""


def write_context(run_dir: Path, text: str) -> str:
    """Ghi bối cảnh, cắt bớt nếu quá dài.

    Returns:
        Phần thật sự được ghi, để người gọi hiện lại đúng thứ đã lưu.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    # Giữ nguyên xuống dòng. Trước đây chỗ này gộp cả ô thành **một dòng**, và
    # bảng chú giải thì đọc theo từng dòng - nên người dùng khai đủ sáu cột
    # theo đúng mẫu trang hướng dẫn, và hệ thống đọc ra con số không.
    #
    # Hỏng mà im lặng: ô Bối cảnh vẫn hiện lại đúng chữ họ gõ (trình duyệt tự
    # xuống dòng theo bề ngang), nên không có gì trông sai cả.
    lines = [" ".join(line.split()) for line in str(text).splitlines()]
    kept = "\n".join(line for line in lines if line)[:MAX_LENGTH]
    (run_dir / CONTEXT_FILE).write_text(kept, encoding="utf-8")
    return kept
