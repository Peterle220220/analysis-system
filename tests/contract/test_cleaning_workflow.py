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

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from analysis_system.api import Workspace
from analysis_system.manager.gates import (
    GateError,
    GateOption,
    GateRequest,
    approved_rules_from,
    decide,
)
from analysis_system.services.diagnosis import examine
from analysis_system.settings import LAYER_NAMES, LayerPaths, Settings, load_settings

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


def test_a_repeated_code_with_a_leading_zero_is_not_offered_for_casting() -> None:
    # A postcode repeats itself freely, so the identifier test - "almost all
    # distinct" - lets it through. Casting it turns "01234" into 1234 and the
    # loss is invisible afterwards, because 1234 is a perfectly good number.
    frame = pd.DataFrame({"ma_buu_chinh": ["01234", "05678", "01234", "05678"] * 10})
    rules = {item.rule_id for item in examine(frame).findings}
    assert "cast_numeric_safe" not in rules


def test_a_plain_number_column_is_still_offered_for_casting() -> None:
    # The guard must not swallow the case it exists to allow: "0" and "0.5" are
    # numbers written normally and lose nothing by becoming numbers.
    frame = pd.DataFrame({"gio_hoc": ["0", "0.5", "3", "7.25"] * 10})
    rules = {item.rule_id for item in examine(frame).findings}
    assert "cast_numeric_safe" in rules


# --- mot cau hoi duoc tra loi; mot bao cao van co nguoi duyet ---------------------


def layers_in(root: Path) -> Settings:
    """Cau hinh tro vao thu muc tam, khong dung toi tang du lieu that."""
    roots = {name: root / name for name in LAYER_NAMES}
    for path in roots.values():
        path.mkdir(parents=True, exist_ok=True)
    return load_settings().model_copy(update={"layers": LayerPaths(**roots)})


def gate_on(run_dir: Path, gate_id: str, agent_id: str, options: list[str]) -> None:
    """Mot gate nam tren dia, cua mot agent bat ky."""
    directory = run_dir / "gates"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{gate_id}.json").write_text(
        json.dumps(
            {
                "gate_id": gate_id,
                "run_id": run_dir.name,
                "task_id": "t1",
                "agent_id": agent_id,
                "title": "duyet",
                "question": "duyet cai nao?",
                "options": [{"option_id": item, "label": item} for item in options],
                "payload": {},
                "result_hash": "abc",
                "created_at": NOW.isoformat(),
            }
        ),
        encoding="utf-8",
    )


def state_on(run_dir: Path) -> None:
    moment = NOW.isoformat()
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": run_dir.name,
                "phase": "PAUSED_AWAITING_APPROVAL",
                "tasks": {},
                "created_at": moment,
                "updated_at": moment,
            }
        ),
        encoding="utf-8",
    )


def test_a_question_does_not_stop_to_ask_which_claims_may_be_printed(tmp_path: Path) -> None:
    """Nguoi hoi mot cau hoi thi muon mot cau tra loi.

    Duoc dua nam ket luan, moi cai da kem trich dan metric cua chinh no, roi hoi
    "tich cai nao" la bi doi lam viec cua Manager - ma khong ai noi tich hay
    khong tich thi khac nhau cho nao.

    Goi thang vao ham noi bo vi duong cong khai `ask()` doi mot model that va
    mot bang da lam sach; cai can giu o day la chinh sach, va chinh sach nam
    tron trong ham nay.
    """
    settings = layers_in(tmp_path)
    run_dir = Path(settings.layers.runs) / "r_hoi"
    run_dir.mkdir(parents=True, exist_ok=True)
    state_on(run_dir)
    gate_on(run_dir, "gate_t2", "a7_analyst", ["f1", "f2"])

    assert Workspace(settings=settings)._approve_for_the_asker("r_hoi") is True

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert set(state["gates"]["gate_t2"]["approved"]) == {"f1", "f2"}
    # Ghi ro ai duyet va vi sao, de nhat ky khong lan mot quyet dinh cua may voi
    # mot quyet dinh cua nguoi.
    assert "Tu dong duyet" in state["gates"]["gate_t2"]["note"]


def test_the_cleaning_gate_is_never_approved_automatically(tmp_path: Path) -> None:
    # Gate nay dong vao DU LIEU cua nguoi dung. Hoi truoc khi sua la thu duoc
    # yeu cau tu dau, va no khong duoc bien mat cung voi cai gate kia.
    settings = layers_in(tmp_path)
    run_dir = Path(settings.layers.runs) / "r_sach"
    run_dir.mkdir(parents=True, exist_ok=True)
    state_on(run_dir)
    gate_on(run_dir, "gate_t3_clean", "a3_cleaner", ["trim_whitespace"])

    assert Workspace(settings=settings)._approve_for_the_asker("r_sach") is False

    # Khong ghi gi ca - ke ca khoa "gates", vi state chi duoc ghi lai khi that
    # su co mot quyet dinh. Khong co quyet dinh nao la dieu can giu o day.
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state.get("gates", {}) == {}
