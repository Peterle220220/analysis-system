"""Câu hỏi nhắc tới cột nào, và cả câu trả lời có đụng tới cột đó không.

Lỗi thật: hỏi *"mục tiêu tiết kiệm của họ là gì"*, hệ thống trả lời bằng cột
`PPF`. Con số có thật, dẫn nguồn được, vượt mọi lớp chặn đang có — nhưng cột
đúng là `Objective`. Không lớp nào bắt được, vì mọi lớp đều hỏi *"con số này có
thật không"*, không lớp nào hỏi *"cột này có phải thứ người ta hỏi không"*.

**Đã đo `SemanticScorer` trước khi xây, và không dùng nó.** 4/6: đúng ca đã gây
lỗi (`Objective` 0.39 thắng `PPF` 0.26) nhưng sai hai ca một cách tự tin —
`Invest_Monitor` được 0.59 cho *"kênh thông tin"*, cao hơn mọi ca đúng, trong khi
cột đúng là `Source`. Dựng lớp chặn trên nền đó thì ném oan khoảng một phần ba
kết luận đúng, đúng cái bẫy dự án này đã dính một lần khi chấm văn bản bỏ dấu.

Nên chỗ này **không đoán gì cả**. Nó chỉ đối chiếu với hai thứ có thật:

* **Tên cột người dùng tự gõ trong câu hỏi.** Chủ hệ thống vốn viết sẵn kiểu
  *"tần suất theo dõi danh mục (Invest_Monitor)"* — cột được gọi tên, đúng
  nguyên văn, không có gì để suy diễn.
* **Bảng chú giải người dùng tự viết** trong ô Bối cảnh: `Objective = mục tiêu
  tiết kiệm`. Một dòng, gõ một lần cho mỗi bộ dữ liệu, và từ đó câu hỏi tiếng
  Việt cũng gọi được tên cột.

Hai đường, một cơ chế: chú giải chỉ mở rộng vốn từ, còn phép đối chiếu y hệt.

Và nó hỏi ở mức **cả câu trả lời**, không phải từng kết luận. Bản đầu tiên hỏi
từng kết luận một, và đo trên lượt chạy thật thì nó nổ 3 trên 4 — toàn oan. Câu
hỏi đó có hai vế, và ba kết luận kia đang trả lời vế thứ nhất một cách đàng
hoàng. Một cột được hỏi mà **không kết luận nào** đụng tới thì mới là chuyện
đáng nói, và đó đúng là hình dạng của lỗi gốc: cả câu trả lời không hề chạm vào
`Objective`.

Kết quả là **cảnh báo, không phải lớp chặn** — không có đường nào từ đây dẫn tới
việc vứt một kết luận đi.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Final

from analysis_system.services.relevance import fold

# Người dùng gõ `Ten_Cot = nghĩa`. Chỉ nhận dấu `=`: dấu hai chấm xuất hiện đầy
# trong văn xuôi bình thường, nên nhận nó là tự rước dòng rác vào bảng.
GLOSSARY_LINE: Final[re.Pattern[str]] = re.compile(
    r"^\s*([0-9A-Za-z_]{1,60})\s*=\s*(.+?)\s*$",
)

# Tên cột ngắn hơn thế này thì **không đối chiếu nguyên văn** với câu hỏi, chỉ
# đi qua chú giải. Bộ dữ liệu tiếp thị ngân hàng có cột tên đúng một chữ: `y`.
# Tìm chữ "y" đứng riêng trong một câu tiếng Việt thì bắt trúng "đồng ý" ngay
# câu đầu tiên — đã thử và đúng là nó bắt trúng. Một cái tên một chữ không đủ
# đặc trưng để nhận ra giữa văn xuôi, nhưng nghĩa của nó thì đủ.
MIN_LITERAL: Final[int] = 2

# Cụm chú giải ngắn quá thì khớp bừa vào giữa chữ khác. Bốn ký tự là chỗ "thu"
# hay "tuổi" còn qua được, còn "a" hay "kỳ" thì không.
MIN_PHRASE: Final[int] = 4

# Bao nhiêu chữ LIỀN NHAU của chú giải phải xuất hiện trong câu hỏi thì tính là
# gọi tên.
#
# Bản đầu đòi **cả** câu chú giải nằm trong câu hỏi, và điều đó chỉ chạy với
# chú giải ngắn kiểu `Source = kênh thông tin`. Người dùng thật viết
# `duration = Thời lượng cuộc gọi cuối cùng (tính bằng giây).` — không câu hỏi
# nào chứa nổi cả câu đó, nên cả bảng chú giải thành vô dụng mà không báo gì.
#
# Đo trên chính đoạn bối cảnh người dùng viết, sáu câu hỏi:
#
#     2 chữ   nhận đúng 6, sót 0, NHẬN NHẦM 4
#     3 chữ   nhận đúng 5, sót 1, NHẬN NHẦM 1
#     4 chữ   nhận đúng 5, sót 1, NHẬN NHẦM 0
#
# Bốn: cùng số nhận đúng như ba, mà không nhầm cái nào. Hai thì *"độ tuổi trung
# bình của khách hàng"* khớp nhầm cả `job` lẫn `y`, chỉ vì cả hai chú giải đều
# tả "khách hàng". Cái sót lại là một câu không nói gì — và im lặng là hướng an
# toàn cho một cơ chế chỉ cảnh báo.
WINDOW: Final[int] = 4

# Đoạn `.by.` trong metric key: `PPF.mean.by.gender.Female` — cột dùng để chia
# nhóm nằm ngay sau nó.
BY: Final[str] = "by"


def columns_in(metric_keys: Iterable[str]) -> frozenset[str]:
    """Những cột nằm sau các metric key này.

    Metric key được ghép từ tên cột và giá trị nhóm — `PPF.mean.by.gender.Female`
    — nên cột là đoạn đầu, cộng với đoạn đứng ngay sau `by`.
    """
    found: set[str] = set()
    for key in metric_keys:
        parts = [part for part in str(key).split(".") if part]
        if not parts:
            continue
        found.add(parts[0])
        for index, part in enumerate(parts[:-1]):
            if part == BY:
                found.add(parts[index + 1])
    return frozenset(found)


def parse_glossary(context: str) -> dict[str, str]:
    """Bảng chú giải người dùng viết trong ô Bối cảnh.

    Mỗi dòng `Ten_Cot = nghĩa`. Dòng nào không có dạng đó thì bỏ qua — ô Bối
    cảnh vẫn là chỗ viết văn xuôi tự do, chú giải chỉ là thứ đi kèm.
    """
    table: dict[str, str] = {}
    for line in str(context).splitlines():
        matched = GLOSSARY_LINE.match(line)
        if matched is None:
            continue
        column, meaning = matched.group(1), matched.group(2).strip()
        if meaning:
            table[column] = meaning
    return table


def _mentions_word(haystack_folded: str, word: str) -> bool:
    """Tên cột xuất hiện nguyên vẹn, không nằm lọt trong chữ khác.

    Cột `age` phải không khớp vào giữa "average" hay "percentage" — dữ liệu này
    có cột tên đúng ba chữ cái, nên chuyện đó không phải giả định.
    """
    pattern = rf"(?<![0-9a-z_]){re.escape(fold(word))}(?![0-9a-z_])"
    return re.search(pattern, haystack_folded) is not None


def named_by(
    question: str,
    columns: Iterable[str],
    glossary: Mapping[str, str] | None = None,
) -> frozenset[str]:
    """Những cột mà câu hỏi gọi tên — thẳng, hoặc qua chú giải."""
    folded = fold(question)
    table = glossary or {}
    named: set[str] = set()
    for column in columns:
        if len(column) >= MIN_LITERAL and _mentions_word(folded, column):
            named.add(column)
            continue
        if _meaning_appears(folded, table.get(column, "")):
            named.add(column)
    return frozenset(named)


def _meaning_appears(folded_question: str, meaning: str) -> bool:
    """Câu hỏi có nhắc tới thứ chú giải này mô tả không.

    Khớp trên một dải **liền nhau** `WINDOW` chữ của chú giải, không đòi cả
    câu: người ta mô tả một cột bằng một câu, rồi hỏi về nó bằng vài chữ.
    """
    words = fold(meaning).split()
    if not words or len("".join(words)) < MIN_PHRASE:
        return False
    if len(words) <= WINDOW:
        return " ".join(words) in folded_question
    return any(
        " ".join(words[at : at + WINDOW]) in folded_question
        for at in range(len(words) - WINDOW + 1)
    )


def untouched(
    question: str,
    claim_keys: Iterable[Iterable[str]],
    all_keys: Iterable[str],
    context: str = "",
) -> str:
    """Cột được hỏi tên mà không kết luận nào trong câu trả lời đụng tới.

    Args:
        question: câu người dùng hỏi.
        claim_keys: metric key của **từng** kết luận trong câu trả lời.
        all_keys: mọi metric key có trong lượt chạy, để biết bộ dữ liệu có cột gì.
        context: ô Bối cảnh, nơi bảng chú giải có thể nằm.

    Returns:
        Câu cảnh báo, hoặc rỗng. Im lặng là mặc định: mọi điều kiện phải cùng
        đúng thì mới lên tiếng.
    """
    used: set[str] = set()
    for keys in claim_keys:
        used |= columns_in(keys)
    if not used:
        # Chưa có kết luận nào, hoặc không kết luận nào dẫn metric. Không có gì
        # để đối chiếu, và đã có lớp khác lo chuyện câu trả lời rỗng.
        return ""

    glossary = parse_glossary(context)
    known = columns_in(all_keys) | frozenset(glossary)
    asked = named_by(question, known, glossary)
    missing = asked - used
    if not missing:
        # Câu hỏi không gọi tên cột nào, hoặc câu trả lời đã đụng tới hết. Đây
        # là trường hợp thường gặp, và im lặng ở đây chính là lý do cảnh báo
        # còn đáng tin khi nó nổ.
        return ""

    return (
        f"Câu hỏi có nhắc tới {_listed(missing)}, nhưng không kết luận nào dưới "
        f"đây dựa trên {'cột đó' if len(missing) == 1 else 'các cột đó'} — phần "
        f"này của câu hỏi có thể chưa được trả lời."
    )


def _listed(columns: Iterable[str]) -> str:
    ordered = sorted(columns)
    if len(ordered) == 1:
        return f"cột {ordered[0]}"
    return "các cột " + ", ".join(ordered)
