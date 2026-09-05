"""Quy trinh lam sach: xem, phat bieu, va nghe theo nguoi dung.

Three things the boss asked for, in his words:

1. the system looks at the data and works out **whether** it needs cleaning;
2. if it does not, it still says so - the Manager confirms the data is clean;
3. if it does, it says **where** and **how**, and if the person wants something
   different the system does what they say.

The third is the one that was missing entirely. Approving and rejecting lets
somebody veto what was offered; it never let them ask for anything else.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from analysis_system.manager.gates import (
    GateError,
    GateOption,
    GateRequest,
    approved_rules_from,
    decide,
)
from analysis_system.services.diagnosis import examine

NOW = datetime.now(UTC)


def clean_table() -> pd.DataFrame:
    return pd.DataFrame({"ma": ["A1", "A2", "A3"], "nhom": ["x", "y", "x"]})


def dirty_table() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ma": ["A1 ", " A2", "A3", "A3"],
            "so_tien": ["1000", "2000", "3000", "3000"],
            "ghi_chu": ["ok", "N/A", "-", "-"],
        }
    )


# --- 1 va 2: xem, roi phat bieu ------------------------------------------------


def test_a_clean_table_is_reported_as_examined_and_clean() -> None:
    # The case that used to be invisible. Nothing to propose produced an empty
    # gate, and an empty gate looks the same whether the data was examined and
    # found clean or never examined at all.
    found = examine(clean_table())
    assert not found.needs_cleaning
    assert "KHONG thay gi can sua" in found.verdict


def test_the_clean_verdict_says_what_was_checked() -> None:
    # Otherwise it is an absence of effort dressed as a finding.
    found = examine(clean_table())
    assert "dong trung lap" in found.verdict
    assert "khoang trang thua" in found.verdict


def test_a_dirty_table_says_where_and_how_much() -> None:
    found = examine(dirty_table())
    assert found.needs_cleaning
    by_rule = {item.rule_id: item for item in found.findings}
    assert by_rule["trim_whitespace"].column == "ma"
    assert by_rule["trim_whitespace"].affected == 2
    assert by_rule["drop_exact_duplicates"].affected == 1
    assert by_rule["replace_sentinel_with_null"].column == "ghi_chu"


def test_each_finding_carries_a_count_not_an_impression() -> None:
    # "co ve co khoang trang thua" is approved on somebody's feeling;
    # "2/4 dong, 50.0%" is approved on a fact.
    found = examine(dirty_table())
    for item in found.findings:
        assert f"{item.affected:,}" in item.as_reason()
        assert "%" in item.as_reason()


def test_an_identifier_column_is_not_offered_for_casting() -> None:
    # L84: seeding cast_numeric_safe would have turned case_item "00001" into 1.
    frame = pd.DataFrame({"ma_phieu": [f"{index:05d}" for index in range(50)]})
    rules = {item.rule_id for item in examine(frame).findings}
    assert "cast_numeric_safe" not in rules


def test_an_empty_table_is_said_to_be_empty_rather_than_clean() -> None:
    found = examine(pd.DataFrame({"a": []}))
    assert not found.needs_cleaning
    assert "bang rong" in found.verdict


# --- 3: nguoi dung ra lenh, khong chi phu quyet ---------------------------------


def gate_with(rules: list[dict[str, object]]) -> GateRequest:
    return GateRequest(
        gate_id="gate_t3_clean",
        run_id="r",
        task_id="t3_clean",
        agent_id="a3_cleaner",
        title="duyet rule lam sach",
        question="Rule nao duoc phep chay?",
        options=tuple(
            GateOption(option_id=str(rule["rule_id"]), label=str(rule["rule_id"])) for rule in rules
        ),
        payload={"proposal": {"rules": rules}},
        created_at=NOW,
    )


PROPOSED: list[dict[str, object]] = [
    {"rule_id": "cast_numeric_safe", "columns": ["so"], "reason": "toan la so"},
]


def test_a_person_can_ask_for_cleaning_nobody_proposed() -> None:
    # The gap: approve and reject can only ever pick from what was offered, so
    # somebody could veto and not direct.
    request = gate_with(PROPOSED)
    decision = decide(
        request,
        approved=(),
        rejected=("cast_numeric_safe",),
        added=({"rule_id": "trim_whitespace", "columns": ("ma",), "reason": "toi muon"},),
        now=NOW,
    )
    rules = approved_rules_from(request, decision)
    assert [rule["rule_id"] for rule in rules] == ["trim_whitespace"]
    assert rules[0]["columns"] == ("ma",)


def test_what_was_rejected_still_does_not_run() -> None:
    request = gate_with(PROPOSED)
    decision = decide(
        request,
        approved=(),
        rejected=("cast_numeric_safe",),
        added=({"rule_id": "trim_whitespace", "columns": (), "reason": "x"},),
        now=NOW,
    )
    assert "cast_numeric_safe" not in [
        rule["rule_id"] for rule in approved_rules_from(request, decision)
    ]


def test_an_added_rule_is_recorded_so_a_rerun_obeys_it_too() -> None:
    # Every other decision here replays; one that did not would ask the person
    # the same question after every rerun.
    decision = decide(
        gate_with(PROPOSED),
        approved=("cast_numeric_safe",),
        added=({"rule_id": "trim_whitespace", "columns": ("ma",), "reason": "x"},),
        now=NOW,
    )
    assert decision.added[0]["rule_id"] == "trim_whitespace"


def test_a_rule_outside_the_rulebook_is_still_refused() -> None:
    # Being in charge is not the same as being unbounded. A person may ask for
    # more cleaning; they may not ask for cleaning the system has no code for.
    with pytest.raises(GateError):
        decide(
            gate_with(PROPOSED),
            approved=(),
            added=({"rule_id": "xoa_het_du_lieu", "columns": (), "reason": "x"},),
            now=NOW,
        )


def test_approving_and_adding_both_reach_the_run() -> None:
    request = gate_with(PROPOSED)
    decision = decide(
        request,
        approved=("cast_numeric_safe",),
        added=({"rule_id": "trim_whitespace", "columns": ("ma",), "reason": "x"},),
        now=NOW,
    )
    assert [rule["rule_id"] for rule in approved_rules_from(request, decision)] == [
        "cast_numeric_safe",
        "trim_whitespace",
    ]
