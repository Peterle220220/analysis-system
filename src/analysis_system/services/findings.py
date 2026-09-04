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
from typing import Final

from analysis_system.contracts.agents import Finding, MetricValue, RenderedFinding

# `\w` rather than [A-Za-z0-9_], because a category value is a category value in
# whatever language the data is written in. A column of "Co"/"Khong" produces the
# key `gio_xu_ly.mean.by.chuyen_cap.Không`, and an ASCII-only pattern simply did
# not see the placeholder around it - so the claim counted as citing nothing and
# was thrown away. Every Vietnamese label with a diacritic was unquotable, which
# on Vietnamese data is most of them.
PLACEHOLDER: Final[re.Pattern[str]] = re.compile(r"\{([\w.\-]+)\}")

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
NAME_PLACEHOLDER: Final[re.Pattern[str]] = re.compile(r"\{ten:([\w.\-]+)\}")

# A digit outside a placeholder means the model typed a number itself.
BARE_DIGIT: Final[re.Pattern[str]] = re.compile(r"\d")


class FindingError(RuntimeError):
    """A finding states something it is not allowed to state."""


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
    """
    for label in sorted(label_vocabulary(metrics), key=len, reverse=True):
        if any(character.isdigit() for character in label):
            text = text.replace(label, " ")
    return text


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
        ranked.append({"xep_hang": "cao nhat", "khoa": f"{family}.{top}"})
        ranked.append({"xep_hang": "thap nhat", "khoa": f"{family}.{bottom}"})
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


def doubled_unit(template: str, metrics: Mapping[str, MetricValue]) -> str | None:
    """A unit the model typed after a placeholder that already carries one.

    Code appends the unit when it substitutes, so "{x.null_pct}%" renders as
    "0 %%". The prompt has said not to do this for a long time and the model
    does it anyway, which is the usual lesson: a rule nothing enforces is a
    suggestion. Refused rather than trimmed, because trimming would mean
    deciding which "%" the sentence meant.

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

    unknown = [key for key in used if key not in metrics]
    if unknown:
        problems.append(f"tro toi chi so khong ton tai: {unknown}")

    # A name placeholder must point at a real group, not at a statistic. The
    # label of `nhom_van_de.distinct` is "distinct", which is the name of a
    # calculation and not the name of anything in the data.
    families = group_families(metrics)
    named = name_placeholders(finding.claim_template)
    for key in named:
        found = split_group(key)
        if key not in metrics:
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
    declared = {key.removeprefix("ten:") for key in finding.metric_keys}
    referenced = set(used) | set(named)
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
    misuse = extreme_misuse(finding.claim_template, [*used, *named], metrics)
    if misuse is not None:
        problems.append(misuse)

    return problems


def render_finding(
    finding: Finding, metrics: dict[str, MetricValue], evidence_hash: str = ""
) -> RenderedFinding:
    """Turn a checked finding into its final sentence.

    Raises:
        FindingError: the finding did not pass its checks.
    """
    problems = check_finding(finding, metrics)
    if problems:
        raise FindingError("; ".join(problems))

    used = {key: metrics[key] for key in placeholders(finding.claim_template)}

    def substitute(match: re.Match[str]) -> str:
        metric = used[match.group(1)]
        return _format(metric)

    # Names first: a name placeholder contains a key, and leaving it until after
    # the value pass would let the inner key be read as a value placeholder.
    named = NAME_PLACEHOLDER.sub(lambda m: label_of(m.group(1)), finding.claim_template)

    return RenderedFinding(
        claim=PLACEHOLDER.sub(substitute, named),
        template=finding.claim_template,
        metrics={key: metric.value for key, metric in used.items()},
        evidence_ref=finding.evidence_ref,
        evidence_hash=evidence_hash,
        confidence=finding.confidence,
        dimension=finding.dimension,
    )


def _format(metric: MetricValue) -> str:
    """Print one value the same way every time.

    Whole numbers lose the decimal point; everything else keeps two places. Two
    runs on the same data must produce the same sentence to the character.
    """
    value = metric.value
    text = f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"
    return f"{text} {metric.unit}".strip() if metric.unit else text


def render_all(
    candidates: list[Finding], metrics: dict[str, MetricValue], evidence_hash: str = ""
) -> tuple[list[RenderedFinding], list[str]]:
    """Render every finding that passes, and report the ones that do not.

    A bad finding is dropped rather than fixed. Repairing a claim would mean
    guessing what the model meant, which is exactly the thing this module exists
    to prevent.
    """
    rendered: list[RenderedFinding] = []
    rejected: list[str] = []
    for index, finding in enumerate(candidates):
        problems = check_finding(finding, metrics)
        if problems:
            rejected.append(f"finding[{index}]: {'; '.join(problems)}")
            continue
        rendered.append(render_finding(finding, metrics, evidence_hash))
    return rendered, rejected
