"""Trung bình của TỪNG nhóm, đi kèm mọi kết luận nói về khác biệt giữa các nhóm.

Lượt chạy thật (cấp độ 3): kết luận 1 chỉ viết "khác biệt trung bình giữa hai nhóm
là 0.07", kết luận 2 chỉ viết "effect size 1.17". Trung bình của từng nhóm (0.79 và
0.72) đã được đo, nằm ngay trong bộ số, nhưng không câu nào nêu ra: người đọc phải
tự dò xuống biểu đồ mới biết nhóm nào bao nhiêu.

Hai lớp. Luật trong prompt (`GROUP_MEANS_RULE`) bảo model viết theo khung mẫu. Còn
lời dặn không bảo đảm được model nghe theo, nên code nối thêm câu đó cho mọi kết
luận vẫn còn thiếu, bằng đúng các con số đã đo, và thêm các khóa ấy vào phần dẫn
chứng để câu mới vẫn lần ngược được. Không đoán gì: nhóm nào không có trung bình
trong bộ số thì không nối.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Final

from analysis_system.services.svg_chart import _find, _gap, _printed

if TYPE_CHECKING:  # pragma: no cover - chỉ dùng cho kiểu
    from analysis_system.contracts.agents import ManagerAnswer

# Phép tính so sánh các nhóm: `<cột số>.<phép tính>.by.<cột nhóm>[.<lá>]`.
COMPARISONS: Final[frozenset[str]] = frozenset({"diff", "effect_size", "ttest", "anova", "eta_sq"})
LEAVES: Final[frozenset[str]] = frozenset({"p_value", "t_stat", "n", "f_stat", "groups"})

# Nhiều nhóm hơn thế này thì liệt kê từng ấy nhóm cao nhất, còn lại nói số lượng.
MAX_LISTED: Final[int] = 6

# Luật cho A7 và A9. Tên khóa viết dạng <...>: một khóa thật chép vào luật sẽ bị
# model ghép sang một bảng không có cột ấy.
GROUP_MEANS_RULE: Final[str] = (
    "Noi ve KHAC BIET giua cac nhom (khoa co '.diff.by.', '.ttest.by.', '.effect_size.by.', "
    "'.anova.by.', '.eta_sq.by.') thi cau do PHAI dan kem trung binh cua TUNG nhom (khoa dang "
    "'<do_luong>.mean.by.<cot_nhom>.<ten_nhom>' co trong danh sach chi so) va viet theo mau: "
    "'Trung binh cua nhom <A> la {<khoa trung binh A>}, cao hon (hoac thap hon) so voi nhom <B> "
    "la {<khoa trung binh B>} (muc chenh lech {<khoa .diff.by.>})'. KHONG duoc chi viet muc "
    "chenh lech hay effect size: nguoi doc phai thay ca hai con so."
)


def _tidy(text: str) -> str:
    return " ".join(str(text).split())


def compared_pairs(keys: Sequence[str]) -> list[tuple[str, str]]:
    """Những cặp (cột số, cột nhóm) mà các khóa này so sánh giữa các nhóm."""
    found: list[tuple[str, str]] = []
    for key in keys:
        if ".by." not in str(key):
            continue
        head, tail = str(key).split(".by.", 1)
        measure, _, stat = head.rpartition(".")
        if not measure or stat not in COMPARISONS:
            continue
        group, _, leaf = tail.rpartition(".")
        if not group or leaf not in LEAVES:
            group = tail
        pair = (_tidy(measure), _tidy(group))
        if pair not in found:
            found.append(pair)
    return found


def group_means(
    measured: Mapping[str, float], measure: str, group: str
) -> list[tuple[str, float, str]]:
    """(giá trị nhóm, trung bình, khóa) của từng nhóm, cao trước."""
    prefix = f"{measure}.mean.by.{group}."
    found = [
        (_tidy(key)[len(prefix) :], float(value), key)
        for key, value in measured.items()
        if _tidy(key).startswith(prefix)
    ]
    return sorted(found, key=lambda item: item[1], reverse=True)


def _cites_means(keys: Sequence[str], measure: str, group: str) -> bool:
    prefix = f"{measure}.mean.by.{group}."
    return any(_tidy(key).startswith(prefix) for key in keys)


def _named(
    value: str,
    group: str,
    labels: Mapping[str, Mapping[str, str]] | None,
    names: Mapping[str, str] | None,
) -> str:
    """Tên nhóm: nhãn giá trị nếu có, không thì "Tên cột: giá trị" như trên biểu đồ."""
    values = _find(labels, group)
    said = values.get(value) if isinstance(values, Mapping) else None
    return str(said) if said else f"{_find(names, group) or group}: {value}"


def means_sentence(
    measure: str,
    group: str,
    means: Sequence[tuple[str, float, str]],
    labels: Mapping[str, Mapping[str, str]] | None = None,
    names: Mapping[str, str] | None = None,
) -> str:
    """Câu nêu trung bình từng nhóm, theo khung mẫu của báo cáo. Rỗng khi thiếu số."""
    if len(means) < 2:
        return ""
    if len(means) == 2:
        (first, high, _), (second, low, _) = means
        name_a, name_b = _named(first, group, labels, names), _named(second, group, labels, names)
        if high == low:
            return (
                f"Trung bình {measure} của nhóm {name_a} và nhóm {name_b} bằng nhau, "
                f"cùng là {_printed(high)}."
            )
        return (
            f"Trung bình {measure} của nhóm {name_a} là {_printed(high)}, cao hơn so với "
            f"nhóm {name_b} là {_printed(low)} (mức chênh lệch {_gap(high - low)})."
        )
    listed = ", ".join(
        f"nhóm {_named(value, group, labels, names)} là {_printed(mean)}"
        for value, mean, _ in means[:MAX_LISTED]
    )
    more = f" và {len(means) - MAX_LISTED} nhóm khác" if len(means) > MAX_LISTED else ""
    return f"Trung bình {measure} theo từng nhóm: {listed}{more}."


def with_group_means(
    answer: ManagerAnswer,
    measured: Mapping[str, float],
    labels: Mapping[str, Mapping[str, str]] | None = None,
    names: Mapping[str, str] | None = None,
) -> ManagerAnswer:
    """Nối trung bình từng nhóm vào mọi kết luận so sánh nhóm còn thiếu nó.

    Chỉ dùng con số đã đo. Khóa của các con số ấy được thêm vào dẫn chứng của kết
    luận: câu mới lần ngược được y như câu model viết.
    """
    if not measured:
        return answer
    claims = []
    changed = False
    for claim in answer.claims:
        keys = [str(key) for key in claim.metric_keys]
        sentences: list[str] = []
        added: list[str] = []
        for measure, group in compared_pairs(keys):
            if _cites_means(keys, measure, group):
                continue
            means = group_means(measured, measure, group)
            sentence = means_sentence(measure, group, means, labels, names)
            if sentence:
                sentences.append(sentence)
                added.extend(key for _, _, key in means[:MAX_LISTED] if key not in keys)
        if not sentences:
            claims.append(claim)
            continue
        text = str(claim.claim).rstrip()
        if text and not text.endswith((".", "!", "?")):
            text += "."
        claims.append(
            claim.model_copy(
                update={
                    "claim": " ".join([text, *sentences]).strip(),
                    "metric_keys": (*claim.metric_keys, *added),
                }
            )
        )
        changed = True
    return answer.model_copy(update={"claims": tuple(claims)}) if changed else answer
