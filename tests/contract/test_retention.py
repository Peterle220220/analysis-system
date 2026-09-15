"""Don dep: liet ke truoc, xoa sau, va khong bao gio dung toi du lieu goc."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from analysis_system.core import storage
from analysis_system.core.retention import (
    all_but_newest,
    belongings,
    forget,
    orphaned_by,
    runs,
)
from analysis_system.core.settings import LAYER_NAMES, LayerPaths, Settings, load_settings, resolve


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    roots = {name: tmp_path / name for name in LAYER_NAMES}
    for root in roots.values():
        root.mkdir(parents=True, exist_ok=True)
    return load_settings().model_copy(update={"layers": LayerPaths(**roots)})


def make_run(settings: Settings, run_id: str, phase: str = "COMPLETED") -> None:
    """Mot lan chay: thu muc trang thai, mot bang mart, mot artefact."""
    run_dir = Path(settings.layers.runs) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "state.json").write_text(
        json.dumps({"run_id": run_id, "phase": phase, "tasks": {"t1": {}}}), encoding="utf-8"
    )
    storage.write_parquet(
        pd.DataFrame({"a": [1, 2]}), resolve(f"mart://{run_id}_t1_out.parquet", settings)
    )
    resolve(f"artifacts://{run_id}_t1_findings.json", settings).write_text("{}", encoding="utf-8")


# --- what a run owns ------------------------------------------------------------


def test_a_run_owns_the_files_named_after_it(settings: Settings) -> None:
    make_run(settings, "r_one")
    owned = {path.name for path in belongings(settings, "r_one")}
    assert "r_one" in owned
    assert "r_one_t1_out.parquet" in owned
    assert "r_one_t1_findings.json" in owned


def test_a_run_does_not_own_the_data_itself(settings: Settings) -> None:
    # clean://emotions.parquet is the dataset, not one run's working paper. It
    # carries no run id, and that is exactly what tells them apart.
    make_run(settings, "r_one")
    storage.write_parquet(pd.DataFrame({"a": [1]}), resolve("clean://emotions.parquet", settings))
    owned = {path.name for path in belongings(settings, "r_one")}
    assert "emotions.parquet" not in owned


def test_one_run_never_owns_another_runs_files(settings: Settings) -> None:
    make_run(settings, "r_one")
    make_run(settings, "r_one_two")
    owned = {path.name for path in belongings(settings, "r_one")}
    assert "r_one_two" not in owned


# --- listing ---------------------------------------------------------------------


def test_every_run_is_listed_with_what_it_costs(settings: Settings) -> None:
    make_run(settings, "r_one")
    make_run(settings, "r_two", phase="HALTED")
    listed = {run.run_id: run for run in runs(settings)}
    assert set(listed) == {"r_one", "r_two"}
    assert listed["r_two"].phase == "HALTED"
    assert listed["r_one"].files == 3
    assert listed["r_one"].bytes_used > 0


def test_a_run_with_unreadable_state_is_still_listed(settings: Settings) -> None:
    # A half-written state file must not hide a run from the person trying to
    # clear space - that is the run they most want to see.
    make_run(settings, "r_broken")
    (Path(settings.layers.runs) / "r_broken" / "state.json").write_text("{", encoding="utf-8")
    assert [run.phase for run in runs(settings)] == ["?"]


def test_keeping_the_newest_leaves_exactly_that_many(settings: Settings) -> None:
    for index in range(5):
        make_run(settings, f"r_{index}")
    assert len(all_but_newest(settings, 2)) == 3
    assert len(all_but_newest(settings, 0)) == 5


# --- deleting ---------------------------------------------------------------------


def test_forgetting_a_run_removes_everything_it_owns(settings: Settings) -> None:
    make_run(settings, "r_one")
    make_run(settings, "r_two")
    removed, freed = forget(settings, ["r_one"])
    assert removed == 3
    assert freed > 0
    assert not (Path(settings.layers.runs) / "r_one").exists()
    assert not resolve("mart://r_one_t1_out.parquet", settings).exists()
    # The other run is untouched.
    assert (Path(settings.layers.runs) / "r_two").exists()


def test_forgetting_never_touches_the_raw_layer(settings: Settings) -> None:
    # raw holds what the person gave us. No run owns it, and losing it would
    # mean losing something the system cannot recreate.
    make_run(settings, "r_one")
    source = resolve("raw://r_one_goc.csv", settings)
    source.write_text("a\n1\n", encoding="utf-8")
    forget(settings, ["r_one"])
    assert source.is_file()


def test_forgetting_a_run_that_is_not_there_is_not_an_error(settings: Settings) -> None:
    assert forget(settings, ["khong_co"]) == (0, 0)


def test_forgetting_a_parent_that_still_has_questions_is_flagged(settings: Settings) -> None:
    # Learned minutes after this was written: keeping the fifteen newest runs
    # kept fifteen questions and deleted the cleaning run all of them were
    # asked of. The questions survived and became unanswerable.
    make_run(settings, "em1")
    make_run(settings, "em1__q1")
    make_run(settings, "em1__q2")
    assert orphaned_by(settings, ["em1"]) == {"em1": ["em1__q1", "em1__q2"]}


def test_forgetting_the_whole_family_orphans_nobody(settings: Settings) -> None:
    make_run(settings, "em1")
    make_run(settings, "em1__q1")
    assert orphaned_by(settings, ["em1", "em1__q1"]) == {}


def test_a_similar_name_is_not_a_child(settings: Settings) -> None:
    # "em10" is its own run, not a question asked of "em1".
    make_run(settings, "em1")
    make_run(settings, "em10")
    assert orphaned_by(settings, ["em1"]) == {}
