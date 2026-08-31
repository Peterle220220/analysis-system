"""Tests for the fixture cutter. The selection rule has to be provably stable."""

from __future__ import annotations

from make_fixture import (
    DEFAULT_VARIANT_SHARE,
    IndexEntry,
    select_cases,
    variant_signature,
)


def _index() -> list[IndexEntry]:
    """Ten cases: two common variants and several rare ones."""
    entries = [IndexEntry(f"c{number:02d}", "common_a", 10) for number in range(1, 5)]
    entries += [IndexEntry(f"c{number:02d}", "common_b", 10) for number in range(5, 9)]
    entries.append(IndexEntry("c09", "rare_x", 10))
    entries.append(IndexEntry("c10", "rare_y", 10))
    return entries


def test_variant_signature_depends_on_the_activity_order() -> None:
    forward = [{"concept:name": "A"}, {"concept:name": "B"}]
    backward = [{"concept:name": "B"}, {"concept:name": "A"}]
    assert variant_signature(forward) != variant_signature(backward)
    assert variant_signature(forward) == variant_signature(list(forward))


def test_selection_never_exceeds_the_budget() -> None:
    index = _index()
    chosen = select_cases(index, 55)
    events = {entry.case_id: entry.event_count for entry in index}
    assert sum(events[case_id] for case_id in chosen) <= 55


def test_selection_takes_whole_cases_only() -> None:
    index = _index()
    chosen = select_cases(index, 35)
    events = {entry.case_id: entry.event_count for entry in index}
    total = sum(events[case_id] for case_id in chosen)
    # Every case is 10 events, so a truncated case would show up as a remainder.
    assert total % 10 == 0


def test_the_first_pass_covers_distinct_variants() -> None:
    index = _index()
    chosen = set(select_cases(index, 40, variant_share=1.0))
    variants = {entry.variant_hash for entry in index if entry.case_id in chosen}
    assert variants == {"common_a", "common_b", "rare_x", "rare_y"}


def test_the_second_pass_lets_common_variants_repeat() -> None:
    # This is the whole point of the split: with variant coverage only, every
    # variant would occur exactly once and frequency analysis would be dead.
    index = _index()
    chosen = set(select_cases(index, 80, variant_share=DEFAULT_VARIANT_SHARE))
    picked = [entry.variant_hash for entry in index if entry.case_id in chosen]
    assert picked.count("common_a") > 1


def test_selection_is_independent_of_the_input_order() -> None:
    index = _index()
    reversed_index = list(reversed(index))
    assert select_cases(index, 55) == select_cases(reversed_index, 55)


def test_selection_is_repeatable() -> None:
    index = _index()
    assert select_cases(index, 55) == select_cases(index, 55)


def test_a_case_larger_than_the_budget_is_skipped_not_cut() -> None:
    index = [IndexEntry("c01", "huge", 500), IndexEntry("c02", "small", 10)]
    assert select_cases(index, 100) == ["c02"]
