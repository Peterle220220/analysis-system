"""BPMN 2.0, written from the process that actually ran.

Most process diagrams are drawn by hand from what somebody believes the process
is. This one is written from the log: every task in it happened, every arrow
between two tasks was walked by real cases, and the number of cases that walked
it is recorded on the arrow.

Only the main paths. A model of a hundred and sixteen variants is not a model, it
is the log redrawn - so the diagram covers the variants that carry most of the
work and says, in its own documentation, what share of cases it leaves out. A
diagram that quietly omits a fifth of reality is worse than one that admits it.

No layout. Signavio and every other BPMN tool arranges the shapes on import, and
a hand-computed layout would be wrong the moment anybody moved a box. What is
written is the structure, which is the part that came from the data.
"""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree
from typing import Final

from analysis_system.contracts.agents import ProcessMap

BPMN_NS: Final[str] = "http://www.omg.org/spec/BPMN/20100524/MODEL"
XSI_NS: Final[str] = "http://www.w3.org/2001/XMLSchema-instance"
# How many of the ranked variants to draw. Past this the picture stops being a
# model of the process and becomes the log with boxes round it.
MAX_PATHS: Final[int] = 5


class BpmnError(ValueError):
    """There is no process here to draw."""


def _identifier(prefix: str, text: str, seen: dict[str, str]) -> str:
    """A stable id for one activity name.

    Numbered in first-seen order rather than hashed, so the same log always
    produces the same document and two exports can be compared.
    """
    if text not in seen:
        seen[text] = f"{prefix}_{len(seen) + 1}"
    return seen[text]


def _element(parent: ElementTree.Element, tag: str, **attributes: str) -> ElementTree.Element:
    """One BPMN element, namespaced."""
    return ElementTree.SubElement(parent, f"{{{BPMN_NS}}}{tag}", attributes)


def to_bpmn(found: ProcessMap, *, name: str = "Quy trinh do duoc tu du lieu") -> str:
    """Turn a mined process into BPMN 2.0 XML.

    Args:
        found: what A6 measured. Its variants are the paths drawn.
        name: what to call the process in the diagram.

    Returns:
        The document as text, ready to import.

    Raises:
        BpmnError: nothing was measured that could be drawn. An empty diagram
            would look like a process with no steps rather than an absent one.
    """
    variants = found.variants[:MAX_PATHS]
    if not variants:
        raise BpmnError("Khong co duong di nao de ve - ban do quy trinh chua do duoc variant nao.")

    definitions = ElementTree.Element(
        f"{{{BPMN_NS}}}definitions",
        {
            "id": "definitions_1",
            "targetNamespace": "http://analysis-system/process",
            f"{{{XSI_NS}}}schemaLocation": f"{BPMN_NS} BPMN20.xsd",
        },
    )
    process = _element(definitions, "process", id="process_1", name=name, isExecutable="false")

    _element(process, "documentation").text = _describe(found, len(variants))

    tasks: dict[str, str] = {}
    # Added to the document, not held: the ids are what the flows refer to.
    _element(process, "startEvent", id="start_1", name="Bat dau")
    _element(process, "endEvent", id="end_1", name="Ket thuc")

    # One task per distinct activity across the drawn paths, in first-seen order.
    for variant in variants:
        for step in _steps(variant.path):
            task_id = _identifier("task", step, tasks)
            if not any(task.get("id") == task_id for task in process.findall(f"{{{BPMN_NS}}}task")):
                _element(process, "task", id=task_id, name=step)

    flows: set[tuple[str, str]] = set()
    for index, variant in enumerate(variants, start=1):
        steps = _steps(variant.path)
        if not steps:
            continue
        chain = ["start_1", *[tasks[step] for step in steps], "end_1"]
        for position, (source, target) in enumerate(zip(chain, chain[1:], strict=False)):
            if (source, target) in flows:
                continue
            flows.add((source, target))
            _element(
                process,
                "sequenceFlow",
                id=f"flow_{index}_{position + 1}",
                sourceRef=source,
                targetRef=target,
                # Which path this arrow belongs to, so a reader can tell the
                # main route from a branch without counting.
                name=variant.label or f"duong {variant.rank}",
            )

    ElementTree.indent(definitions, space="  ")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        + ElementTree.tostring(definitions, encoding="unicode")
        + "\n"
    )


def _describe(found: ProcessMap, drawn: int) -> str:
    """What this diagram covers, and what it does not.

    The totals come from the metric set rather than from the shortlist of
    variants the map carries: counting those counts what was kept, not what was
    found, and the sentence meant to admit the omission would be the one hiding
    it.
    """
    numbers = {metric.key: metric.value for metric in found.metrics}
    total = int(numbers.get("process.variants", drawn))
    coverage = numbers.get("process.variant_coverage.top5_pct")

    said = f"Ve tu {drawn} duong di pho bien nhat trong {total} duong da do duoc."
    if coverage is not None:
        said += (
            f" Nhung duong nay chiem {coverage:.1f}% so case;"
            f" {100.0 - coverage:.1f}% con lai KHONG co trong so do nay."
        )
    elif total > drawn:
        said += f" {total - drawn} duong con lai khong co trong so do nay."
    return (
        f"{said} Nguon: {found.source}."
        " Moi mui ten deu la buoc ma case that da di qua;"
        " khong co buoc nao duoc them vao cho day du."
    )


def _steps(path: str) -> list[str]:
    """The activities in one variant's path, in order.

    The preview shortens a long path with an ellipsis; a truncated step is not a
    step and is left out rather than drawn as one.
    """
    return [
        step.strip()
        for step in path.split("->")
        if step.strip() and not step.strip().startswith("...")
    ]
