"""Khoang cach giua LOI HUA cua mot luat va viec no THAT SU lam.

Every proposed rule carries a `reason`, and the reason is what a person reads
at the approval gate. They approve the sentence; the system runs the `rule_id`.
Nothing has ever checked that the two describe the same thing.

So a rule saying *"chuan hoa dinh dang ngay thang"* with `rule_id:
cast_numeric_safe` reads perfectly, gets approved on the strength of the
sentence, and turns the date column into nulls. The person did not approve
that. They were not shown it.

This is the same rule as everywhere else in this system, applied to one more
place: **what is said must match what happens.** A claim may only cite a metric
that was computed; a data request may only quote a refusal that occurred; and a
cleaning rule may only promise what its own code does.

The check is lexical, and that is on purpose. Each rule does one narrow, known
thing, and the words for that thing are a short list. A model asked "does this
reason match this rule" would be answering a question the words already answer,
unrepeatably and for money.

It reports rather than refuses. A reason worded oddly is not a reason to stop a
run - but a reason that describes a *different* rule in the book is worth
putting in front of the person before they approve it.
"""

from __future__ import annotations

from typing import Final

from analysis_system.services.relevance import fold

# What each rule actually does, in the words somebody would use to describe it.
# Taken from the rule bodies, not invented: `trim_whitespace` strips spaces,
# `cast_numeric_safe` converts to numbers, and so on.
DESCRIBES: Final[dict[str, frozenset[str]]] = {
    "trim_whitespace": frozenset({"khoang trang", "space", "thua", "dau cuoi", "trim"}),
    "normalize_unicode_nfc": frozenset({"unicode", "nfc", "dau tieng viet", "chuan hoa chu"}),
    "replace_sentinel_with_null": frozenset(
        {"sentinel", "gia tri thay the", "n/a", "na", "null", "rong", "thieu"}
    ),
    "standardize_datetime": frozenset(
        {"ngay", "thang", "thoi gian", "datetime", "date", "mui gio", "dinh dang ngay"}
    ),
    "cast_numeric_safe": frozenset({"so", "numeric", "kieu so", "ep kieu", "chuyen ve so"}),
    "drop_exact_duplicates": frozenset({"trung lap", "trung nhau", "duplicate", "ban sao", "lap"}),
    "flag_missing_required": frozenset({"thieu", "bat buoc", "missing", "danh dau", "required"}),
}


def describes_instead(rule_id: str, reason: str) -> str:
    """The rule this reason sounds like, when that is not the rule it belongs to.

    Returns:
        The rule id the wording points at, or empty when the reason matches its
        own rule, matches nothing in particular, or is blank.
    """
    words = fold(reason)
    if not words.strip():
        return ""
    if any(term in words for term in DESCRIBES.get(rule_id, frozenset())):
        return ""
    matches = [
        other
        for other, terms in DESCRIBES.items()
        if other != rule_id and any(term in words for term in terms)
    ]
    # Only when exactly one other rule fits. Two means the wording is loose
    # rather than wrong, and saying so would be noise at every gate.
    return matches[0] if len(matches) == 1 else ""


def mismatches(rules: list[dict[str, object]]) -> dict[int, str]:
    """Every proposed rule whose reason describes a different rule.

    Keyed by position in the proposal, because that is what the gate uses to
    name an option and a person needs to know *which* one to look at.
    """
    found: dict[int, str] = {}
    for index, rule in enumerate(rules):
        rule_id = str(rule.get("rule_id") or "")
        other = describes_instead(rule_id, str(rule.get("reason") or ""))
        if other:
            found[index] = other
    return found


def warning_for(rule_id: str, sounds_like: str) -> str:
    """What the gate shows about one mismatch."""
    return (
        f"[LUAT VA LY DO KHONG KHOP] ly do noi ve {sounds_like!r} nhung luat se chay la "
        f"{rule_id!r}. Duyet theo ly do thi ban dang duyet mot viec khac voi viec se xay ra."
    )
