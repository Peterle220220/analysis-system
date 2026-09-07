"""Does the answer have the shape the question asked for?

Being true is not enough, and being on the subject is not enough either. Asked
*"what percentage did A reach?"*, an answer of *"six channels were analysed"* is
correct, is about A, and is not an answer. Asked *"which factors affect the exam
score?"*, an answer of *"average attendance is 85.83"* is a real figure about the
right subject that says nothing at all about what affects anything.

`relevance` already checks that a claim is about the question. This checks the
other half: that it is the **kind of thing the question asked for**. The two
catch different failures and neither substitutes for the other.

The check is possible because the metric keys carry their own kind. A question
about causes needs a claim citing something relational - `.corr.with.`,
`.r2.with.`, `.diff.by.`, `.importance.` - and a summary like `.mean` cannot
answer it however true it is. That is not a guess about meaning; it is a fact
about which metric families exist:

    quan he  .corr.with.  .rank_corr.with.  .r2.with.  .importance.
             .diff.by.  .effect_size.by.  .eta_sq.by.  .ttest.by.  .anova.by.
    so luong .mean  .median  .sum  .total  .distinct  .null_pct  .cases
    cuc tri  .max  .min

Nothing here reads a model. The question is classified by the words a person
actually types, and the answer is judged by the keys it cites - both decided in
code, both the same every run.

**When in doubt, pass.** A question whose kind cannot be read is treated as an
open one, and an unmet demand is *reported*, never used to delete an answer. The
claims stay; what the reader is told is that the question asked for something the
data could not give. Turning "I could not answer that" into "here is nothing" is
how a check meant to help starts destroying work.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Final


class Demand(Enum):
    """What kind of answer a question is asking for."""

    QUANTITY = "so luong"
    RANKING = "xep hang"
    CAUSE = "nguyen nhan"
    COMPARISON = "so sanh"
    TREND = "xu huong"
    OPEN = "nhan dinh"


# What each kind of question is asking for, in the words it asks with.
#
# Order matters: a question is read against these in turn and the first that
# matches wins. CAUSE comes before QUANTITY because "yeu to nao anh huong den ty
# le hoan" contains "ty le" and is not a request for a percentage - it is a
# request for what moves one.
DEMAND_WORDS: Final[tuple[tuple[Demand, tuple[str, ...]], ...]] = (
    (
        Demand.CAUSE,
        (
            "vi sao",
            "tai sao",
            "do dau",
            "nguyen nhan",
            "ly do",
            "yeu to nao",
            "yeu to gi",
            "anh huong",
            "tac dong",
            "phu thuoc",
            "lien quan",
            "dan den",
            "gay ra",
            "chi phoi",
        ),
    ),
    (
        Demand.RANKING,
        (
            "nao nhat",
            "cao nhat",
            "thap nhat",
            "nhieu nhat",
            "it nhat",
            "lon nhat",
            "nho nhat",
            "manh nhat",
            "yeu nhat",
            "lau nhat",
            "nhanh nhat",
            "cham nhat",
            "top",
            "dung dau",
            "xep hang",
            "kem nhat",
            "tot nhat",
            "te nhat",
        ),
    ),
    (
        Demand.COMPARISON,
        (
            "so voi",
            "so sanh",
            "chenh lech",
            "khac nhau",
            "khac biet",
            "giua",
            "doi chieu",
            "cach biet",
        ),
    ),
    (
        Demand.TREND,
        (
            "xu huong",
            "thay doi",
            "bien dong",
            "theo thoi gian",
            "qua cac",
            "dien bien",
            "tang truong",
        ),
    ),
    (
        Demand.QUANTITY,
        (
            "bao nhieu",
            "phan tram",
            "ty le",
            "ty trong",
            "tong so",
            "trung binh",
            "tong cong",
            "con so",
            "dat muc",
            "bao lau",
            "%",
        ),
    ),
    (
        Demand.OPEN,
        (
            "thay duoc gi",
            "thay gi",
            "nhan xet",
            "danh gia",
            "nhan dinh",
            "tong quan",
            "ra sao",
            "the nao",
            "dieu gi",
            "van de gi",
            "rut ra",
            "ket luan gi",
            "mo ta",
        ),
    ),
)

# Which metric families answer which demand. Read off the keys the system really
# produces, not invented: see the module docstring.
RELATIONAL: Final[tuple[str, ...]] = (
    ".corr.with.",
    ".rank_corr.with.",
    ".r2.with.",
    ".importance.",
    ".diff.by.",
    ".effect_size.by.",
    ".eta_sq.by.",
    ".ttest.by.",
    ".anova.by.",
    ".contribution.",
    ".gap.",
)
SUMMARY: Final[tuple[str, ...]] = (
    ".mean",
    ".median",
    ".sum",
    ".total",
    ".distinct",
    ".null_pct",
    ".cases",
    ".events",
    ".count",
    ".pct",
    "_hours",
    ".rate",
)
EXTREME: Final[tuple[str, ...]] = (".max", ".min", ".longest", ".slowest", ".top")
GROUPED: Final[str] = ".by."
OVER_TIME: Final[tuple[str, ...]] = (
    ".by.month",
    ".by.year",
    ".by.day",
    ".by.week",
    ".by.quarter",
    ".trend.",
    ".over_time.",
    ".per_month",
    ".per_day",
)


def fold(text: str) -> str:
    """Lowercase, strip diacritics, keep words only.

    The same folding `relevance` uses, and for the same reason: people type
    Vietnamese both ways, and a question written without accents asks exactly
    what the accented one asks.
    """
    plain = unicodedata.normalize("NFD", text.lower())
    plain = "".join(char for char in plain if unicodedata.category(char) != "Mn")
    return " ".join(re.findall(r"[a-z0-9%]+", plain.replace(chr(273), chr(100))))


def read_question(question: str) -> Demand:
    """What kind of answer this question is asking for.

    Matched against the words people actually type, in a fixed order, first match
    winning. A question that matches nothing is OPEN - the kind that accepts any
    supported claim - because guessing wrong here would refuse a good answer, and
    the whole point is to catch answers that miss, not to invent new ways to miss.
    """
    folded = fold(question)
    for demand, words in DEMAND_WORDS:
        if any(word in folded for word in words):
            return demand
    return Demand.OPEN


def _has(keys: Iterable[str], marks: Iterable[str]) -> bool:
    """Whether any cited key belongs to any of these families."""
    marks = tuple(marks)
    return any(mark in key for key in keys for mark in marks)


@dataclass(frozen=True)
class Verdict:
    """Whether the answer is the kind of thing the question asked for."""

    demand: Demand
    met: bool
    # Empty when met. Otherwise says what was asked for and what came instead -
    # in the reader's words, because they are the one who has to decide whether
    # to ask differently.
    shortfall: str = ""


# What to tell the reader when a demand goes unmet. Written as the gap rather
# than as a rule, since "the question asked X, the figures only offer Y" is
# something a person can act on and "check failed" is not.
SHORTFALL: Final[dict[Demand, str]] = {
    Demand.CAUSE: (
        "cau hoi tim NGUYEN NHAN, nhung khong luan diem nao dan chi so ve quan he "
        "(tuong quan, muc giai thich, chenh lech theo nhom). Nhung so dua ra chi mo ta "
        "tung cot rieng le - dung, nhung khong noi duoc cai gi keo cai gi."
    ),
    Demand.RANKING: (
        "cau hoi doi mot cai DUNG DAU, nhung khong luan diem nao so nhieu muc voi nhau "
        "hay chi ra cuc tri - mot con so don le khong tra loi duoc 'cai nao nhat'."
    ),
    Demand.COMPARISON: (
        "cau hoi doi SO SANH giua cac ben, nhung cac luan diem chi dua ra con so mot "
        "phia, khong tach theo nhom de doi chieu."
    ),
    Demand.TREND: (
        "cau hoi doi XU HUONG theo thoi gian, nhung khong co chi so nao chia theo moc "
        "thoi gian - du lieu hien tai chua do duoc cai do."
    ),
    Demand.QUANTITY: (
        "cau hoi doi mot CON SO cu the, nhung khong luan diem nao dan chi so dinh luong."
    ),
}


def satisfied_by(demand: Demand, metric_keys: Sequence[str]) -> Verdict:
    """Whether these cited metrics can answer that kind of question.

    Judged on the keys alone. A key names its own family - `.corr.with.` is a
    relationship whatever it is called, `.mean` is a summary - so this asks a
    question with an answer instead of asking a model what it thinks.
    """
    keys = tuple(metric_keys)
    if demand is Demand.OPEN:
        met = bool(keys)
    elif demand is Demand.CAUSE:
        met = _has(keys, RELATIONAL)
    elif demand is Demand.RANKING:
        # Either an extremum, or several members of one family set side by side -
        # both are ways of showing that something came top.
        met = _has(keys, EXTREME) or _has(keys, (GROUPED,)) or len(set(keys)) > 1
    elif demand is Demand.COMPARISON:
        met = _has(keys, (GROUPED,)) or _has(keys, RELATIONAL) or len(set(keys)) > 1
    elif demand is Demand.TREND:
        met = _has(keys, OVER_TIME)
    else:  # QUANTITY
        met = _has(keys, SUMMARY) or _has(keys, EXTREME)

    if met:
        return Verdict(demand=demand, met=True)
    return Verdict(demand=demand, met=False, shortfall=SHORTFALL.get(demand, ""))


# Chữ báo rằng người hỏi muốn con số **tách theo nhóm**. Có chúng thì một chỉ
# số `.by.` chính là câu trả lời; không có thì nó là câu trả lời cho một câu
# khác.
BREAKDOWN_WORDS: Final[tuple[str, ...]] = (
    "theo tung",
    "tung nhom",
    "moi nhom",
    "tung loai",
    "moi loai",
    "phan theo",
    "chia theo",
    "theo nhom",
    "so voi",
    "giua",
    "khac nhau",
    "khac biet",
)


def only_broken_down(question: str, metric_keys: Sequence[str], every_key: Sequence[str]) -> str:
    """Hỏi một con số cho cả nhóm, mà chỉ nhận được số của các nhóm con.

    Lỗi thật: hỏi *"tỷ lệ đồng ý mở sổ trong nhóm sinh viên đã từng được liên
    hệ là bao nhiêu"*. Code đã lọc đúng 281 dòng và **đã đo** `is_yes.mean =
    0.452`. Câu trả lời lại là *"phân nhóm có chiến dịch trước thành công đạt
    0.71, cao hơn nhóm thất bại"* — đúng, dẫn nguồn được, và trả lời một câu
    không ai hỏi.

    Lớp kiểm dạng câu trả lời cho qua, vì `is_yes.mean.by.poutcome.success` có
    chữ `.mean` nên tính là một con số. Nhưng `.by.` là **chia nhỏ**, và người
    hỏi tổng thể không hỏi cái đó.

    Bốn điều kiện phải cùng đúng, vì im lặng là mặc định:

    1. câu hỏi đòi một con số;
    2. câu hỏi **không** đòi tách nhóm — không có "theo từng", "so với"…;
    3. **mọi** chỉ số được dẫn đều là chỉ số chia nhỏ;
    4. bản tổng thể của nó **có thật** trong số đã đo, nên có cái để nói.

    Returns:
        Câu nói rõ thiếu gì, hoặc rỗng. Đây là báo cho người đọc, không phải
        cái cớ để xoá một luận điểm.
    """
    keys = [str(key) for key in metric_keys]
    if not keys or read_question(question) is not Demand.QUANTITY:
        return ""
    folded = fold(question)
    if any(word in folded for word in BREAKDOWN_WORDS):
        return ""
    if not all(GROUPED in key for key in keys):
        return ""

    available = {str(key) for key in every_key}
    headline = sorted(
        {key.split(GROUPED, 1)[0] for key in keys} & available,
        key=len,
    )
    if not headline:
        return ""
    return (
        f"Câu hỏi đòi một con số cho cả nhóm, nhưng các kết luận chỉ đưa số đã "
        f"chia nhỏ theo nhóm con. Con số tổng thể có đo được: {headline[0]}."
    )


def check(question: str, metric_keys: Sequence[str]) -> Verdict:
    """Read the question, then judge the answer against what it asked for."""
    return satisfied_by(read_question(question), metric_keys)


def unanswered_end(question: str, claims: Sequence[str]) -> str:
    """Say so when a question asked for both ends and the answer gave one.

    Measured on a live run. Asked *"nhan nao chiem ty le cao nhat, va nhan nao
    thap nhat?"*, the answer said which was lowest and stopped - the claim about
    the highest had named the wrong group and been rejected, correctly. Nothing
    noticed that half the question was left standing, so the reader got a
    confident answer to something they had only half asked.

    The words come from `findings`, not from a second list here. Two lists of
    the same words drift apart, and this codebase has paid for that four times.

    Returns:
        What is missing, or empty when the question wanted one end or the answer
        covered both.
    """
    from analysis_system.services.findings import BOTTOM_WORDS, TOP_WORDS

    asked = fold(question)
    if not (_any_of(asked, TOP_WORDS) and _any_of(asked, BOTTOM_WORDS)):
        return ""
    said = fold(" ".join(claims))
    missing_top = not _any_of(said, TOP_WORDS)
    missing_bottom = not _any_of(said, BOTTOM_WORDS)
    if not (missing_top or missing_bottom):
        return ""
    which = "cao nhat" if missing_top else "thap nhat"
    return (
        f"cau hoi hoi ca hai dau, nhung cau tra loi khong noi duoc ve ben {which}. "
        "Nua con lai van con bo ngo."
    )


def _any_of(text: str, words: Iterable[str]) -> bool:
    """True when any of these phrases appears in the folded text."""
    return any(word in text for word in words)
