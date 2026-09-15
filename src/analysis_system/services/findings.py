"""Rendering findings, and the check that makes a hallucinated number impossible.

The rule from the spec is that A7 may not state a figure that is not in its
input metrics. This is where that rule is enforced, and it is enforced by shape
rather than by inspection:

* the model writes a sentence containing placeholders - "cham {delay.mean} ngay";
* a sentence containing a bare digit is rejected outright, before rendering;
* every placeholder must name a metric that code computed;
* code substitutes the values.

A number the model invented therefore has nowhere to go. It cannot be typed into
the sentence, because digits are refused; and it cannot be referenced, because
the key would not exist. That is a stronger guarantee than reading numbers back
out of finished prose and trying to match them, which founders on rounding,
on 4.8 against 4,80, and on figures derived from two others.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any, Final

from analysis_system.contracts.agents import Finding, MetricValue, RenderedFinding
from analysis_system.core.units import keeps_unit

# `\w` rather than [A-Za-z0-9_], because a category value is a category value in
# whatever language the data is written in. A column of "Co"/"Khong" produces the
# key `gio_xu_ly.mean.by.chuyen_cap.Không`, and an ASCII-only pattern simply did
# not see the placeholder around it - so the claim counted as citing nothing and
# was thrown away. Every Vietnamese label with a diacritic was unquotable, which
# on Vietnamese data is most of them.
# Bat ky thu gi giua hai dau ngoac nhon, tru chinh chung.
#
# Ban dau chi nhan `[\w.-]`, va mot bo du lieu that da lam lo cho do: cot ten
# `Bankrupt?` cho ra khoa `Bankrupt?.mean`, model viet dung khoa ay vao
# placeholder, va he thong khong nhan ra do la mot placeholder. Ket luan bi loai
# vi "dan chi so khong khop", ba lan lien, tren mot cau hoi chi la dem so dong.
#
# Ten cot that con te hon the: ` ROA(A) before interest and % after tax` co
# khoang trang dau dong, ngoac, va dau phan tram. Khong the doi du lieu cua
# nguoi dung cho vua mot bieu thuc chinh quy.
#
# Rong ra thi mot cum `{gi do}` trong van xuoi cung bi doc la placeholder -
# nhung `check_finding` doi chieu moi placeholder voi danh sach chi so, nen cai
# khong co that bi loai kem mot cau noi ro. To hon mot lop chan im lang.
PLACEHOLDER: Final[re.Pattern[str]] = re.compile(r"\{([^{}]+)\}")

# `{ten:<key>}` asks for the NAME of the group a key describes, not its value.
#
# Without this a group label can only be said by typing it, and the model does
# not type it. Asked which problem group is slowest it wrote
# "Nhom van de {nhom_van_de.distinct}", and asked to compare two months it wrote
# "o {diem_hai_long.by.ngay_mo.1970-01}" - correct key, and the label 1970-01
# vanished into the number it rendered to. Both times it was reaching for a way
# to *name* something and had only a value placeholder to reach for.
#
# So it gets one. This works with the habit instead of against it: the model
# already puts everything specific behind a placeholder, and the label it wants
# is sitting in the key it already cited. Telling it to type names instead was
# tried first, and measured not to work.
NAME_PLACEHOLDER: Final[re.Pattern[str]] = re.compile(r"\{ten:([^{}]+)\}")

# A digit outside a placeholder means the model typed a number itself.
BARE_DIGIT: Final[re.Pattern[str]] = re.compile(r"\d")


class FindingError(RuntimeError):
    """A finding states something it is not allowed to state."""


def tidy_key(name: str) -> str:
    """Tên khoá đã chuẩn hoá khoảng trắng, để khớp cho được.

    Một cột tên ` ROA(C) before interest...` mang một dấu cách vô hình ở đầu,
    và model phải chép lại **đúng** ký tự không nhìn thấy đó thì khoá mới khớp.
    Trên một lượt chạy thật nó chép thừa một dấu cách — viết `{ ` cho dễ đọc —
    nên khoá thành hai dấu cách và cả kết luận bị loại:

        metric_keys khai  ' ROA(C) ... .mean'
        placeholder tìm  '  ROA(C) ... .mean'

    Đòi hỏi ấy là một cái bẫy, không phải một lớp bảo vệ. Chuẩn hoá thì cái bẫy
    biến mất, và **không lớp chặn nào bị nới**: sau khi chuẩn hoá, khoá vẫn phải
    khớp một chỉ số **có thật** thì mới qua.
    """
    return " ".join(str(name).split())


def resolve_key(name: str, metrics: Mapping[str, MetricValue]) -> str | None:
    """Khoá thật mà tên này trỏ tới, hoặc None nếu không có chỉ số nào như thế."""
    if name in metrics:
        return name
    wanted = tidy_key(name)
    for key in metrics:
        if tidy_key(key) == wanted:
            return key
    return None


def resolve_name(
    name: str, metrics: Mapping[str, MetricValue], prefer: Iterable[str] = ()
) -> str | None:
    """Khoá thật mà một `{ten:...}` trỏ tới, kể cả khi model viết tắt `<cột>.<nhóm>`.

    Tên chỉ cần phần đuôi của khoá: `{ten:K}` in ra nhóm của K, không in số. Trên
    một lượt chạy thật (bao_cao_tai_chinh_mb_cua_4_quy_gan_nhat__q2, 2026-09-15)
    model viết `{ten:Kỳ báo cáo.Q4-2025}` thay cho khoá đầy đủ
    `... .ratio_pct.by.Kỳ báo cáo.Q4-2025`, cả bốn kết luận bị loại và lượt hỏi
    tốn thêm một vòng gọi model.

    Chỉ nhận khi đuôi `.by.<cột>.<nhóm>` khớp trọn cả tên cột lẫn tên nhóm, nên mọi
    khoá khớp đều in ra đúng một cái tên. Một tên trơn (`{ten:Q4-2025}`) không đủ để
    biết là cột nào, nên vẫn bị từ chối. Khi nhiều khoá cùng khớp, ưu tiên khoá mà
    câu đã dẫn (`prefer`), để phần đối chiếu `metric_keys` thấy đúng một trích dẫn.
    """
    real = resolve_key(name, metrics)
    if real is not None:
        return real
    wanted = tidy_key(name)
    if "." not in wanted:
        return None
    suffix = f".by.{wanted}"
    matches = [
        key for key in metrics if tidy_key(key).endswith(suffix) and split_group(key) is not None
    ]
    if not matches:
        return None
    cited = {tidy_key(key) for key in prefer}
    return next((key for key in matches if tidy_key(key) in cited), matches[0])


def placeholders(template: str) -> list[str]:
    """Every metric key a claim template asks for the VALUE of, in order."""
    return [match.group(1) for match in PLACEHOLDER.finditer(NAME_PLACEHOLDER.sub("", template))]


def name_placeholders(template: str) -> list[str]:
    """Every metric key a claim template asks for the NAME of, in order."""
    return [match.group(1) for match in NAME_PLACEHOLDER.finditer(template)]


def split_group(key: str) -> tuple[str, str] | None:
    """The family a metric belongs to and the group it describes.

    Two shapes carry a group name, and only one of them puts it last:

        gio_xu_ly.mean.by.nhom_van_de.van_chuyen   ->  ...nhom_van_de  | van_chuyen
        cot_2.joy.share_pct                        ->  cot_2.share_pct | joy

    Reading the last segment was enough until a question asked which label held
    the largest share. The key for that is the second shape, so `{ten:...}`
    resolved to "share_pct" and the claim was refused - the group could be
    measured and not named.

    Returns:
        (family, group), or None when the key describes no group.
    """
    parts = key.split(".")
    if len(parts) >= 2 and ".by." in key and parts[-1] not in STAT_LEAVES:
        return ".".join(parts[:-1]), parts[-1]
    if len(parts) == 3 and parts[-1] in STAT_LEAVES and parts[1] not in STAT_LEAVES:
        # <cot>.<nhom>.<phep tinh>: the family is the column and the statistic
        # together, so counts rank against counts and never against shares.
        return f"{parts[0]}.{parts[2]}", parts[1]
    return None


def label_of(key: str) -> str:
    """The group name a metric key describes, wherever it sits in the key."""
    found = split_group(key)
    return found[1] if found else key.rpartition(".")[2]


def label_vocabulary(metrics: Mapping[str, MetricValue]) -> frozenset[str]:
    """Every name the data itself uses, taken from the metric keys.

    A metric key is built out of column names and category values -
    exam_score.mean.by.study_bucket.0-2h - so its segments are exactly the words
    a claim may legitimately need in order to say which group it is describing.
    """
    words: set[str] = set()
    for key in metrics:
        for segment in key.split("."):
            if segment:
                words.add(segment)
    return frozenset(words)


def strip_known_labels(text: str, metrics: Mapping[str, MetricValue]) -> str:
    """Remove the data's own names before looking for invented numbers.

    Categories like 0-2h or 6h+ carry digits, and a model cannot name the group
    it is talking about without writing them. Banning those digits does not stop
    invention - it stops the model discussing that dimension at all, which is
    how a whole analysis ended up avoiding the question it was asked.

    Longest first, so 0-2h is removed before the bare 2 inside it could be.

    Matched in the label's own spelling **and** with underscores read as spaces.
    A group called `dưới_30` is written by any sane writer as "dưới 30", and on
    a real run that one mismatch had every claim thrown out - three different
    models, same rejection, none of them at fault.
    """
    for label in sorted(label_vocabulary(metrics), key=len, reverse=True):
        if not any(character.isdigit() for character in label):
            continue
        for spelling in _spellings(label):
            text = text.replace(spelling, " ")
    return text


def _spellings(label: str) -> tuple[str, ...]:
    """The ways a writer might spell one label, longest first.

    Only separators change - never the words. Turning `duoi_30` into a loose
    pattern would start excusing digits the label never contained, and the point
    of this whole check is that a digit must come from the data.
    """
    spaced = label.replace("_", " ")
    hyphened = label.replace("_", "-")
    seen = [label, spaced, hyphened]
    return tuple(sorted({item for item in seen if item}, key=len, reverse=True))


# Metric families that measure how two things move together, and never why.
INFERENTIAL: Final[tuple[str, ...]] = (
    ".corr.",
    ".rank_corr.",
    ".r2.",
    ".ttest.",
    ".anova.",
    ".effect_size.",
    ".eta_sq.",
    ".diff.by.",
    ".coef.",
    ".vif.",
    ".regression.",
    # A tree's importance says "knowing this helps predict that". It is
    # read as "changing this changes that" constantly, and it is not that.
    ".importance.",
    ".intercept",
)

# Words that turn an association into a cause. The list is short on purpose: it
# holds the phrasings that assert one thing produced another, and leaves alone
# the ones that only describe a pattern.
CAUSAL_WORDS: Final[tuple[str, ...]] = (
    "lam tang",
    "lam giam",
    "lam cho",
    "khien",
    "gay ra",
    "dan den",
    "dan toi",
    "nguyen nhan",
    "tac dong len",
    "tac dong den",
    "tac dong toi",
    "tac dong manh",
    "anh huong den",
    "anh huong toi",
    "cai thien",
    "thuc day",
    "cause",
    "causes",
    "leads to",
)


def _fold(text: str) -> str:
    """Vietnamese without its diacritics, so one spelling of a word is enough."""
    marks = str.maketrans(
        "áàảãạăắằẳẵặâấầẩẫậéèẻẽẹêếềểễệíìỉĩịóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựýỳỷỹỵđ",
        "aaaaaaaaaaaaaaaaaeeeeeeeeeeeiiiiiooooooooooooooooouuuuuuuuuuuyyyyyd",
    )
    return text.lower().translate(marks)


def causal_overreach(claim: str, metric_keys: Iterable[str]) -> str | None:
    """The causal phrase in a claim that only measured association, if there is one.

    A correlation says two things move together. Which one moves the other -
    or whether a third thing moves both - is not in the number, and a report
    that quietly asserts it has said something the data cannot support.

    Returns:
        The offending phrase, or None when the claim stays within what was
        measured.
    """
    if not any(family in key for key in metric_keys for family in INFERENTIAL):
        return None
    folded = _fold(claim)
    return next((word for word in CAUSAL_WORDS if word in folded), None)


# Phrases that assert a group stands at the top of its set, and the ones that
# assert it stands at the bottom. Kept short: each entry claims a *rank*, which
# is a fact about the whole set and therefore checkable. "cao hon nhom X" is a
# comparison between two named groups and is left alone.
TOP_WORDS: Final[tuple[str, ...]] = (
    "cao nhat",
    "lon nhat",
    "nhieu nhat",
    "lau nhat",
    "dai nhat",
    "cham nhat",
    "dung dau",
    "dan dau",
    "cao hon cac nhom khac",
    "cao hon tat ca",
    "nhieu hon cac nhom khac",
    "highest",
    "longest",
)
BOTTOM_WORDS: Final[tuple[str, ...]] = (
    "thap nhat",
    "nho nhat",
    "it nhat",
    "ngan nhat",
    "nhanh nhat",
    "thap hon cac nhom khac",
    "lowest",
    "shortest",
)

# Leaf segments that name a statistic about a breakdown rather than one of the
# groups inside it. Without this, gio_xu_ly.anova.by.nhom_van_de.p_value would
# look like a group called "p_value" and get ranked against "f_stat".
STAT_LEAVES: Final[frozenset[str]] = frozenset(
    {
        "count",
        "mean",
        "median",
        "std",
        "var",
        "sum",
        "min",
        "max",
        "n",
        "groups",
        "distinct",
        "f_stat",
        "p_value",
        "statistic",
        "effect",
        "ci_low",
        "ci_high",
        "slope",
        "intercept",
        "r",
        "r2",
        "share_pct",
    }
)


def group_families(metrics: Mapping[str, MetricValue]) -> dict[str, dict[str, float]]:
    """Every breakdown that has at least two groups to compare.

    A key like `gio_xu_ly.mean.by.nhom_van_de.van_chuyen` splits into the family
    `gio_xu_ly.mean.by.nhom_van_de` and the group `van_chuyen`. Grouping them
    back together is what lets code answer "which group is highest" itself,
    instead of trusting the model to compare four numbers correctly.
    """
    families: dict[str, dict[str, float]] = {}
    for key, metric in metrics.items():
        found = split_group(key)
        if found is None:
            continue
        family, group = found
        families.setdefault(family, {})[group] = metric.value
    return {family: groups for family, groups in families.items() if len(groups) >= 2}


def rankings(metrics: Mapping[str, MetricValue]) -> list[dict[str, str]]:
    """Which group sits at each end of every breakdown, by name.

    The other half of L86. Refusing a wrong ranking stopped the nonsense but
    left the question unanswered: asked *"which group takes longest?"*, the
    model had four numbers and no key meaning "the highest one", so it stayed
    stuck. This hands it the answer it was missing.

    Keys, never values - the same division as `process_paths`. The key is a
    handle the model can spend two ways, `{ten:key}` for the name and `{key}`
    for the figure, and the number stays behind it where the digit rule can
    still reach it. `extreme_misuse` then checks the pairing, so a model that
    ignores this and picks its own group is still caught.
    """
    # The real key, never one rebuilt from its parts. Rebuilt keys were right
    # for `X.mean.by.C.<group>`, where the group is last, and wrong for
    # `C.<group>.count`, where it is in the middle: joining family to group gave
    # `cot_2.count.joy`, and the metric is `cot_2.joy.count`. So the model was
    # handed two keys that do not exist, used them, and had every ranking claim
    # rejected for citing a metric that was never computed.
    keys: dict[tuple[str, str], str] = {}
    for key in metrics:
        found = split_group(key)
        if found is not None:
            keys[found] = key

    ranked: list[dict[str, str]] = []
    for family, groups in sorted(group_families(metrics).items()):
        top = max(groups, key=lambda name: groups[name])
        bottom = min(groups, key=lambda name: groups[name])
        # One entry per end, and exactly one field in it that looks like a key.
        #
        # Two earlier shapes both failed on live runs, and each failure was the
        # payload's fault rather than the model's. Carrying the family alongside
        # the keys got the family cited, and it names no group. Naming the
        # fields `cao_nhat`/`thap_nhat` got `<family>.cao_nhat` cited - the
        # model read the field name as the last segment of the key. Anything
        # key-shaped in this structure will end up in a citation, so nothing
        # key-shaped goes in it except the key itself.
        ranked.append({"xep_hang": "cao nhat", "khoa": keys[family, top]})
        ranked.append({"xep_hang": "thap nhat", "khoa": keys[family, bottom]})
    return ranked


def extreme_misuse(
    claim: str, metric_keys: Iterable[str], metrics: Mapping[str, MetricValue]
) -> str | None:
    """The problem with a claim that ranks a group, if there is one.

    A question like *"nhom van de nao lau nhat?"* asks for a **name**, and the
    metric set holds only **numbers**. A model with no key meaning "the highest
    group" reaches for the nearest metric about that column and drops it where
    the name belongs, which produced this, from a real run:

        "Nhom van de 100 dong chiem ty le 23.81% trong tong so phieu."

    Every existing rule passes it. The metric is real, the value is real, no
    digit was typed. The sentence is still nonsense. Saying so in the prompt was
    tried and measured: it did not work, so it is checked here instead.

    Two things are refused. A ranking claim that cites no group at all has
    nothing to rank. A ranking claim that names a group which is not actually
    the extreme is simply wrong, and code can tell - it has the numbers.

    Returns:
        The problem, or None when the claim ranks nothing or ranks correctly.
    """
    folded = _fold(claim)
    top = any(word in folded for word in TOP_WORDS)
    bottom = any(word in folded for word in BOTTOM_WORDS)
    # Both directions at once is a sentence comparing two ends of a range
    # ("cao nhat 51.75, thap nhat 24.26"). There is no single rank being
    # asserted, so there is nothing here to check.
    if top == bottom:
        return None

    keys = list(metric_keys)
    # An extreme the code computed for itself needs no second opinion.
    if any(key.endswith((".max", ".min")) for key in keys):
        return None

    families = group_families(metrics)
    ranked = [
        (key, found)
        for key in keys
        if (found := split_group(key)) is not None and found[0] in families
    ]
    if not ranked:
        return (
            "cau nhan dinh xep hang mot nhom ('cao nhat', 'lau nhat') nhung khong tro toi "
            "chi so cua nhom nao ca. Phai dan chi so cua CHINH nhom do, va goi ten no bang "
            "'{ten:<khoa do>}' - vi du 'Nhom {ten:K} lau nhat, {K}.'"
        )

    for _key, (family, group) in ranked:
        groups = families[family]
        winner = (
            max(groups, key=lambda name: groups[name])
            if top
            else min(groups, key=lambda name: groups[name])
        )
        if group != winner:
            direction = "cao nhat" if top else "thap nhat"
            return (
                f"cau nhan dinh noi nhom {group!r} la {direction} trong {family!r}, "
                f"nhung nhom {direction} that su la {winner!r}"
            )
    return None


# Words that assert a statistical test was performed. Naming one is a claim
# about what the system did, not a way of describing a number.
TEST_WORDS: Final[tuple[str, ...]] = (
    "t-test",
    "t test",
    "ttest",
    "anova",
    "chi-square",
    "chi binh phuong",
    "kiem dinh",
    "p-value",
    "p value",
    "gia tri p",
    "y nghia thong ke",
    "co y nghia thong ke",
)

# The metric families that only exist when such a test really ran.
TEST_FAMILIES: Final[tuple[str, ...]] = (
    ".ttest.",
    ".anova.",
    ".chi2.",
    ".corr.",
    ".rank_corr.",
    ".effect_size.",
    ".eta_sq",
    ".p_value",
)


def untested_claim(claim: str, metric_keys: Iterable[str]) -> str | None:
    """A claim that names a statistical test which was never run.

    Straight from a live run on emotions.txt, and it passed every rule there
    was:

        "T-test cho thay co su khac biet dang ke ve trung binh so tu giua hai
         nhom 'anger' va 'joy' (t-statistic: 2,666.67, p-value: 2,666.67)."

    No test was run. The model cited `sentence_count.mean` and dropped that one
    figure into the t slot and the p slot both. Every existing check passed: a
    real key, no typed digit, no ranking, no doubled unit - and the sentence
    asserts a result that does not exist, in the register readers trust most.

    Same rule as everywhere else in here: the model may only refer to what
    actually happened. A test happened if and only if its metrics are present.

    Returns:
        The problem, or None when no test is claimed or one really ran.
    """
    folded = _fold(claim)
    named = next((word for word in TEST_WORDS if word in folded), None)
    if named is None:
        return None
    if any(family in key for key in metric_keys for family in TEST_FAMILIES):
        return None
    return (
        f"cau nhan dinh noi toi {named!r} nhung khong dan chi so nao cua mot phep kiem "
        "(.ttest., .anova., .p_value, .eta_sq...). Khong co phep kiem nao duoc chay, "
        "nen khong duoc noi la co. Mo ta bang so trung binh thi duoc."
    )


def without_doubled_units(template: str, metrics: Mapping[str, MetricValue]) -> tuple[str, bool]:
    """The claim with any unit typed straight after its own placeholder removed.

    Code appends the unit when it substitutes, so `{x.null_pct}%` renders as
    "0 %%". The prompt has forbidden this for a long time and the model does it
    anyway - two findings lost to it in a single run.

    This was a refusal at first, on the grounds that trimming means deciding
    which "%" the sentence meant. That reasoning was wrong: the rendered value
    *always* carries its unit, so the typed one is redundant in every case and
    there is nothing to decide. Rejecting cost a real finding each time it fired
    and taught the model nothing, because a model does not read its own
    rejections across runs.

    Repair is right exactly where there is one possible reading, and refusal
    stays right everywhere else in this module, where there is more than one.

    Returns:
        The tidied template, and whether anything was removed.
    """
    tidied = template
    changed = False
    while True:
        found = _doubled_at(tidied, metrics)
        if found is None:
            return tidied, changed
        start, end = found
        tidied = tidied[:start] + tidied[end:]
        changed = True


def _doubled_at(template: str, metrics: Mapping[str, MetricValue]) -> tuple[int, int] | None:
    """Where a redundant unit sits, as a slice of the template."""
    for match in PLACEHOLDER.finditer(NAME_PLACEHOLDER.sub("", template)):
        metric = metrics.get(match.group(1))
        if metric is None or not metric.unit:
            continue
        rest = template[match.end() :]
        spaces = len(rest) - len(rest.lstrip())
        if rest.lstrip().startswith(metric.unit):
            begin = match.end()
            return begin, begin + spaces + len(metric.unit)
    return None


def doubled_unit(template: str, metrics: Mapping[str, MetricValue]) -> str | None:
    """A unit the model typed after a placeholder that already carries one.

    Kept for the tests that describe the shape of the mistake. The claim path
    repairs it instead of refusing - see `without_doubled_units`.

    Returns:
        The problem, or None when no placeholder is followed by its own unit.
    """
    for match in PLACEHOLDER.finditer(NAME_PLACEHOLDER.sub("", template)):
        metric = metrics.get(match.group(1))
        if metric is None or not metric.unit:
            continue
        after = template[match.end() :].lstrip()
        if after.startswith(metric.unit):
            return (
                f"'{{{match.group(1)}}}' da co don vi {metric.unit!r} do he thong tu chen. "
                f"Ban viet them {metric.unit!r} ngay sau no, cau se thanh "
                f"'... {metric.unit} {metric.unit}'. Bo don vi ban go tay di."
            )
    return None


def check_finding(finding: Finding, metrics: dict[str, MetricValue]) -> list[str]:
    """Everything wrong with one finding.

    Returns:
        A list of problems. Empty means the finding may be rendered.
    """
    problems: list[str] = []
    bare = PLACEHOLDER.sub("", NAME_PLACEHOLDER.sub("", finding.claim_template))
    without_placeholders = strip_known_labels(bare, metrics)
    if BARE_DIGIT.search(without_placeholders):
        problems.append(
            "cau nhan dinh chua con so go truc tiep - moi so phai la mot placeholder "
            "{ten_chi_so} tro toi gia tri da tinh"
        )

    used = placeholders(finding.claim_template)
    if not used:
        problems.append("cau nhan dinh khong tro toi chi so nao - khong co gi de kiem chung")

    unknown = [key for key in used if resolve_key(key, metrics) is None]
    if unknown:
        problems.append(f"tro toi chi so khong ton tai: {unknown}")

    # A name placeholder must point at a real group, not at a statistic. The
    # label of `nhom_van_de.distinct` is "distinct", which is the name of a
    # calculation and not the name of anything in the data.
    families = group_families(metrics)
    named = name_placeholders(finding.claim_template)
    cited = [*used, *(key.removeprefix("ten:") for key in finding.metric_keys)]
    # Ten viet tat `{ten:<cot>.<nhom>}` duoc doi ve khoa that truoc moi phep kiem.
    resolved: list[str] = []
    for key in named:
        real = resolve_name(key, metrics, cited)
        found = split_group(real or key)
        resolved.append(real or key)
        if real is None:
            problems.append(f"'{{ten:{key}}}' tro toi chi so khong ton tai")
        elif found is None or found[0] not in families:
            problems.append(
                f"'{{ten:{key}}}' khong phai ten cua mot nhom nao ca - "
                f"'{label_of(key)}' la ten mot phep tinh. Chi dung ten: voi khoa "
                "dang '<do luong>.by.<cot>.<ten nhom>'"
            )

    # `ten:key` and `key` are two ways of spending the same citation, so the
    # declaration is read with the prefix removed. The model declared both forms
    # the first time it used a name placeholder - which is the honest thing to
    # do - and a comparison that only knew about values rejected the very claims
    # this mechanism exists to make possible.
    # Ca hai ben duoc chuan hoa khoang trang truoc khi so. Mot cot ten
    #  bat model chep lai dung mot ky tu vo hinh o CA HAI cho -
    # trong metric_keys va trong placeholder - va lech mot dau cach o mot ben
    # thi ca ket luan bi loai.
    declared = {
        tidy_key(resolve_name(name, metrics, cited) or name)
        for name in (key.removeprefix("ten:") for key in finding.metric_keys)
    }
    referenced = {tidy_key(key) for key in (*used, *resolved)}
    if declared and declared != referenced:
        problems.append(
            f"metric_keys khai bao {sorted(declared)} khong khop "
            f"voi cac placeholder {sorted(referenced)}"
        )

    if not finding.evidence_ref:
        problems.append("thieu evidence_ref - moi ket luan phai truy nguoc duoc ve du lieu goc")

    if not 0.0 <= finding.confidence <= 1.0:
        problems.append(f"confidence {finding.confidence} nam ngoai khoang 0..1")

    overreach = causal_overreach(finding.claim_template, used)
    if overreach is not None:
        problems.append(
            f"cau nhan dinh dung tu chi nhan qua {overreach!r} trong khi chi so chi do "
            "MOI LIEN HE. Viet lai theo kieu mo ta: 'di kem voi', 'tuong quan voi', "
            "'cao hon o nhom...'"
        )

    doubled = doubled_unit(finding.claim_template, metrics)
    if doubled is not None:
        problems.append(doubled)

    untested = untested_claim(finding.claim_template, used)
    if untested is not None:
        problems.append(untested)

    # Both kinds count as citing a group: "Nhom {ten:...van_chuyen} lau nhat"
    # names the group it is ranking just as surely as quoting its figure does.
    misuse = extreme_misuse(finding.claim_template, [*used, *resolved], metrics)
    if misuse is not None:
        problems.append(misuse)

    return problems


def render_finding(
    finding: Finding,
    metrics: dict[str, MetricValue],
    evidence_hash: str = "",
    as_written: str = "",
) -> RenderedFinding:
    """Turn a checked finding into its final sentence.

    Args:
        finding: the claim, already checked.
        metrics: the measured values its placeholders name.
        evidence_hash: what the figures were read from.
        as_written: the template **as the model wrote it**, before
            `without_doubled_units` tidied it. Only the unit decision reads
            this, and only because the two repairs would otherwise cancel out:
            that one removes the unit the model typed, trusting the system to
            put one back, while this one declines to put one back when the
            model has written its own noun. Both looking at the tidied text,
            `"{rows.total} dòng dữ liệu"` loses the word twice and comes out
            as *"40 dữ liệu"*.

    Raises:
        FindingError: the finding did not pass its checks.
    """
    problems = check_finding(finding, metrics)
    if problems:
        raise FindingError("; ".join(problems))

    # Khoa duoc doi chieu sau khi chuan hoa khoang trang: mot cot ten
    # ` ROA(C) ...` bat model chep lai dung mot ky tu vo hinh, va no chep thua
    # mot dau cach tren mot luot chay that.
    used = {}
    for name in placeholders(finding.claim_template):
        real = resolve_key(name, metrics)
        if real is not None:
            used[name] = metrics[real]

    def substitute(match: re.Match[str]) -> str:
        metric = used[match.group(1)]
        return _format(metric, keep_unit.get(match.group(1), True))

    # Quyet dinh doc tren mau cau model VIET RA, khong phai ban da tidy.
    keep_unit = _unit_decisions(as_written or finding.claim_template, used)

    # Names first: a name placeholder contains a key, and leaving it until after
    # the value pass would let the inner key be read as a value placeholder.
    cited = placeholders(finding.claim_template)
    named = NAME_PLACEHOLDER.sub(
        lambda m: label_of(resolve_name(m.group(1), metrics, cited) or m.group(1)),
        finding.claim_template,
    )

    return RenderedFinding(
        claim=PLACEHOLDER.sub(substitute, named),
        template=finding.claim_template,
        metrics={key: metric.value for key, metric in used.items()},
        evidence_ref=finding.evidence_ref,
        evidence_hash=evidence_hash,
        confidence=finding.confidence,
        dimension=finding.dimension,
    )


def _unit_decisions(template: str, used: Mapping[str, MetricValue]) -> dict[str, bool]:
    """Chỉ số nào còn cần đơn vị, đọc trên mẫu câu gốc.

    Một khoá xuất hiện hai lần với hai đuôi câu khác nhau thì **giữ** thắng: bỏ
    nhầm làm mất nghĩa, giữ nhầm chỉ thừa một chữ.
    """
    decisions: dict[str, bool] = {}
    for match in PLACEHOLDER.finditer(template):
        key = match.group(1)
        metric = used.get(key)
        if metric is None:
            continue
        keep = keeps_unit(metric.unit, template[match.end() :])
        decisions[key] = decisions.get(key, False) or keep
    return decisions


def _format(metric: MetricValue, keep_unit: bool = True) -> str:
    """Print one value the same way every time.

    Whole numbers lose the decimal point; everything else keeps two places. Two
    runs on the same data must produce the same sentence to the character.

    A counting noun like `dong` is dropped when the model has already written
    its own noun after the number - the unit is what stops a bare number being
    ambiguous, and after a noun it is not bare. See `services.units`.
    """
    value = metric.value
    text = f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"
    if metric.unit and keep_unit:
        return f"{text} {metric.unit}".strip()
    return text


def render_text(text: str, metrics: Mapping[str, MetricValue]) -> str:
    """Chèn giá trị vào một câu thường, cùng cách chèn như mọi luận điểm.

    Dùng cho câu chốt của Manager, chỗ không bắt buộc dẫn chỉ số nhưng vẫn cấm
    gõ số trực tiếp. Cùng một chỗ chèn số cho cả hai đường: hai cách in một con
    số là hai cơ hội để chúng lệch nhau.

    Placeholder trỏ tới chỉ số không có thật thì giữ nguyên, không xoá — mất
    chữ trong câu còn khó hiểu hơn là thấy một cái tên lạ, và `direct_answer`
    đã chặn trường hợp đó từ trước.
    """

    def value_of(match: Any) -> str:
        # Cung mot cach tra khoa nhu . Hai cho tra khac nhau la
        # hai cho lech nhau, va mot con so in ra hai kieu la mot cho de nghi ngo.
        real = resolve_key(match.group(1), metrics)
        return match.group(0) if real is None else _format(metrics[real])

    def name_of(match: Any) -> str:
        return label_of(resolve_name(match.group(1), metrics) or match.group(1))

    named = NAME_PLACEHOLDER.sub(name_of, str(text))
    return PLACEHOLDER.sub(value_of, named)


def render_all(
    candidates: list[Finding], metrics: dict[str, MetricValue], evidence_hash: str = ""
) -> tuple[list[RenderedFinding], list[str]]:
    """Render every finding that passes, and report the ones that do not.

    A bad finding is dropped rather than fixed. Repairing a claim would mean
    guessing what the model meant, which is exactly the thing this module exists
    to prevent - with one exception, and it earns the name: a unit typed after a
    placeholder that already carries one is redundant in every case, so there is
    nothing to guess. It is tidied, and the tidying is written down.
    """
    rendered: list[RenderedFinding] = []
    rejected: list[str] = []
    for index, finding in enumerate(candidates):
        as_written = finding.claim_template
        tidied, changed = without_doubled_units(finding.claim_template, metrics)
        if changed:
            finding = finding.model_copy(update={"claim_template": tidied})
            rejected.append(
                f"finding[{index}]: da bo don vi go tay ngay sau placeholder - he thong "
                "tu chen don vi, viet them se thanh '40.24 % %'."
            )
        problems = check_finding(finding, metrics)
        if problems:
            rejected.append(f"finding[{index}]: {'; '.join(problems)}")
            continue
        rendered.append(render_finding(finding, metrics, evidence_hash, as_written))
    return rendered, rejected


# Dấu nhận ra một ghi chú **sửa nhẹ** — kết luận vẫn còn, chỉ được dọn lại. Nó
# đi chung một danh sách với các kết luận bị loại thật, và người đọc đếm cả cụm
# là "đã bị trảm".
#
# Chủ hệ thống đã đọc đúng như vậy: *"UI phơi bày rõ lý do nó trảm 3 kết luận
# (do LLM gõ thừa dấu %)"* — trong khi hai trong ba cái đó **không bị trảm**,
# chúng được sửa và giữ lại. Rồi từ đó là một đề nghị nới lỏng một lớp bảo vệ
# vốn đã nới sẵn.
REPAIRED_MARK: Final[str] = "da bo don vi go tay"


def was_repaired(line: str) -> bool:
    """Dòng này nói một kết luận đã được **sửa và giữ**, không phải bị loại."""
    return REPAIRED_MARK in str(line).lower()
