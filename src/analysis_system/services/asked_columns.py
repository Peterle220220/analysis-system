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
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final

from analysis_system.services.relevance import fold

# Người dùng gõ `Ten_Cot = nghĩa`. Chỉ nhận dấu `=`: dấu hai chấm xuất hiện đầy
# trong văn xuôi bình thường, nên nhận nó là tự rước dòng rác vào bảng.
#
# Vế trái nhận **mọi ký tự trừ dấu bằng**. Bản đầu chỉ nhận chữ, số và gạch
# dưới, nên `Total Asset Growth Rate = tốc độ tăng trưởng` không đọc được — mà
# hầu hết tên cột thật đều có dấu cách, ngoặc, hoặc dấu phần trăm.
#
# Rộng ra thì một dòng văn xuôi có dấu bằng cũng lọt vào bảng. Không sao: chỉ
# những khoá **khớp một cột có thật** mới được dùng tới, nên một dòng rác chỉ
# nằm đó chứ không trỏ tới đâu.
GLOSSARY_LINE: Final[re.Pattern[str]] = re.compile(
    r"^\s*([^=]{1,80}?)\s*=\s*(.+?)\s*$",
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

# Nhiều cách gọi cho một cột, trên cùng một dòng: tách ở dấu chấm phẩy, hoặc ở
# dấu gạch chéo CÓ dấu cách hai bên. Chủ hệ thống tự viết đúng kiểu đó:
# `tỷ suất lợi nhuận gộp / biên lợi nhuận gộp = Operating Gross Margin`.
#
# Gạch chéo dính chữ thì KHÔNG tách: tên cột như `Net worth/Assets` tự có nó,
# và chú giải như `Kết quả (yes/no)` cũng vậy. Dấu phẩy cũng không tách — một
# nghĩa dài hay có dấu phẩy ở giữa, như `(success, failure, nonexistent)`.
ALTERNATIVES: Final[re.Pattern[str]] = re.compile(r"\s*;\s*|\s+/\s+")

# Cau hoi GOC cua nguoi dung, gan vao moi buoc cua ke hoach. Chi dung de chon
# cot uu tien; KHONG thay loi dan rieng cua tung buoc.
ASKED_PARAM: Final[str] = "cau_hoi_goc"

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
    """Bảng chú giải người dùng viết trong ô Bối cảnh: vế trái -> vế phải.

    Mỗi dòng `A = B`. Dòng nào không có dạng đó thì bỏ qua — ô Bối cảnh vẫn là
    chỗ viết văn xuôi tự do, chú giải chỉ là thứ đi kèm.

    Ở đây CHƯA biết vế nào là tên cột: chỗ đó do `named_by` quyết định, vì chỉ
    nó mới có danh sách cột thật. Nên viết `cột = nghĩa` hay `nghĩa = cột` đều
    đọc được.

    Hai dòng cùng vế trái thì GỘP lại chứ không đè. Trước đây dòng sau đè dòng
    trước, không báo gì: người dùng tưởng đã thêm một cách gọi, thật ra đã xoá
    cách gọi cũ.
    """
    table: dict[str, str] = {}
    for line in str(context).splitlines():
        matched = GLOSSARY_LINE.match(line)
        if matched is None:
            continue
        left, said = matched.group(1), matched.group(2).strip()
        if not said:
            continue
        table[left] = f"{table[left]}; {said}" if left in table else said
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
    asked_words = folded.split()
    listed = list(columns)
    meanings = _meanings_by_column(glossary or {}, listed)
    spans: dict[str, tuple[int, int, float]] = {}
    for column in listed:
        if len(column) >= MIN_LITERAL and _mentions_word(folded, column):
            spans[column] = _best_span(asked_words, [column])
            continue
        hits = [said for said in meanings.get(column, ()) if _meaning_appears(folded, said)]
        if hits:
            spans[column] = _best_span(asked_words, hits)
    return frozenset(_most_specific(spans))


def _best_span(asked_words: list[str], phrases: Sequence[str]) -> tuple[int, int, float]:
    """Đoạn dài nhất của các cụm này xuất hiện liền nhau trong câu hỏi.

    Trả về (vị trí bắt đầu, số chữ khớp, tỷ lệ phủ của cụm). Tỷ lệ phủ phá hoà
    khi hai cột khớp đúng cùng một đoạn: cụm được phủ trọn thắng cụm chỉ khớp
    một phần.
    """
    best = (0, 0, 0.0)
    for phrase in phrases:
        words = fold(phrase).split()
        for start in range(len(asked_words)):
            for offset in range(len(words)):
                size = 0
                while (
                    start + size < len(asked_words)
                    and offset + size < len(words)
                    and asked_words[start + size] == words[offset + size]
                ):
                    size += 1
                cover = size / len(words) if words else 0.0
                if (size, cover) > (best[1], best[2]):
                    best = (start, size, cover)
    return best


def _most_specific(spans: Mapping[str, tuple[int, int, float]]) -> set[str]:
    """Bỏ cột mà đoạn khớp của nó nằm trọn trong đoạn khớp của một cột cụ thể hơn.

    Đo trên một bản nháp thật: hỏi bằng đúng cách gọi của một cột thì 59/96 cột
    kéo theo cột khác. "Nợ ngắn hạn/tài sản ngắn hạn" kéo theo cả cột "nợ ngắn
    hạn/tài sản", vì cụm thứ hai nằm trọn trong cụm thứ nhất.

    Chỉ bỏ khi hai đoạn CHỒNG lên nhau trong câu hỏi. Hỏi hai cột ở hai chỗ khác
    nhau - "tỷ lệ nợ và biên lợi nhuận gộp" - thì giữ cả hai. Hai cột khớp đúng
    cùng một đoạn với cùng độ phủ thì cũng giữ cả hai: đó là mơ hồ thật, và
    việc báo nó ra thuộc về lúc duyệt chú giải.
    """
    kept: set[str] = set()
    for column, (start, size, cover) in spans.items():
        beaten = any(
            other != column
            and o_start <= start
            and start + size <= o_start + o_size
            and (o_size, o_cover) > (size, cover)
            for other, (o_start, o_size, o_cover) in spans.items()
        )
        if not beaten:
            kept.add(column)
    return kept


def _tidy(name: str) -> str:
    """Tên cột đã chuẩn hoá khoảng trắng, để khớp cho được."""
    return " ".join(str(name).split())


def _meanings_by_column(
    glossary: Mapping[str, str], columns: Sequence[str]
) -> dict[str, list[str]]:
    """Mỗi cột có thật, và mọi cách gọi của nó — viết chiều nào cũng đọc được.

    Vế nào khớp một cột có thật thì là tên cột; vế còn lại là các cách gọi.
    Chủ hệ thống viết `tỷ lệ nợ = Debt ratio %` — thuật ngữ trước, cột sau — và
    bản trước chỉ đọc chiều ngược lại, nên cả năm dòng của họ bị bỏ qua trong
    im lặng. Đo trên chính bảng đó: 0/3 câu hỏi nhận ra cột; đọc cả hai chiều
    thì 3/3.

    So khớp sau khi chuẩn hoá khoảng trắng: tên cột của một tệp có thể mang một
    dấu cách vô hình ở đầu, và bắt người dùng chép lại một ký tự vô hình là một
    cái bẫy, không phải một lớp bảo vệ.
    """
    real = {_tidy(name): name for name in columns}
    found: dict[str, list[str]] = {}
    for left, right in glossary.items():
        if _tidy(left) in real:
            column, said = real[_tidy(left)], right
        elif _tidy(right) in real:
            column, said = real[_tidy(right)], left
        else:
            continue
        for term in ALTERNATIVES.split(said):
            if term.strip():
                found.setdefault(column, []).append(term.strip())
    return found


def unmatched_lines(context: str, columns: Iterable[str]) -> list[str]:
    """Những dòng chú giải không trỏ tới cột nào có thật — để nói ra.

    Một dòng chú giải không khớp cột nào thì nằm im trong ô Bối cảnh, trông y
    hệt một dòng đúng. Chủ hệ thống đã viết năm dòng như thế và không có gì
    trên màn hình cho họ biết cả năm đều không được dùng.
    """
    real = {_tidy(name) for name in columns}
    lost: list[str] = []
    for line in str(context).splitlines():
        matched = GLOSSARY_LINE.match(line)
        if matched is None or not matched.group(2).strip():
            continue
        if _tidy(matched.group(1)) in real or _tidy(matched.group(2)) in real:
            continue
        lost.append(line.strip())
    return lost


def _meaning_appears(folded_question: str, meaning: str) -> bool:
    """Câu hỏi có nhắc tới thứ chú giải này mô tả không.

    Khớp trên một dải **liền nhau** `WINDOW` chữ của chú giải, không đòi cả
    câu: người ta mô tả một cột bằng một câu, rồi hỏi về nó bằng vài chữ.
    """
    words = fold(meaning).split()
    if not words or len("".join(words)) < MIN_PHRASE:
        return False
    if len(words) <= WINDOW:
        return _has_phrase(folded_question, " ".join(words))
    return any(
        _has_phrase(folded_question, " ".join(words[at : at + WINDOW]))
        for at in range(len(words) - WINDOW + 1)
    )


def _has_phrase(folded_question: str, phrase: str) -> bool:
    """Cụm này có mặt NGUYÊN CHỮ trong câu hỏi, không lọt vào giữa chữ khác.

    Trước đây so bằng chuỗi con: "kỳ hạn" khớp vào "kỳ hạnh". Giờ một cột có thể
    có nhiều cách gọi ngắn, nên khớp lọt chữ đáng lo hơn trước.
    """
    pattern = rf"(?<![0-9a-z_]){re.escape(phrase)}(?![0-9a-z_])"
    return re.search(pattern, folded_question) is not None


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
    measured = columns_in(all_keys)
    # Chi them khoa cua dong viet chieu `cot = nghia`. Dong viet nguoc
    # (`nghia = cot`) co khoa la mot CACH GOI, khong phai mot cot - them no vao
    # thi canh bao se noi toi mot "cot" khong co that.
    real = {_tidy(name) for name in measured}
    forward = frozenset(key for key, said in glossary.items() if _tidy(said) not in real)
    asked = named_by(question, measured | forward, glossary)
    missing = asked - used
    if not missing:
        # Câu hỏi không gọi tên cột nào, hoặc câu trả lời đã đụng tới hết. Đây
        # là trường hợp thường gặp, và im lặng ở đây chính là lý do cảnh báo
        # còn đáng tin khi nó nổ.
        return ""

    return (
        f"Câu hỏi có nhắc tới {_listed(missing)}, nhưng không kết luận nào dưới "
        f"đây dựa trên {'cột đó' if len(missing) == 1 else 'các cột đó'}, phần "
        f"này của câu hỏi có thể chưa được trả lời."
    )


def _listed(columns: Iterable[str]) -> str:
    ordered = sorted(columns)
    if len(ordered) == 1:
        return f"cột {ordered[0]}"
    return "các cột " + ", ".join(ordered)


def asked_question(params: Mapping[str, Any], fallback: str = "") -> str:
    """Câu hỏi dùng để chọn cột: câu hỏi gốc của người dùng trước hết.

    Bước phân tích chỉ nhận lời dặn của Manager, và lời dặn có thể đã đổi cột.
    Lượt chạy thật: hỏi "biên lợi nhuận gộp", lời dặn viết "'Operating Gross
    Margin' hoặc 'Gross Profit to Sales'", còn bước chọn phép kiểm thì không
    nhận được câu hỏi nào, nên nó không tách nhóm cho cột được hỏi.
    """
    return str(params.get(ASKED_PARAM) or params.get("question") or fallback)
