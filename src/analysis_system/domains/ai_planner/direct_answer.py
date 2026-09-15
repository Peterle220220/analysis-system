"""Câu trả lời thẳng, đứng trước mọi bằng chứng.

Chủ hệ thống đọc một câu trả lời và viết: *"tôi cảm giác như hệ thống đang hành
xử giống một cỗ máy in báo cáo thống kê hơn là một chuyên gia phân tích"*. Đúng,
và chẩn đoán đi kèm cũng đúng: các lớp chống bịa số đã ép Manager làm việc **từ
dưới lên** — dịch từng phép đo thành một gạch đầu dòng rời rạc, rồi dừng. Không
bước nào ngoảnh lại hỏi *"những con số này đã trả lời câu hỏi chưa"*.

Hỏi *"poutcome hay campaign ảnh hưởng mạnh hơn"*, người ta chờ nghe **"poutcome
mạnh hơn"**. Ba đoạn số liệu đúng mà không có câu đó thì người đọc phải tự làm
nốt việc mà hệ thống đáng lẽ làm hộ.

Nên có một chỗ để nói câu đó, và chỗ đó phải **nới về câu chữ mà không nới về
số**:

* **Không bắt dẫn metric key.** Một câu chốt như *"poutcome ảnh hưởng mạnh hơn
  campaign"* không có con số nào để dẫn, và ép nó dẫn là ép nó nói vòng.
* **Vẫn cấm gõ số trực tiếp.** Đây là chỗ được đọc nhiều nhất trang, nên nó là
  chỗ tệ nhất để một con số bịa lọt qua. Muốn có số thì viết `{ten_chi_so}` như
  mọi chỗ khác, và code chèn giá trị thật vào.

Đó là toàn bộ sự nới lỏng, và nó nới đúng thứ đang trói: **cách diễn đạt**, chứ
không phải **quyền khẳng định một con số**.

Câu chốt hỏng thì bị bỏ, không làm hỏng cả câu trả lời. Mất một câu tóm tắt thì
người đọc vẫn còn đủ bằng chứng bên dưới; mất cả câu trả lời thì không còn gì.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Final

from analysis_system.domains.ai_planner.findings import (
    BARE_DIGIT,
    NAME_PLACEHOLDER,
    PLACEHOLDER,
    strip_known_labels,
)

if TYPE_CHECKING:  # pragma: no cover - chỉ dùng cho kiểu
    from analysis_system.models.agents import MetricValue

# Dài hơn thế này thì nó không còn là một câu chốt, nó là một đoạn nữa — và cả
# vấn đề ở đây là người đọc có một câu để đọc trước khi đọc mọi thứ.
MAX_LENGTH: Final[int] = 400

# Mọi lý do từ chối câu chốt đều mở đầu bằng cụm này, nên chúng nhặt lại được
# từ danh sách `rejected` chung với các luận điểm bị loại.
#
# Cần nhặt lại vì chuyện sau đã xảy ra thật: model viết đúng câu chốt cần viết,
# gõ thẳng một con số vào đó, và code bỏ **cả câu**. Chỗ được đọc nhiều nhất
# trang trở nên trống trơn — không câu trả lời, cũng không một chữ nói vì sao.
# Người đọc kết luận là hệ thống né câu hỏi.
MARK: Final[str] = "cau chot"

# Lý do máy ghi, dịch sang câu người đọc hiểu được. Đây là chỗ nói với người
# dùng, nên nó nói bằng tiếng người.
PLAINLY: Final[dict[str, str]] = {
    "con so go truc tiep": (
        "Máy đã viết một câu trả lời thẳng, nhưng trong đó có một con số gõ tay "
        "thay vì lấy từ phép đo, nên hệ thống không hiển thị câu đó. Mọi con số "
        "trên trang này đều phải truy ngược được về một phép đo có thật."
    ),
    "dan chi so khong co that": (
        "Máy đã viết một câu trả lời thẳng, nhưng nó dẫn một chỉ số không có "
        "trong lượt đo này, nên hệ thống không hiển thị câu đó."
    ),
    "dai": (
        "Máy đã viết một câu trả lời thẳng, nhưng nó dài quá mức một câu chốt "
        "nên hệ thống không hiển thị."
    ),
}


def refusals(rejected: Iterable[str]) -> list[str]:
    """Những dòng nói về câu chốt, tách khỏi các luận điểm bị loại."""
    return [line for line in (str(item) for item in rejected) if line.startswith(MARK)]


def plainly(reason: str) -> str:
    """Một lý do máy ghi, nói lại bằng tiếng người."""
    for fragment, said in PLAINLY.items():
        if fragment in reason:
            return said
    return (
        "Máy đã viết một câu trả lời thẳng nhưng hệ thống không nhận, nên câu "
        "đó không được hiển thị."
    )


# Khong co cau chot, va cung khong co ly do tu choi nao de noi.
NO_SUMMARY: Final[str] = "Hệ thống không chốt được một câu trả lời trực tiếp cho câu hỏi này."


def why_no_summary(rejected: Iterable[str]) -> str:
    """Vì sao không có câu trả lời thẳng, nói bằng tiếng người.

    Chỉ nhặt lý do từ chối CÂU CHỐT. Một luận điểm bị loại không phải lý do
    vắng câu trả lời thẳng, và lấy nó ra nói là đổ lỗi nhầm chỗ.
    """
    refused = refusals(rejected)
    return plainly(refused[0]) if refused else NO_SUMMARY


def problems_with(summary: str, metrics: Mapping[str, MetricValue]) -> list[str]:
    """Mọi thứ sai với câu chốt này.

    Returns:
        Danh sách vấn đề. Rỗng nghĩa là dùng được.
    """
    text = str(summary).strip()
    if not text:
        return ["cau chot rong"]
    if len(text) > MAX_LENGTH:
        return [f"cau chot dai {len(text)} ky tu, toi da {MAX_LENGTH}"]

    problems: list[str] = []
    bare = PLACEHOLDER.sub("", NAME_PLACEHOLDER.sub("", text))
    if BARE_DIGIT.search(strip_known_labels(bare, metrics)):
        # Cung mot luat nhu moi luan diem khac, va co y giu nguyen: day la cho
        # duoc doc nhieu nhat trang, nen la cho te nhat de mot con so bia lot.
        problems.append("cau chot co con so go truc tiep - moi so phai la placeholder {ten_chi_so}")
    for match in PLACEHOLDER.finditer(text):
        if match.group(1) not in metrics:
            problems.append(f"cau chot dan chi so khong co that: {match.group(1)}")
    return problems


def usable(summary: str, metrics: Mapping[str, MetricValue]) -> bool:
    """Câu chốt này có dùng được không."""
    return not problems_with(summary, metrics)


def misses_the_number(question: str, rendered: str) -> str:
    """Câu hỏi đòi một con số mà câu chốt không có con số nào.

    Chủ hệ thống phải nói lại hai lần: *"câu trả lời của hệ thống trước tiên và
    kiên quyết phải giải đáp được câu hỏi của user"*. Hỏi *"có bao nhiêu công ty
    phá sản và bao nhiêu công ty không"*, câu chốt nói về tỷ lệ rồi hẹn số liệu
    ở dưới — tức là trả lời một câu khác.

    Một luật trong prompt là chưa đủ. Dự án này đã đo: prompt ghi *"tuyệt đối
    không gõ số trực tiếp"* và model vẫn gõ, năm lần trong bốn lượt chạy. Nên
    chỗ nào bảo được bằng code thì kiểm bằng code.

    Args:
        question: câu người dùng hỏi.
        rendered: câu chốt **sau khi** code đã chèn giá trị vào placeholder.

    Returns:
        Câu cảnh báo, hoặc rỗng. Đây là báo cho người đọc — không xoá câu chốt,
        vì một câu chốt thiếu số vẫn hơn không có câu chốt nào.
    """
    from analysis_system.domains.ai_planner.answer_shape import Demand
    from analysis_system.domains.ai_planner.question_parts import demands

    said = str(rendered).strip()
    # Xet TUNG Y, khong xet ca cau. `read_question` lay loai dau tien khop roi
    # dung, nen "Nhom nao cao nhat? Co bao nhieu?" ra "xep hang" va y hoi so
    # luong khong bao gio duoc xet.
    if not said or Demand.QUANTITY.value not in demands(question):
        return ""
    if any(character.isdigit() for character in said):
        return ""
    return (
        "Câu hỏi đòi một con số, nhưng câu trả lời thẳng ở trên không có con số "
        "nào, hãy đọc các kết luận bên dưới để lấy con số cần tìm."
    )
