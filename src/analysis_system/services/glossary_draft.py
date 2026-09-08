"""Bản nháp bảng chú giải cột — model đề xuất, code đối chiếu, người duyệt.

Câu hỏi tiếng Việt trên một bảng cột tiếng Anh không khớp được chữ nào. Bảng
chú giải trong ô Bối cảnh chữa đúng chỗ đó, nhưng nó phải **gõ tay** — và với
một bảng 96 cột thì không ai gõ. Không gõ thì hệ thống rơi về thứ tự bảng chữ
cái, đo tám cột không ai hỏi, rồi nói thật là chưa kết luận được: trung thực mà
vô dụng.

Nên model soạn nháp, **một lần cho mỗi bộ dữ liệu**. Đúng ba bước quen thuộc
của cả hệ thống này:

* **Model đề xuất** — nó đọc tên cột và đoán nghĩa tiếng Việt. Đây là việc nó
  làm tốt, và là loại việc không có cách nào tính ra bằng code.
* **Code đối chiếu** — mọi khoá phải là **một cột có thật** trong bảng. Một
  dòng trỏ tới cột không tồn tại bị bỏ, và số dòng bị bỏ được nói ra.
* **Người duyệt** — bản nháp đi vào ô Bối cảnh để đọc và sửa, **không tự lưu**.
  Chú giải sai thì người dùng thấy lúc duyệt, chứ không phải sau đó âm thầm
  làm lệch mọi câu trả lời.

Không dịch câu hỏi. Dịch sai thì không ai nhìn thấy, và cái sai ấy đi thẳng vào
việc chọn cột — đúng loại lỗi cả dự án này dựng lên để tránh.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from analysis_system.services.llm import LlmRequest

# Nhiều hơn thế này thì một lần gọi vừa dài vừa dễ bị cắt giữa chừng. Bảng rộng
# hơn thì soạn cho những cột đầu, và người dùng bổ sung phần còn lại.
MAX_COLUMNS: Final[int] = 120

# Nghĩa dài hơn thế này thì nó là một đoạn mô tả, không phải một cái tên.
MAX_MEANING: Final[int] = 90

PURPOSE: Final[str] = "glossary_draft"


class GlossaryEntry(BaseModel):
    """Một cột, và nghĩa của nó nói bằng tiếng Việt."""

    model_config = ConfigDict(extra="forbid")

    column: str
    meaning: str


class GlossaryProposal(BaseModel):
    """Bản nháp model trả về."""

    model_config = ConfigDict(extra="forbid")

    entries: list[GlossaryEntry] = Field(default_factory=list)


def build_request(columns: Sequence[str]) -> LlmRequest:
    """Hỏi model nghĩa tiếng Việt của từng tên cột.

    Chỉ đưa **tên cột**, không đưa một dòng dữ liệu nào: đặt tên cho một cột
    không cần nhìn giá trị của nó, và không nhìn thì không có gì để lộ.
    """
    wanted = [str(name) for name in columns][:MAX_COLUMNS]
    lines = "\n".join(f"- {name}" for name in wanted)
    return LlmRequest(
        purpose=PURPOSE,
        system=(
            "Ban dat ten tieng Viet cho cac cot du lieu, de nguoi dung hoi bang "
            "tieng Viet ma he thong van tim dung cot.\n\n"
            "# LUAT BAT BUOC\n"
            "1. Chep ten cot NGUYEN VEN vao truong 'column', ke ca khoang trang, "
            "dau ngoac va dau hoi. Sai mot ky tu la dong do bi bo.\n"
            "2. 'meaning' la cach NGUOI DUNG se goi cot do bang tieng Viet, ngan "
            "gon, co dau day du. Vi du: 'ty le no', 'toc do tang truong doanh thu'.\n"
            "3. KHONG giai thich, khong mo ta cach tinh, khong them don vi. Chi "
            "mot cum danh tu.\n"
            "4. Cot nao ban khong chac nghia thi BO QUA - de trong con hon doan "
            "sai, vi mot cai ten sai se lam he thong chon nham cot."
        ),
        prompt=f"Cac cot trong bang:\n{lines}",
        schema=GlossaryProposal,
    )


def verified(
    proposal: GlossaryProposal, columns: Sequence[str]
) -> tuple[dict[str, str], list[str]]:
    """Những dòng dùng được, và những gì bị bỏ.

    Args:
        proposal: bản nháp model trả về.
        columns: tên cột thật của bảng.

    Returns:
        (bảng chú giải, danh sách lý do bỏ). Mọi khoá trong bảng trả về đều là
        **một cột có thật** — đó là toàn bộ phần "code đối chiếu".
    """
    real = {" ".join(str(name).split()): str(name) for name in columns}
    table: dict[str, str] = {}
    dropped: list[str] = []

    for entry in proposal.entries:
        tidy = " ".join(str(entry.column).split())
        meaning = " ".join(str(entry.meaning).split())
        if tidy not in real:
            dropped.append(f"{entry.column!r}: khong co cot nao ten nhu the")
            continue
        if not meaning:
            dropped.append(f"{entry.column!r}: bo trong nghia")
            continue
        if len(meaning) > MAX_MEANING:
            dropped.append(
                f"{entry.column!r}: nghia dai {len(meaning)} ky tu, toi da {MAX_MEANING}"
            )
            continue
        table[real[tidy]] = meaning

    return table, dropped


def as_lines(table: dict[str, str]) -> str:
    """Bảng chú giải viết ra đúng dạng ô Bối cảnh đọc được."""
    return "\n".join(f"{column} = {meaning}" for column, meaning in sorted(table.items()))
