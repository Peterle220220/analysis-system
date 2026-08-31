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


def check_finding(finding: Finding, metrics: dict[str, MetricValue]) -> list[str]:
    """Everything wrong with one finding.

    Returns:
        A list of problems. Empty means the finding may be rendered.
    """
    problems: list[str] = []
    without_placeholders = PLACEHOLDER.sub("", finding.claim_template)
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

    return problems


def render_finding(finding: Finding, metrics: dict[str, MetricValue]) -> RenderedFinding:
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
    candidates: list[Finding], metrics: dict[str, MetricValue]
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
        rendered.append(render_finding(finding, metrics))
    return rendered, rejected
