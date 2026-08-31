"""Golden test: the committed fixture must always yield the same result.

This is where criterion S1 is proved. The fixture is read from git and never
regenerated here, so a change in this test means either the pipeline changed or
the fixture did - and both should be deliberate.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from analysis_system.pipeline.run import run_pipeline
from analysis_system.services import storage
from analysis_system.settings import LAYER_NAMES, LayerPaths, Settings, load_settings

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "bpi19_slice.csv"
EXPECTED = REPO_ROOT / "tests" / "golden" / "expected" / "pipeline.json"


def settings_in(tmp_path: Path) -> Settings:
    """Point every layer at a throwaway directory, keeping the real rules."""
    real = load_settings()
    roots = {name: tmp_path / name for name in LAYER_NAMES}
    for root in roots.values():
        root.mkdir(parents=True, exist_ok=True)
    return real.model_copy(update={"layers": LayerPaths(**roots)})


def expected() -> dict[str, Any]:
    """Read the recorded golden result."""
    if not EXPECTED.is_file():
        pytest.fail(f"Thieu ket qua ky vong: {EXPECTED}")
    loaded: dict[str, Any] = json.loads(EXPECTED.read_text(encoding="utf-8"))
    return loaded


def test_the_fixture_itself_has_not_changed() -> None:
    # The fixture is immutable by contract; anything else invalidates the rest.
    assert storage.sha256_file(FIXTURE) == expected()["fixture_sha256"]


def test_pipeline_matches_the_recorded_golden_result(tmp_path: Path) -> None:
    summary = run_pipeline(FIXTURE, settings_in(tmp_path), run_id="r_golden")
    want = expected()
    assert summary.rows_in == want["rows_in"]
    assert summary.rows_out == want["rows_out"]
    assert summary.validation.passed == want["validation_passed"]
    assert summary.validation.failed == want["validation_failed"]
    assert summary.staging_hash == want["staging_hash"]
    assert summary.clean_hash == want["clean_hash"]
    assert summary.report_hash == want["report_hash"]


def test_running_twice_produces_identical_hashes(tmp_path: Path) -> None:
    # Criterion S1. Different run ids and different output directories must not
    # change a single hash.
    first = run_pipeline(FIXTURE, settings_in(tmp_path / "one"), run_id="r_first")
    second = run_pipeline(FIXTURE, settings_in(tmp_path / "two"), run_id="r_second")
    assert first.staging_hash == second.staging_hash
    assert first.clean_hash == second.clean_hash
    assert first.report_hash == second.report_hash


def test_the_run_writes_all_three_artefacts(tmp_path: Path) -> None:
    summary = run_pipeline(FIXTURE, settings_in(tmp_path), run_id="r_paths")
    assert summary.staging_path.is_file()
    assert summary.clean_path.is_file()
    assert summary.report_path.is_file()


def test_validation_passes_on_the_fixture(tmp_path: Path) -> None:
    summary = run_pipeline(FIXTURE, settings_in(tmp_path), run_id="r_ok")
    assert summary.is_ok, [failure.detail for failure in summary.validation.failures]
