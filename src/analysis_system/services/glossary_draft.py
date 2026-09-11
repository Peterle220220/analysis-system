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

import re
from collections.abc import Sequence
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from analysis_system.services.llm import LlmRequest
from analysis_system.services.relevance import fold

# Nhiều hơn thế này thì một lần gọi vừa dài vừa dễ bị cắt giữa chừng. Bảng rộng
# hơn thì soạn cho những cột đầu, và người dùng bổ sung phần còn lại.
MAX_COLUMNS: Final[int] = 120

# Nghĩa dài hơn thế này thì nó là một đoạn mô tả, không phải một cái tên.
MAX_MEANING: Final[int] = 90

PURPOSE: Final[str] = "glossary_draft"

# Từ đệm hai chữ ở đầu cách gọi, viết ở dạng đã bỏ dấu để so khớp.
FILLERS: Final[frozenset[str]] = frozenset({"toc do", "tinh trang", "muc do", "tan suat"})

# Phần trong ngoặc tròn hoặc vuông.
PARENTHESES: Final[re.Pattern[str]] = re.compile(r"\s*[(\[]([^)\]]*)[)\]]")

# Trong ngoặc chỉ có tới chừng này ký tự thì là một ký tự phân biệt, như "(A)",
# không phải một đơn vị như "(lần)" hay "(nhân dân tệ)".
QUALIFIER: Final[int] = 2


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
            "Ban dat TU KHOA TIM KIEM tieng Viet cho cac cot du lieu. Day KHONG "
            "phai bai dich cho hay: he thong doi chieu tung chu giua cau hoi va tu "
            "khoa, nen tu khoa phai la dung chu mot giam doc kinh doanh se GO khi "
            "hoi.\n\n"
            "# LUAT BAT BUOC\n"
            "1. Chep ten cot NGUYEN VEN vao truong 'column', ke ca khoang trang, "
            "dau ngoac va dau hoi. Sai mot ky tu la dong do bi bo.\n"
            "2. 'meaning' viet bang tieng Viet CO DAU DAY DU, du chu, khong viet "
            "tat. Viet 'nợ ngắn hạn', KHONG viet 'no ng' hay 'nợ ng'; viet 'tài "
            "sản', KHONG viet 'ts'.\n"
            "3. Ngan gon: ly tuong 2 den 4 chu, mot cum danh tu, khong phai cau "
            "giai thich. Vi du: 'tỷ lệ nợ', 'biên lợi nhuận gộp', 'tăng trưởng "
            "doanh thu', 'dòng tiền trên cổ phiếu'. DUNG NGHIA quan trong hon "
            "ngan: khong rut gon duoc ma van dung nghia thi cu viet dai hon.\n"
            "4. KHONG mo dau bang tu dem: 'tốc độ', 'tình trạng', 'mức độ', 'tần "
            "suất'. Viet 'tăng trưởng tổng tài sản', khong viet 'tốc độ tăng "
            "trưởng tổng tài sản'.\n"
            "5. KHONG don vi tinh, khong ngoac: bo '(lần)', '(%)', '(nhân dân tệ)'.\n"
            "6. Chu viet tat tieng Anh quen thuoc (ROE, EPS, EBIT) thi giu nguyen "
            "chu viet tat cung phan phan biet cua no, viet thuong, khong ngoac: "
            "'EPS(A) ...' thanh 'eps a', 'EPS(B) ...' thanh 'eps b'.\n"
            "7. Uu tien thuat ngu ngan cua nguoi lam kinh doanh: 'biên lợi nhuận "
            "gộp' thay vi 'tỷ suất lợi nhuận gộp hoạt động'.\n"
            "8. MOI COT MOT TU KHOA RIENG. Hai cot khong duoc trung tu khoa. Hai "
            "cot chi khac nhau o mot chi tiet (sau thue / truoc thue, A / B / C, "
            "ngan han / dai han) thi tu khoa PHAI giu chi tiet do.\n"
            "9. Cot nao ban khong chac nghia thi BO QUA - de trong con hon doan "
            "sai, vi mot tu khoa sai se lam he thong chon nham cot."
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
        meaning = tidy_meaning(str(entry.meaning))
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


def tidy_meaning(meaning: str) -> str:
    """Dọn một cách gọi model trả về — việc code làm được thì không giao model.

    Đo trên một bản nháp thật: 19/96 dòng mở đầu bằng từ đệm, 6 dòng có đơn vị
    trong ngoặc. Từ đệm làm hỏng đúng những cách gọi ngắn: "tình trạng phá sản"
    không khớp câu hỏi "công ty phá sản".

    - bỏ từ đệm hai chữ ở đầu: tốc độ, tình trạng, mức độ, tần suất
    - bỏ phần trong ngoặc nếu nó là đơn vị; một ký tự phân biệt như "(A)" thì
      giữ lại chữ bên trong, vì bỏ nó đi thì "roa (a)" và "roa (b)" trùng nhau
    """
    text = PARENTHESES.sub(_unwrap_or_drop, " ".join(str(meaning).split()))
    words = text.split()
    if len(words) > 2 and fold(" ".join(words[:2])) in FILLERS:
        words = words[2:]
    return " ".join(words).strip(" .;,")


def _unwrap_or_drop(found: re.Match[str]) -> str:
    inner = found.group(1).strip()
    return f" {inner}" if 0 < len(inner) <= QUALIFIER else ""


def duplicate_meanings(lines: str) -> list[str]:
    """Những chỗ hai cột trở lên có cùng một cách gọi — để người duyệt sửa.

    Không máy nào tự phân xử được hai cột trùng hệt cách gọi: hỏi bằng cách gọi
    đó thì cả hai cùng khớp. Đo trên một bản nháp thật có 2 cặp như vậy.
    """
    from analysis_system.services.asked_columns import ALTERNATIVES, parse_glossary

    by_term: dict[str, list[str]] = {}
    shown: dict[str, str] = {}
    for column, said in parse_glossary(lines).items():
        for term in ALTERNATIVES.split(said):
            key = fold(term)
            if key:
                by_term.setdefault(key, []).append(column.strip())
                shown.setdefault(key, term.strip())
    return [
        f"{' và '.join(columns)} cùng là «{shown[key]}»"
        for key, columns in by_term.items()
        if len(columns) > 1
    ]


def as_lines(table: dict[str, str]) -> str:
    """Bảng chú giải viết ra đúng dạng ô Bối cảnh đọc được."""
    return "\n".join(f"{column} = {meaning}" for column, meaning in sorted(table.items()))
