"""catalogue.survey: mỗi bộ dữ liệu gốc, cùng mọi thứ sinh ra từ nó.

Viết trước khi chuyển catalogue.py sang domain mới (plans/refactor-ddd.md, Phase 0): trước
đó nó mới được phủ 37%, nên một lần chuyển làm gãy nó sẽ không ai hay.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from analysis_system.core.settings import LAYER_NAMES, LayerPaths, Settings, load_settings
from analysis_system.domains.data_ingestion.catalogue import Dataset, Derived, _run_of, survey


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    roots = {name: tmp_path / name for name in LAYER_NAMES}
    for root in roots.values():
        root.mkdir(parents=True, exist_ok=True)
    return load_settings().model_copy(update={"layers": LayerPaths(**roots)})


def put(root: Path, name: str, text: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def record_run(settings: Settings, run_id: str, source: str | None) -> None:
    state = {"source": {"path": source}} if source else {}
    put(Path(settings.layers.runs), f"{run_id}/state.json", json.dumps(state))


def by_name(settings: Settings) -> dict[str, Dataset]:
    return {dataset.name: dataset for dataset in survey(settings)}


def test_a_working_file_hangs_off_the_source_its_run_was_given(settings: Settings) -> None:
    put(Path(settings.layers.raw), "ban_hang.csv", "a,b\n1,2\n")
    record_run(settings, "em1", "raw://ban_hang.csv")
    put(Path(settings.layers.clean), "em1_clean.parquet", "xx")

    dataset = by_name(settings)["ban_hang"]
    assert dataset.source == "ban_hang.csv"
    assert [(item.path, item.layer, item.run_id) for item in dataset.derived] == [
        ("clean://em1_clean.parquet", "clean", "em1")
    ]
    assert dataset.total_bytes == len("a,b\n1,2\n") + 2


def test_a_question_run_belongs_to_the_dataset_of_the_run_it_was_asked_of(
    settings: Settings,
) -> None:
    put(Path(settings.layers.raw), "ban_hang.csv", "x")
    record_run(settings, "em1", "raw://ban_hang.csv")
    record_run(settings, "em1__q3", "clean://em1_clean.parquet")
    put(Path(settings.layers.clean), "em1__q3_bieu_do.png", "png")

    (chart,) = by_name(settings)["ban_hang"].charts
    # Khop run dai nhat: em1__q3, khong phai em1.
    assert chart.run_id == "em1__q3"
    assert chart.is_chart


def test_a_file_no_run_can_be_traced_to_still_appears_under_its_own_name(
    settings: Settings,
) -> None:
    put(Path(settings.layers.staging), "mo_coi.parquet", "abc")
    dataset = by_name(settings)["mo_coi"]
    assert dataset.source == ""
    assert [item.run_id for item in dataset.derived] == [""]


def test_a_run_whose_state_cannot_be_read_is_skipped(settings: Settings) -> None:
    put(Path(settings.layers.runs), "hong/state.json", "{khong phai json")
    record_run(settings, "khong_nguon", None)
    put(Path(settings.layers.raw), "a.csv", "1")
    assert list(by_name(settings)) == ["a"]


def test_the_biggest_dataset_comes_first(settings: Settings) -> None:
    put(Path(settings.layers.raw), "nho.csv", "1")
    put(Path(settings.layers.raw), "lon.csv", "1" * 50)
    assert [dataset.name for dataset in survey(settings)] == ["lon", "nho"]


def test_an_empty_world_has_no_datasets(tmp_path: Path) -> None:
    missing = {name: tmp_path / "khong_co" / name for name in LAYER_NAMES}
    settings = load_settings().model_copy(update={"layers": LayerPaths(**missing)})
    assert survey(settings) == []


def test_grouping_by_layer_keeps_every_file() -> None:
    dataset = Dataset(
        name="x",
        derived=[
            Derived(path="clean://a", layer="clean", size_bytes=1),
            Derived(path="mart://b", layer="mart", size_bytes=2),
            Derived(path="clean://c.png", layer="clean", size_bytes=3),
        ],
    )
    assert {layer: len(items) for layer, items in dataset.by_layer().items()} == {
        "clean": 2,
        "mart": 1,
    }
    assert [item.path for item in dataset.charts] == ["clean://c.png"]


def test_the_longest_run_id_wins() -> None:
    owners = {"em1": "a", "em1__q3": "a"}
    assert _run_of("em1__q3_findings.json", owners) == "em1__q3"
    assert _run_of("em1_clean.parquet", owners) == "em1"
    assert _run_of("khac.parquet", owners) == ""
