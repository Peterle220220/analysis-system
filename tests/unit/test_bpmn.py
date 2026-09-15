"""BPMN: a diagram of the process that actually ran, and honest about what it omits.

Most process diagrams are drawn from what somebody believes the process is. This
one is written from the log, so the test that matters most is not about valid XML
- it is that the document says how much of reality it left out. It once claimed
to be drawn from five of five paths when the log held a hundred and sixteen,
because it counted the shortlist it had been handed rather than the process.
"""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree

import pytest

from analysis_system.models.agents import MetricValue, ProcessMap, ProcessVariant
from analysis_system.services.bpmn import MAX_PATHS, BpmnError, to_bpmn

NS = "{http://www.omg.org/spec/BPMN/20100524/MODEL}"


def variant(rank: int, path: str, label: str = "") -> ProcessVariant:
    return ProcessVariant(
        rank=rank,
        path=path,
        steps=len(path.split("->")),
        cases_key=f"process.variant.{rank}.cases",
        share_key=f"process.variant.{rank}.share_pct",
        label=label,
    )


def mapped(
    *,
    variants: tuple[ProcessVariant, ...] | None = None,
    total: int = 3,
    coverage: float | None = 80.0,
) -> ProcessMap:
    metrics = [MetricValue(key="process.variants", value=float(total), source="variant")]
    if coverage is not None:
        metrics.append(
            MetricValue(
                key="process.variant_coverage.top5_pct", value=coverage, unit="%", source="variant"
            )
        )
    return ProcessMap(
        source="clean://log.parquet",
        metrics=tuple(metrics),
        variants=variants
        or (
            variant(1, "Nhan ho so -> Kiem tra -> Duyet", "Luong chuan"),
            variant(2, "Nhan ho so -> Kiem tra -> Sua -> Duyet", "Co sua"),
        ),
    )


def documentation(found: ProcessMap) -> str:
    """What the diagram says about itself - the part that admits its omissions."""
    note = parsed(found).find(NS + "documentation")
    assert note is not None, "so do phai tu noi no bo sot cai gi"
    return note.text or ""


def parsed(found: ProcessMap) -> ElementTree.Element:
    root = ElementTree.fromstring(to_bpmn(found))
    process = root.find(NS + "process")
    assert process is not None
    return process


# --- the structure comes from the log ---------------------------------------------


def test_it_writes_a_task_for_every_activity_on_the_drawn_paths() -> None:
    process = parsed(mapped())
    names = {task.get("name") for task in process.findall(NS + "task")}
    assert names == {"Nhan ho so", "Kiem tra", "Duyet", "Sua"}


def test_an_activity_on_two_paths_becomes_one_task() -> None:
    # Otherwise the diagram shows the same step twice and the reader counts it
    # as two.
    process = parsed(mapped())
    names = [task.get("name") for task in process.findall(NS + "task")]
    assert len(names) == len(set(names))


def test_every_arrow_is_a_step_real_cases_walked() -> None:
    process = parsed(mapped())
    flows = process.findall(NS + "sequenceFlow")
    assert flows
    ids = {task.get("id") for task in process.findall(NS + "task")} | {"start_1", "end_1"}
    for flow in flows:
        assert flow.get("sourceRef") in ids
        assert flow.get("targetRef") in ids


def test_an_arrow_says_which_path_it_belongs_to() -> None:
    # So a reader can tell the main route from a branch without counting.
    process = parsed(mapped())
    labels = {flow.get("name") for flow in process.findall(NS + "sequenceFlow")}
    assert "Luong chuan" in labels


def test_it_starts_and_ends_somewhere() -> None:
    process = parsed(mapped())
    assert process.findall(NS + "startEvent")
    assert process.findall(NS + "endEvent")


def test_only_the_main_paths_are_drawn() -> None:
    # A model of a hundred variants is not a model, it is the log redrawn.
    many = tuple(variant(index, f"A -> B{index} -> C") for index in range(1, 12))
    process = parsed(mapped(variants=many, total=11))
    drawn = {flow.get("name") for flow in process.findall(NS + "sequenceFlow")}
    assert len(drawn) <= MAX_PATHS


# --- and it says what it leaves out -------------------------------------------------


def test_it_counts_the_paths_in_the_process_not_the_ones_it_was_handed() -> None:
    # It once said "five of five" when the log held a hundred and sixteen,
    # because ProcessMap keeps only the ranked few. The sentence meant to admit
    # the omission was the one hiding it.
    text = documentation(mapped(total=116))
    assert "116" in text
    assert "5 duong" not in text.split("trong")[1] if "trong" in text else True


def test_it_says_what_share_of_cases_it_does_not_cover() -> None:
    text = documentation(mapped(total=116, coverage=79.6))
    assert "79.6%" in text
    assert "20.4%" in text
    assert "KHONG co trong so do" in text


def test_without_a_coverage_figure_it_still_counts_what_is_missing() -> None:
    text = documentation(mapped(total=10, coverage=None))
    assert "8 duong con lai" in text


def test_it_names_where_the_process_came_from() -> None:
    text = documentation(mapped())
    assert "clean://log.parquet" in text


# --- what it refuses ------------------------------------------------------------------


def test_a_map_with_no_paths_is_refused_rather_than_drawn_empty() -> None:
    # An empty diagram looks like a process with no steps rather than an absent
    # one.
    with pytest.raises(BpmnError, match="Khong co duong di"):
        to_bpmn(ProcessMap(source="clean://x.parquet"))


def test_a_truncated_step_is_not_drawn_as_a_step() -> None:
    # A long path is previewed with an ellipsis; that is not an activity.
    process = parsed(
        mapped(variants=(variant(1, "A -> B -> ... (+9 buoc)"),), total=1, coverage=None)
    )
    names = {task.get("name") for task in process.findall(NS + "task")}
    assert names == {"A", "B"}


# --- the same log draws the same document ---------------------------------------------


def test_the_same_map_produces_the_same_xml_twice() -> None:
    # Ids are numbered in first-seen order rather than hashed, so two exports of
    # one process can be compared.
    assert to_bpmn(mapped()) == to_bpmn(mapped())
