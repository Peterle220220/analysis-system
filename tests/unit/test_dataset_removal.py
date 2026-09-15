"""Xoa mot bo du lieu: moi thu cua no di, khong mot tep nao cua bo khac di theo."""

from __future__ import annotations

from pathlib import Path

import pytest

from analysis_system.core.settings import LAYER_NAMES, LayerPaths, Settings, load_settings
from analysis_system.domains.data_ingestion.dataset_labels import read_labels, record_label
from analysis_system.domains.data_ingestion.dataset_origin import read_origins, record_origin
from analysis_system.domains.data_ingestion.dataset_removal import (
    belongings,
    forget,
    owner,
    runs_of,
)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    roots = {name: tmp_path / name for name in LAYER_NAMES}
    for root in roots.values():
        root.mkdir(parents=True, exist_ok=True)
    return load_settings().model_copy(update={"layers": LayerPaths(**roots)})


def put(settings: Settings, layer: str, *names: str) -> list[Path]:
    root = Path(getattr(settings.layers, layer))
    made = []
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
        made.append(path)
    return made


def two_datasets(settings: Settings) -> tuple[list[Path], list[Path]]:
    """Hai bo chung tien to "don_hang_", nhu mot nguoi dat ten that van hay lam."""
    short = [
        *put(settings, "raw", "don_hang.csv"),
        *put(settings, "runs", "don_hang/state.json", "don_hang__q1/state.json"),
        *put(settings, "staging", "don_hang_don_hang.parquet"),
        *put(settings, "profile", "don_hang_profile.json"),
        *put(settings, "clean", "don_hang.parquet"),
        *put(settings, "mart", "don_hang__q1_t1_loc.parquet"),
        *put(settings, "artifacts", "don_hang__q1_answer.json", "report/don_hang__q1.html"),
    ]
    long = [
        *put(settings, "raw", "don_hang_quy_3.xlsx"),
        *put(settings, "runs", "don_hang_quy_3/state.json", "don_hang_quy_3__q1/state.json"),
        *put(settings, "staging", "don_hang_quy_3_don_hang_quy_3.parquet"),
        *put(settings, "profile", "don_hang_quy_3_profile.json"),
        *put(settings, "clean", "don_hang_quy_3.parquet"),
        *put(settings, "artifacts", "report/don_hang_quy_3__q1.html"),
    ]
    runs_root = Path(settings.layers.runs)
    record_origin(runs_root, "don_hang", "du_lieu")
    record_origin(runs_root, "don_hang_quy_3", "tu_phan_tich")
    return short, long


def test_deleting_a_dataset_takes_everything_of_it_and_nothing_of_its_neighbour(
    settings: Settings,
) -> None:
    short, long = two_datasets(settings)
    bystanders = [
        *put(settings, "clean", "events.parquet"),
        *put(settings, "artifacts", ".api_requests/upload_don_hang.json"),
    ]
    assert runs_of(settings, "don_hang") == ["don_hang", "don_hang__q1"]

    removed, freed = forget(settings, "don_hang")

    assert removed == 9  # hai thu muc chay + bay tep
    assert freed > 0
    assert not any(path.exists() for path in short)
    assert all(path.exists() for path in [*long, *bystanders])
    assert read_origins(Path(settings.layers.runs)) == {"don_hang_quy_3": "tu_phan_tich"}


def test_the_longer_name_can_be_deleted_without_touching_the_shorter(settings: Settings) -> None:
    short, long = two_datasets(settings)
    forget(settings, "don_hang_quy_3")
    assert not any(path.exists() for path in long)
    assert all(path.exists() for path in short)


def test_a_dataset_known_only_by_its_clean_table_keeps_its_files(settings: Settings) -> None:
    # Bo "a_b" da mat thu muc chay va tep goc, nhung bang sach cua no van la cua no.
    kept = [*put(settings, "clean", "a_b.parquet"), *put(settings, "profile", "a_b_profile.json")]
    gone = put(settings, "raw", "a.csv")
    forget(settings, "a")
    assert all(path.exists() for path in kept)
    assert not any(path.exists() for path in gone)


def test_the_display_name_goes_with_the_dataset(settings: Settings) -> None:
    put(settings, "raw", "hong.xls")
    record_label(Path(settings.layers.runs), "hong", "Tệp hỏng")
    record_label(Path(settings.layers.runs), "khac", "Bộ khác")
    forget(settings, "hong")
    assert read_labels(Path(settings.layers.runs)) == {"khac": "Bộ khác"}


def test_a_failed_upload_with_only_a_raw_file_can_be_deleted(settings: Settings) -> None:
    raw = put(settings, "raw", "hong.xls")
    assert belongings(settings, "hong") == raw
    assert forget(settings, "hong") == (1, 1)


@pytest.mark.parametrize("name", ["", "bo__q1", "../raw", ".an"])
def test_a_name_that_is_not_a_dataset_is_refused(settings: Settings, name: str) -> None:
    put(settings, "raw", "bo.csv")
    with pytest.raises(ValueError, match="khong phai ten"):
        forget(settings, name)
    assert (Path(settings.layers.raw) / "bo.csv").exists()


def test_owner_picks_the_longest_matching_dataset() -> None:
    known = {"a", "a_b", "report"}
    assert owner("a_b_profile.json", known) == "a_b"
    assert owner("a_c.parquet", known) == "a"
    assert owner("a.parquet", known) == "a"
    assert owner("ab.parquet", known) == ""
