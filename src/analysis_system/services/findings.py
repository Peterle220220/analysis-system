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

PLACEHOLDER: Final[re.Pattern[str]] = re.compile(r"\{([A-Za-z0-9_.\-]+)\}")

# A digit outside a placeholder means the model typed a number itself.
BARE_DIGIT: Final[re.Pattern[str]] = re.compile(r"\d")


class FindingError(RuntimeError):
    """A finding states something it is not allowed to state."""


def placeholders(template: str) -> list[str]:
    """Every metric key a claim template refers to, in order."""
    return [match.group(1) for match in PLACEHOLDER.finditer(template)]


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
        head, separator, leaf = key.rpartition(".")
        if not separator or ".by." not in head or leaf in STAT_LEAVES:
            continue
        families.setdefault(head, {})[leaf] = metric.value
    return {family: groups for family, groups in families.items() if len(groups) >= 2}


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
    ranked = [key for key in keys if key.rpartition(".")[0] in families]
    if not ranked:
        return (
            "cau nhan dinh xep hang mot nhom ('cao nhat', 'lau nhat') nhung khong tro toi "
            "chi so cua nhom nao ca. Ten nhom la CHU - go thang vao cau - va phai kem "
            "placeholder chi so cua chinh nhom do, vi du "
            "'Nhom van_chuyen lau nhat, {gio_xu_ly.mean.by.nhom_van_de.van_chuyen}'"
        )

    for key in ranked:
        family, _, group = key.rpartition(".")
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


def check_finding(finding: Finding, metrics: dict[str, MetricValue]) -> list[str]:
    """Everything wrong with one finding.

    Returns:
        A list of problems. Empty means the finding may be rendered.
    """
    problems: list[str] = []
    without_placeholders = strip_known_labels(PLACEHOLDER.sub("", finding.claim_template), metrics)
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

    declared = set(finding.metric_keys)
    if declared and declared != set(used):
        problems.append(
            f"metric_keys khai bao {sorted(declared)} khong khop "
            f"voi cac placeholder {sorted(set(used))}"
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

    misuse = extreme_misuse(finding.claim_template, used, metrics)
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

    return RenderedFinding(
        claim=PLACEHOLDER.sub(substitute, finding.claim_template),
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
