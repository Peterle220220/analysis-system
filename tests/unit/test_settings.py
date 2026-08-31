"""Tests for configuration loading, layer URI resolution and the startup check."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from analysis_system.settings import (
    DEFAULT_CONFIG_PATH,
    LAYER_NAMES,
    REPO_ROOT,
    ConfigError,
    cassette_path,
    expand_path,
    load_settings,
    resolve,
    verify_layers,
)


def _write_config(tmp_path: Path, *, create_dirs: bool = True) -> Path:
    """Write a settings file whose layers live under tmp_path."""
    layers: dict[str, str] = {}
    for name in LAYER_NAMES:
        directory = tmp_path / "data" / name
        if create_dirs:
            directory.mkdir(parents=True)
        layers[name] = str(directory)
    config = {
        "layers": layers,
        "cleaning": {"assume_timezone": "UTC"},
        "validation": {"max_rows_dropped_pct": 5.0},
    }
    path = tmp_path / "settings.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return path


def test_load_settings_reads_every_layer(tmp_path: Path) -> None:
    settings = load_settings(_write_config(tmp_path))
    for name in LAYER_NAMES:
        assert settings.layers.root_of(name) == tmp_path / "data" / name
    assert settings.cleaning.assume_timezone == "UTC"


def test_load_settings_missing_file_names_the_path(tmp_path: Path) -> None:
    missing = tmp_path / "khong-ton-tai.yaml"
    with pytest.raises(ConfigError) as error:
        load_settings(missing)
    assert str(missing) in str(error.value)


def test_resolve_maps_layer_uri_to_path(tmp_path: Path) -> None:
    settings = load_settings(_write_config(tmp_path))
    resolved = resolve("staging://events.parquet", settings)
    assert resolved == tmp_path / "data" / "staging" / "events.parquet"


def test_resolve_rejects_unknown_layer(tmp_path: Path) -> None:
    settings = load_settings(_write_config(tmp_path))
    with pytest.raises(ConfigError):
        resolve("khong_co_tang://x.parquet", settings)


def test_resolve_rejects_escaping_the_layer_root(tmp_path: Path) -> None:
    settings = load_settings(_write_config(tmp_path))
    with pytest.raises(ConfigError):
        resolve("staging://../clean/stolen.parquet", settings)


def test_resolve_rejects_absolute_path(tmp_path: Path) -> None:
    settings = load_settings(_write_config(tmp_path))
    with pytest.raises(ConfigError):
        resolve("staging:///etc/passwd", settings)


def test_verify_layers_passes_when_every_layer_exists(tmp_path: Path) -> None:
    settings = load_settings(_write_config(tmp_path))
    verify_layers(settings)


def test_verify_layers_reports_missing_layer_and_creates_nothing(tmp_path: Path) -> None:
    settings = load_settings(_write_config(tmp_path, create_dirs=False))
    with pytest.raises(ConfigError) as error:
        verify_layers(settings)
    message = str(error.value)
    assert "staging" in message
    # The check must never silently repair the configuration.
    assert not (tmp_path / "data").exists()


# --- portable paths -----------------------------------------------------------


def test_a_configured_path_reads_an_environment_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANALYSIS_DATA", "/srv/du-lieu")
    assert expand_path("${ANALYSIS_DATA}/raw") == Path("/srv/du-lieu/raw")


def test_an_unset_variable_falls_back_to_its_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANALYSIS_RUNS", raising=False)
    assert expand_path("${ANALYSIS_RUNS}") == Path.home() / "analysis-runs"


def test_an_empty_variable_falls_back_too(monkeypatch: pytest.MonkeyPatch) -> None:
    # Otherwise ${ANALYSIS_DATA}/raw would expand to /raw and write into the
    # filesystem root.
    monkeypatch.setenv("ANALYSIS_DATA", "")
    assert expand_path("${ANALYSIS_DATA}/raw") == Path.home() / "analysis-data" / "raw"


def test_a_variable_nothing_defines_is_an_error() -> None:
    with pytest.raises(ConfigError, match="khong duoc dat"):
        expand_path("${KHONG_AI_DAT_BIEN_NAY}/raw")


def test_a_home_shortcut_is_expanded() -> None:
    assert expand_path("~/du-lieu") == Path.home() / "du-lieu"


def test_a_plain_absolute_path_is_left_alone() -> None:
    assert expand_path("/srv/du-lieu/raw") == Path("/srv/du-lieu/raw")


def test_the_committed_configuration_names_no_machine() -> None:
    # A config file in git that names one home directory cannot be deployed.
    text = DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")
    layers = text.split("layers:")[1].split("cleaning:")[0]
    assert "/home/" not in layers
    assert "${ANALYSIS_DATA}" in layers


def test_the_settings_file_loads_with_the_paths_expanded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANALYSIS_DATA", str(tmp_path / "du-lieu"))
    monkeypatch.setenv("ANALYSIS_RUNS", str(tmp_path / "lan-chay"))
    loaded = load_settings()
    assert loaded.layers.raw == tmp_path / "du-lieu" / "raw"
    assert loaded.layers.runs == tmp_path / "lan-chay"


def test_a_relative_cassette_directory_is_read_from_the_repository() -> None:
    # Not from wherever the operator happened to be standing.
    settings = load_settings()
    assert cassette_path(settings).is_absolute()
    assert cassette_path(settings) == REPO_ROOT / "tests" / "cassettes"
