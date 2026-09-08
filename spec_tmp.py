from pathlib import Path

p = Path("src/analysis_system/services/shortlist.py")
d = p.read_text(encoding="utf-8")

old = '''    folded = fold(question)
    words = set(re.findall(r"[a-z0-9_]+", folded))
    columns = sorted({key.split(".", 1)[0] for key in keys if key.split(".", 1)[0]})
    telling = _telling_words(columns)

    found: set[str] = set()
    for name in columns:
        head = fold(name)
        if not head:
            continue
        # Khớp cả khi cột la `Reason_Equity` con cau hoi viet `reason_equity`,
        # va ca khi cau hoi chi noi `equity`.
        if head in words or any(part and part in words for part in head.split("_")):
            found.add(name)
        elif telling[name] & words:
            found.add(name)
    return found'''

new = '''    folded = fold(question)
    words = set(re.findall(r"[a-z0-9_]+", folded))
    columns = sorted({key.split(".", 1)[0] for key in keys if key.split(".", 1)[0]})
    telling = _telling_words(columns)

    found: set[str] = set()
    matched_by: dict[str, set[str]] = {}
    length: dict[str, int] = {}
    for name in columns:
        head = fold(name)
        if not head:
            continue
        # Khớp cả khi cột la `Reason_Equity` con cau hoi viet `reason_equity`,
        # va ca khi cau hoi chi noi `equity`.
        if head in words or any(part and part in words for part in head.split("_")):
            found.add(name)
            length[name] = len(head.split())
            continue
        hits = telling[name] & words
        if hits:
            found.add(name)
            matched_by[name] = hits
            length[name] = _longest_run(name, folded)

    return _most_specific(found, matched_by, length)


def _longest_run(name: str, folded_question: str) -> int:
    """Dãy chữ **liền nhau** dài nhất của tên cột mà câu hỏi có nhắc tới.

    `ROA(C)` gấp lại thành hai chữ `roa c`, và chính chữ `c` mới phân biệt nó
    với `ROA(A)`. Đếm từng chữ một thì cả ba cột ROA đều khớp như nhau; đếm
    theo **cụm liền nhau** thì `roa c` dài hơn `roa`, và cụm dài hơn thắng.
    """
    words = fold(name).split()
    best = 0
    for start in range(len(words)):
        for end in range(len(words), start, -1):
            if end - start <= best:
                break
            if " ".join(words[start:end]) in folded_question:
                best = end - start
                break
    return best


def _most_specific(
    found: set[str], matched_by: dict[str, set[str]], length: dict[str, int]
) -> set[str]:
    """Bỏ những cột khớp bằng một cụm ngắn hơn cột khác cùng chia chữ ấy.

    Người dùng gõ `ROA(C)`, và trong bảng chỉ có **một** cột mang đúng cụm ấy.
    Bắt họ gõ ` ROA(C) before interest and depreciation before interest` là bắt
    họ chép lại một cái tên chẳng ai nhớ.

    Ba cột ROA cùng chia chữ `roa`, nhưng chỉ `ROA(C)` chứa cả cụm `roa c`. Cụm
    dài hơn thắng — và khi hai cột **cùng** dài nhất thì giữ cả hai, vì lúc đó
    câu hỏi thật sự chưa chỉ rõ, và chọn hộ một cái là đoán.
    """
    keep = set(found)
    for name in list(found):
        for other in found:
            if other == name or not (matched_by.get(name, set()) & matched_by.get(other, set())):
                continue
            if length.get(other, 0) > length.get(name, 0):
                keep.discard(name)
                break
    return keep'''
assert d.count(old) == 1, "khong tim thay named_in"
p.write_text(d.replace(old, new, 1), encoding="utf-8")
print("ok")
