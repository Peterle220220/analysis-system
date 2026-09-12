"""Chọn chỉ số nào được gửi cho model, và nói ra cái nào bị bỏ.

Số dòng KHÔNG phải vấn đề. Không agent nào nhìn thấy một dòng dữ liệu nào -
`max_sample_rows: 0` trong manifest của cả A7 lẫn A9 - nên bốn mươi dòng và bốn
triệu dòng sinh ra **cùng một danh sách chỉ số**. Đọc bốn triệu dòng là chuyện
của pandas và DuckDB, không phải của prompt.

Số **cột** mới là vấn đề, và nó tăng theo bình phương: mỗi cặp cột số cho một hệ
số tương quan, mỗi cột nhóm nhân mỗi cột số cho một bảng so sánh. 12 cột cho 316
chỉ số; 25 cột cho 73.096 token đầu vào và một lần chạy chết.

Cái chết đó cụ thể như sau, lấy nguyên văn từ phản hồi của OpenRouter:

    finish_reason : "length"
    content       : null

Model tiêu hết ngân sách đầu ra vào phần suy nghĩ - nó đang cân nhắc rất cẩn
thận, tự nhắc mình không được bịa số - rồi bị cắt trước khi kịp viết câu trả
lời. Prompt càng to thì càng nhiều thứ để cân nhắc.

Nên phần này đặt một **ngân sách** cho prompt thay vì hy vọng nó vừa. Ba luật,
theo thứ tự:

1. Chỉ số nhắc tới cột người dùng hỏi thì lên trước. Đối chiếu bằng chữ, cố ý:
   người ta gõ tên cột y như nó nằm trong tệp.
2. Chỉ số tổng quát trước chỉ số chi tiết. Một cái trung bình chung đáng giá hơn
   trung bình của nhóm thứ mười bảy.
3. Hết ngân sách thì dừng - và **nói ra đã bỏ bao nhiêu**. Một con số vắng mặt
   và một con số không ai được báo trông giống hệt nhau, và đó là luật của cả hệ
   thống này chứ không riêng chỗ nào.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Final

from analysis_system.services.asked_columns import named_by, parse_glossary

# Ngân sách cho riêng danh sách chỉ số, tính bằng ký tự. Bốn ký tự đổi khoảng
# một token, nên 40.000 ký tự vào cỡ 10.000 token - đủ rộng cho một bảng bình
# thường, và còn xa mới chạm trần 120.000 của một lần gọi.
DEFAULT_BUDGET: Final[int] = 40_000

# Chỉ số nói về cả bảng, hoặc là con số đầu tiên người ta hỏi tới. Luôn ưu tiên.
HEADLINE: Final[tuple[str, ...]] = (
    "rows.total",
    ".mean",
    ".median",
    ".share_pct",
    ".count",
    ".corr.",
    ".r2.",
    ".p_value",
    ".eta_sq",
    ".f_stat",
)

# Chi tiết theo từng nhóm. Có ích, nhưng chỉ khi còn chỗ.
DETAIL: Final[str] = ".by."


def fold(text: str) -> str:
    """Chữ thường, bỏ dấu, để so tên cột với câu hỏi mà không vướng dấu."""
    stripped = "".join(
        char for char in unicodedata.normalize("NFD", text) if unicodedata.category(char) != "Mn"
    )
    return stripped.replace("đ", "d").replace("Đ", "D").lower()


# Một từ xuất hiện trong nhiều hơn chừng này phần các cột thì nó không phân
# biệt được cột nào với cột nào. Đo từ chính dữ liệu, không phải một danh sách
# tự viết ra — mỗi bộ dữ liệu có những từ nhàm của riêng nó.
COMMON_SHARE: Final[float] = 0.25

# Từ ngắn hơn thế này khớp bừa: `a`, `c`, `no` nằm trong mọi câu.
MIN_WORD: Final[int] = 3

# Mot tu tro toi khong qua chung nay cot thi van dang dung, du bang co bao
# nhieu cot. Tam la cho mot cau hoi con thu hep duoc that su.
ABSOLUTE_TELLING: Final[int] = 8


def _telling_words(columns: list[str]) -> dict[str, set[str]]:
    """Với mỗi cột, những từ trong tên nó thật sự phân biệt được nó.

    `interest`, `rate`, `before` nằm trong hàng chục cột của cùng một bảng —
    khớp theo chúng thì câu hỏi nào cũng gọi tên mọi cột. `roa` hay `debt` thì
    chỉ nằm trong vài cột, và đó chính là thứ người ta gõ ra khi muốn nói tới
    những cột ấy.

    Đo trên chính bộ cột đang có. Một danh sách từ nhàm viết sẵn sẽ đúng cho
    bảng này và sai cho bảng sau.
    """
    words_of: dict[str, set[str]] = {}
    seen: dict[str, int] = {}
    for name in columns:
        words = {
            word
            for word in re.findall(r"[a-z0-9]+", fold(name).replace("_", " "))
            if len(word) >= MIN_WORD
        }
        words_of[name] = words
        for word in words:
            seen[word] = seen.get(word, 0) + 1

    # Ty le mot minh la thuoc do sai. Voi bang bay cot, ba cot ROA cung chia
    # chu `roa` la 43 phan tram - bi coi la nham, va khong cot nao khop duoc gi.
    # Nhung mot tu tro toi ba cot la mot tin hieu tot; chi mot tu tro toi ba
    # muoi cot moi la vo dung.
    #
    # Nen lay cai NAO ROI HON: mot tran tuyet doi, hoac mot phan tu so cot.
    ceiling = max(ABSOLUTE_TELLING, int(len(columns) * COMMON_SHARE))
    return {
        name: {word for word in words if seen[word] <= ceiling} for name, words in words_of.items()
    }


def named_in(question: str, keys: list[str]) -> set[str]:
    """Những cột mà câu hỏi gọi tên.

    Đối chiếu bằng chữ chứ không bằng nghĩa, và đó là chủ ý: người dùng gõ tên
    cột y như nó nằm trong tệp - `Reason_Equity`, `Source` - nên so chữ là so
    đúng thứ họ vừa gõ. Đoán nghĩa ở đây là thêm một chỗ để đoán sai.

    Bản đầu so **cả tên cột** như một từ, nên mọi tên cột nhiều chữ đều vô
    hình. Bộ ngân hàng có cột một từ (`Source`, `Duration`) nên nó chạy được;
    bộ dự đoán phá sản có ` ROA(C) before interest and depreciation before
    interest`, và câu hỏi viết `ROA(C)` thì không khớp gì cả — hệ thống chọn
    tám cột đầu bảng chữ cái và bỏ đúng hai cột được hỏi.
    """
    folded = fold(question)
    words = set(re.findall(r"[a-z0-9_]+", folded))
    # KHONG cat o dau cham. Ham nay duoc goi bang hai thu: metric key
    # (`Source.Internet.share_pct`) va ten cot tho (`cons.conf.idx`). Cat o dau
    # cham dung cho cai dau va sai cho cai sau - `cons.conf.idx` thanh `cons`,
    # va bo ngan hang co ba cot nhu the (`emp.var.rate`, `cons.price.idx`) bi
    # cat am tham tu dau den gio.
    #
    # Nguoi goi biet minh dua gi vao, nen viec tach dau la cua nguoi goi.
    columns = sorted({name for name in keys if name})
    telling = _telling_words(columns)

    found: set[str] = set()
    run: dict[str, tuple[int, int]] = {}
    for name in columns:
        head = fold(name)
        if not head:
            continue
        # Khớp cả khi cột la `Reason_Equity` con cau hoi viet `reason_equity`,
        # va ca khi cau hoi chi noi `equity`.
        if head in words or any(part and part in words for part in head.split("_")):
            found.add(name)
            # Cung mot thuoc do cho moi nhanh. Nhanh nay tung tu cham diem
            # lay le, va no bo qua phep chon hep: hoi "doanh_thu thang nay",
            # chu "thang" nam trong "don_hang_thang_1" nen ca hai deu khop
            # ngang nhau, du "doanh thu" chi tro toi mot cot con "thang" tro
            # toi hai.
            run[name] = _best_run(name, folded, columns)
            continue
        if telling[name] & words:
            found.add(name)
            run[name] = _best_run(name, folded, columns)
    return _most_specific(found, run)


def _words(text: str) -> list[str]:
    """Các chữ trong đoạn này, đã gấp dấu và bỏ hết ký tự không phải chữ."""
    return re.findall(r"[a-z0-9]+", fold(text).replace("_", " "))


def _best_run(name: str, folded_question: str, columns: list[str]) -> tuple[int, int]:
    """Cụm khớp tốt nhất của cột này: **hẹp trước, dài sau**.

    `ROA(C)` gấp lại thành hai chữ `roa c`, và chính chữ `c` mới phân biệt nó
    với `ROA(A)`. Đếm từng chữ một thì cả ba cột ROA khớp như nhau; đếm theo
    **cụm liền nhau** thì `roa c` dài hơn `roa`.

    Nhưng dài không phải lúc nào cũng cụ thể. Hỏi *"Doanh thu bao nhiêu triệu
    đồng"*, cụm `trieu dong` dài đúng hai chữ y như `doanh thu` — nhưng nó là
    **đơn vị**, nằm trong nhiều tên cột, còn `doanh thu` chỉ nằm trong một.

    Nên đo trước hết bằng **cụm ấy trỏ tới bao nhiêu cột**: ít hơn là cụ thể
    hơn. Bằng nhau mới xét tới dài hơn.

    Returns:
        (số cột cụm này trỏ tới, độ dài cụm). Nhỏ hơn ở chỗ đầu là tốt hơn;
        `(len(columns) + 1, 0)` nghĩa là không khớp gì.
    """
    mine = _words(name)
    asked = _words(folded_question)
    if not mine or not asked:
        return (len(columns) + 1, 0)

    every = [_words(other) for other in columns]
    best = (len(columns) + 1, 0)
    for start in range(len(mine)):
        for end in range(len(mine), start, -1):
            piece = mine[start:end]
            if not any(
                asked[at : at + len(piece)] == piece for at in range(len(asked) - len(piece) + 1)
            ):
                continue
            breadth = sum(
                1
                for words in every
                if any(
                    words[at : at + len(piece)] == piece
                    for at in range(len(words) - len(piece) + 1)
                )
            )
            best = min(best, (breadth, -len(piece)))
    return best


def _most_specific(found: set[str], run: dict[str, tuple[int, int]]) -> set[str]:
    """Chỉ giữ những cột khớp bằng cụm dài nhất.

    Người dùng gõ `ROA(C)`, và trong bảng chỉ có **một** cột mang đúng cụm ấy.
    Bắt họ gõ ` ROA(C) before interest and depreciation before interest` là bắt
    họ chép lại một cái tên chẳng ai nhớ nổi.

    Ba cột ROA cùng chia chữ `roa`, nhưng chỉ `ROA(C)` chứa cả cụm `roa c`. Cụm
    dài hơn thắng — và khi hai cột **cùng** dài nhất thì giữ cả hai, vì lúc đó
    câu hỏi thật sự chưa chỉ rõ, và chọn hộ một cái là đoán.
    """
    if not found:
        return found
    # Chi giu nhung cot khop bang cum DAI NHAT.
    #
    # Hoi "doanh_thu thang nay the nao", chu `thang` cung nam trong
    # `don_hang_thang_1` - nen ca hai deu khop, du nguoi hoi chi nhac mot cot.
    # `doanh_thu` khop ca hai chu (`doanh thu`), con `don_hang_thang_1` chi
    # khop mot. Cum dai hon la cum cu the hon.
    #
    # Bang nhau thi giu ca hai: hoi "so sanh chi phi va doanh thu" thi ca hai
    # cung khop hai chu, va bo mot cai la tra loi nua cau.
    sharpest = min(run[name] for name in found)
    return {name for name in found if run[name] <= sharpest}


def by_glossary(question: str, columns: list[str], glossary: str) -> set[str]:
    """Cột câu hỏi gọi tên QUA BẢNG CHÚ GIẢI, hoặc gọi đúng nguyên tên cột.

    Khớp được thì kết quả này ƯU TIÊN TUYỆT ĐỐI: người gọi dùng nó thay cho phép
    khớp theo từng chữ bên dưới, không cộng hai thứ lại. Bảng chú giải là điều
    người dùng đã tự khai; khớp theo chữ là đoán.

    Lượt chạy thật: hỏi "biên lợi nhuận gộp", chú giải ghi `Operating Gross
    Margin = biên lợi nhuận gộp hoạt động`, nhưng phần này chỉ khớp theo chữ,
    không đọc chú giải, và giữ lại `Gross Profit to Sales`, một cột khác có
    tương quan gần bằng 1 với cột được hỏi. Câu trả lời nói về cột đó.

    Rỗng khi không có chú giải hoặc không khớp gì: người gọi quay về khớp chữ.
    """
    table = parse_glossary(glossary) if glossary else {}
    if not table or not question:
        return set()
    return set(named_by(question, sorted({name for name in columns if name}), table))


def rank(key: str, wanted: set[str]) -> tuple[int, int, str]:
    """Thứ hạng của một chỉ số. Nhỏ hơn là được gửi trước."""
    head = key.split(".", 1)[0]
    about_asked = 0 if head in wanted else 1
    if key == "rows.total":
        kind = 0
    elif any(mark in key for mark in HEADLINE) and DETAIL not in key:
        kind = 1
    elif any(mark in key for mark in HEADLINE):
        kind = 2
    else:
        kind = 3
    return (about_asked, kind, key)


def choose(
    metrics: list[dict[str, Any]],
    question: str,
    budget: int = DEFAULT_BUDGET,
    *,
    glossary: str = "",
) -> tuple[list[dict[str, Any]], str]:
    """Chọn chỉ số vừa ngân sách, ưu tiên cái câu hỏi nhắc tới.

    Args:
        metrics: cả danh sách, dạng đã sẵn sàng đưa cho model.
        question: câu hỏi của người dùng.
        budget: số ký tự tối đa dành cho danh sách chỉ số.
        glossary: bảng chú giải `cột = nghĩa`; khớp qua nó thì được ưu tiên
            tuyệt đối (xem `by_glossary`).

    Returns:
        (danh sách được gửi, một dòng nói đã bỏ bao nhiêu). Dòng đó rỗng khi
        không bỏ gì - không có gì để nói thì không nói.
    """
    if not metrics:
        return [], ""

    keys = [str(item.get("key", "")) for item in metrics]
    # Tach dau khoa o day:  nhan TEN COT, khong nhan metric key -
    # cat o dau cham la viec cua nguoi goi, vi chi nguoi goi biet minh dua gi vao.
    heads = [key.split(".", 1)[0] for key in keys]
    wanted = by_glossary(question, heads, glossary) or named_in(question, heads)
    ordered = sorted(metrics, key=lambda item: rank(str(item.get("key", "")), wanted))

    kept: list[dict[str, Any]] = []
    used = 0
    for item in ordered:
        cost = len(str(item)) + 2
        if kept and used + cost > budget:
            break
        used += cost
        kept.append(item)

    # Tra ve theo dung thu tu khoa, o ca hai duong ra. Viec sap xep o tren chi
    # de CHON, khong phai de trinh bay - va hai duong ra cho hai thu tu khac
    # nhau la mot cai bay cho bat ky ai doc ket qua.
    shown = sorted(kept, key=lambda item: str(item.get("key", "")))
    if len(kept) == len(metrics):
        return shown, ""

    dropped = len(metrics) - len(kept)
    note = (
        f"Bảng có {len(metrics):,} chỉ số, chỉ đưa {len(kept):,} cái liên quan nhất "
        f"vào phân tích, {dropped:,} cái còn lại không được xét. Prompt quá lớn thì "
        "model tiêu hết chỗ vào việc cân nhắc và không kịp trả lời."
    )
    if wanted:
        note += f" Ưu tiên các cột câu hỏi nhắc tới: {', '.join(sorted(wanted))}."
    return shown, note


def rankings_for(
    ranked: list[dict[str, str]],
    shown: list[dict[str, Any]],
    question: str = "",
    *,
    glossary: str = "",
) -> list[dict[str, str]]:
    """Bảng xếp hạng, cắt về đúng những chỉ số đã thật sự được gửi.

    Trên một lượt chạy thật: 698 chỉ số, 511 cái được gửi vừa ngân sách, nhưng
    bảng xếp hạng vẫn đủ 352 dòng — **52 dòng trong đó trỏ tới chỉ số model
    chưa từng nhìn thấy**. Bảo ai đó "X cao nhất" về một con số không có trong
    tầm mắt họ là mời họ tin mà không kiểm được.

    Và xếp lại: cột nào câu hỏi gọi tên thì lên trước. Cùng một lượt chạy đó,
    hỏi *"kênh thông tin nào nhiều nhất"*, model đọc trúng dòng
    `Equity_Market.mean.by.Source.Television` — một xếp hạng của **đo lường
    khác** chia theo Source — rồi nói Television là kênh phổ biến nhất. Dòng
    đúng, `Source.Financial_Consultants.count`, nằm lẫn trong ba trăm dòng
    cùng chữ "cao nhat".

    Không thêm trường nào vào mỗi dòng. Hai hình dạng trước đã thử và đều
    hỏng — xem chú thích trong `findings.rankings`: thứ gì trông giống một khoá
    nằm trong cấu trúc này thì sẽ bị trích như một khoá.
    """
    seen = {str(entry.get("key", "")) for entry in shown}
    kept = [row for row in ranked if str(row.get("khoa", "")) in seen]
    if not question:
        return kept
    heads = [str(row.get("khoa", "")).split(".", 1)[0] for row in kept]
    wanted = by_glossary(question, heads, glossary) or named_in(
        question, [str(row.get("khoa", "")) for row in kept]
    )
    return sorted(kept, key=lambda row: str(row.get("khoa", "")).split(".", 1)[0] not in wanted)
