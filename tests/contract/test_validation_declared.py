"""Khong phep kiem nao chay khong phai la DAT - do la CHUA KIEM.

A5 runs the checks it is given and nothing else, which is right: inventing a
check is inventing a standard nobody agreed. But given none, it used to run
nothing, find nothing and report OK - so a run whose data was never checked
read exactly like one whose data was checked and held. Telling those two apart
is the whole job.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from analysis_system.agents.a5_validator import ValidatorAgent
from analysis_system.contracts.base import DataRef, ScopeToken, TaskRequest, TaskResult
from analysis_system.core import storage
from analysis_system.core.settings import LAYER_NAMES, LayerPaths, Settings, load_settings, resolve

MANIFEST_DIR = Path("config/manifests")
NOW = datetime.now(UTC)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    roots = {name: tmp_path / name for name in LAYER_NAMES}
    for root in roots.values():
        root.mkdir(parents=True, exist_ok=True)
    return load_settings().model_copy(update={"layers": LayerPaths(**roots)})


def tickets() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ma_phieu": ["P001", "P002", "P003"],
            "gio_xu_ly": [24.5, 13.0, 9.5],
        }
    )


def validate(settings: Settings, params: dict[str, Any]) -> TaskResult:
    storage.write_parquet(tickets(), resolve("mart://phieu.parquet", settings))
    scope = ScopeToken(
        run_id="r_val",
        task_id="t_val",
        agent_id="a5_validator",
        allow_read=("mart://**", "clean://**", "staging://**"),
        allow_write=("validation://**",),
        allow_tools=("pandas",),
        params=params,
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
    )
    ref = DataRef(path="mart://phieu.parquet", format="parquet", content_hash="a" * 64)
    agent = ValidatorAgent(settings, MANIFEST_DIR)
    return agent.run(
        TaskRequest(scope=scope, input_refs=(ref,), instruction="cham du lieu"), now=NOW
    )


def test_no_checks_parameter_at_all_already_failed_loudly(settings: Settings) -> None:
    # This half was right from the start. A test so it stays right.
    result = validate(settings, {})
    assert result.status == "FAILED"
    assert result.error is not None
    assert result.error.code == "NO_CHECKS"


def test_an_empty_checks_block_is_said_out_loud(settings: Settings) -> None:
    # The hole that was left: `checks` present but empty clears the guard
    # above, runs nothing, finds nothing and reports OK - so a run whose data
    # was never checked read exactly like one whose data was checked and held.
    result = validate(settings, {"checks": {}})
    assert result.status == "OK"
    assert result.metrics["checks_passed"] == 0.0
    assert any("KHONG CHAY PHEP KIEM NAO" in note for note in result.declined)


def test_the_note_says_what_is_missing(settings: Settings) -> None:
    # A person reading it needs to know what to do, not merely that something
    # is wrong.
    said = " ".join(validate(settings, {"checks": {}}).declined)
    assert "checks" in said
    assert "chua duoc kiem" in said


def test_declared_checks_that_pass_say_nothing_of_the_sort(settings: Settings) -> None:
    result = validate(settings, {"checks": {"not_null": ["ma_phieu"]}})
    assert result.status == "OK"
    assert result.metrics["checks_passed"] > 0
    assert not [note for note in result.declined if "KHONG CHAY PHEP KIEM" in note]


def test_a_declared_check_that_fails_is_a_verdict_not_a_gap(settings: Settings) -> None:
    # A failed check means the data broke a rule - a different thing entirely
    # from no rule having been applied.
    result = validate(settings, {"checks": {"ranges": [{"column": "gio_xu_ly", "min": 20.0}]}})
    assert result.metrics["checks_failed"] > 0
    assert not [note for note in result.declined if "KHONG CHAY PHEP KIEM" in note]


def test_the_planning_prompt_explains_how_to_declare_them() -> None:
    # The reason it was never set: `checks` appeared nowhere in the prompt, so
    # the Manager was being asked to fill in a field it had never been told
    # about - the same shape as inputs_from and dimensions before it.
    prompt = Path("prompts/manager_plan.md").read_text(encoding="utf-8")
    assert "checks.not_null" in prompt
    assert "Không khai gì thì nó không kiểm gì" in prompt
