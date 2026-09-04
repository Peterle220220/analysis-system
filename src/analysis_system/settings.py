"""Configuration: independent per-layer paths, resolved from config/settings.yaml.

Every layer is declared on its own so a single layer can later be pointed at a
different disk without touching code. Paths are never derived from one shared
root, and this module never creates a directory that is missing.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

LAYER_NAMES: Final[tuple[str, ...]] = (
    "raw",
    "extracted",
    "staging",
    "clean",
    "mart",
    "profile",
    "validation",
    "artifacts",
    "runs",
)

ROOT_ENV_VAR: Final[str] = "ANALYSIS_SYSTEM_ROOT"
# Directories that ship with the code but are read at run time, not imported.
RESOURCE_DIRS: Final[tuple[str, ...]] = ("config", "prompts")


def resource_root() -> Path:
    """Where config/ and prompts/ live.

    Looked up rather than assumed. The old assumption - two directories up from
    this file - holds only while the package sits in its source checkout, and
    points into site-packages once it is installed properly. A container is
    where that first matters, and where it would otherwise surface as a missing
    prompt rather than a missing prompt *directory*.

    Order: an explicit setting, the checkout this file sits in, the working
    directory. Never raises: a resolver that can abort a module import turns a
    misconfiguration into a traceback about something unrelated.
    """
    source_tree = Path(__file__).resolve().parents[2]
    declared = os.environ.get(ROOT_ENV_VAR)
    candidates = [Path(declared)] if declared else []
    candidates += [source_tree, Path.cwd()]
    for candidate in candidates:
        if all((candidate / name).is_dir() for name in RESOURCE_DIRS):
            return candidate
    return source_tree


REPO_ROOT: Final[Path] = resource_root()
DEFAULT_CONFIG_PATH: Final[Path] = REPO_ROOT / "config" / "settings.yaml"

_URI_SEPARATOR: Final[str] = "://"

# Where the data lives is a property of the machine, not of the project. The
# config file names these instead of a home directory, so the same file works on
# a laptop and on a server without being edited.
ENV_DEFAULTS: Final[Mapping[str, str]] = {
    "ANALYSIS_DATA": "~/analysis-data",
    "ANALYSIS_RUNS": "~/analysis-runs",
}

_PLACEHOLDER: Final[re.Pattern[str]] = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ConfigError(RuntimeError):
    """The configuration is missing, malformed, or points somewhere unusable."""


class LayerPaths(BaseModel):
    """Absolute filesystem root of every storage layer."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    raw: Path
    extracted: Path
    staging: Path
    clean: Path
    mart: Path
    profile: Path
    validation: Path
    artifacts: Path
    runs: Path

    def root_of(self, layer: str) -> Path:
        """Return the root directory of one layer.

        Raises:
            ConfigError: the layer name is not one of LAYER_NAMES.
        """
        if layer not in LAYER_NAMES:
            known = ", ".join(LAYER_NAMES)
            raise ConfigError(f"Tang khong hop le: {layer!r}. Cac tang hop le: {known}")
        value = getattr(self, layer)
        if not isinstance(value, Path):  # pragma: no cover - pydantic guarantees this
            raise ConfigError(f"Tang {layer!r} khong phai duong dan.")
        return value


class CleaningSettings(BaseModel):
    """Parameters the cleaning rules are not allowed to guess.

    Which columns each rule touches is configuration, not a constant buried in
    code: a different event log means different column names, not a code change.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    assume_timezone: str
    datetime_columns: tuple[str, ...] = ()
    numeric_columns: tuple[str, ...] = ()
    required_columns: tuple[str, ...] = ()


class ValidationSettings(BaseModel):
    """The contract the cleaned frame must satisfy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_rows_dropped_pct: float
    not_null_columns: tuple[str, ...] = ()
    unique_together: tuple[tuple[str, ...], ...] = ()


class LlmSettings(BaseModel):
    """Which model provider the run uses, and which model.

    The provider is what decides whether a run costs money at all:

    handoff  - the prompt is written out for a person to run on a subscription
    cassette - a recorded answer is replayed
    gemini   - the Gemini API is called; the free tier costs nothing but trains
               on what it is sent, so it belongs on the public fixture and not
               on client data
    anthropic- the API is called, and billed
    none     - no model; agents fall back to code-only behaviour
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str = "handoff"
    manager_model: str = "claude-opus-5"
    worker_model: str = "claude-sonnet-5"
    # Named separately because it is a different vendor's namespace, not a
    # cheaper Claude. Swapping vendors must not mean editing two things.
    gemini_model: str = "gemini-3.7-flash"
    # The model an agent gets when its manifest names none. Per-skill
    # choice lives in the manifests; this is only the fallback.
    openrouter_model: str = "dots-studio/dots-3-note-preview:free"
    # The Manager's own model, used for planning and for the final synthesis.
    #
    # Separate from `openrouter_model` because those two roles are not alike.
    # A worker fills in a declared shape from figures already handed to it; the
    # Manager decides which agents run, in what order, and what each reads from
    # which - the hardest reasoning in the system. Sharing one setting meant the
    # planner ran on whatever was cheap enough for the workers, and it showed:
    # a two-step plan came back unwired three times running.
    #
    # Empty falls back to `openrouter_model`, so nothing breaks by default.
    planner_model: str = ""
    # How much internal reasoning to ask for. Low by default: these tasks fill a
    # declared shape from data already supplied, and whether the answer is any
    # good is decided afterwards by code, not by how long the model thought.
    gemini_thinking: str = "low"
    dev_mode: bool = True
    cassette_dir: str = "tests/cassettes"

    @property
    def active_model(self) -> str:
        """Model actually used. dev_mode forces both roles onto the cheaper one."""
        return self.worker_model if self.dev_mode else self.manager_model

    @property
    def costs_money(self) -> bool:
        """True only for the provider that actually calls the API."""
        return self.provider == "anthropic"


class Settings(BaseModel):
    """The whole configuration file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    layers: LayerPaths
    cleaning: CleaningSettings
    validation: ValidationSettings
    llm: LlmSettings = LlmSettings()


def load_settings(path: Path | None = None) -> Settings:
    """Read and validate config/settings.yaml.

    Args:
        path: configuration file to read; defaults to the repository copy.

    Returns:
        The validated settings.

    Raises:
        ConfigError: the file is missing, is not valid YAML, or fails validation.
    """
    config_path = path or DEFAULT_CONFIG_PATH
    if not config_path.is_file():
        raise ConfigError(f"Khong tim thay file cau hinh: {config_path}")
    try:
        raw_text = config_path.read_text(encoding="utf-8")
        parsed = yaml.safe_load(raw_text)
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"Khong doc duoc file cau hinh {config_path}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ConfigError(f"File cau hinh {config_path} phai la mot mapping YAML.")
    try:
        return Settings.model_validate(_expand_layers(parsed))
    except ValidationError as exc:
        raise ConfigError(f"Cau hinh {config_path} khong hop le:\n{exc}") from exc


def expand_path(value: str) -> Path:
    """Resolve ${VAR} and ~ in a configured path.

    An unset variable falls back to the default declared in ENV_DEFAULTS. A
    variable with neither is an error, never an empty string: silently expanding
    ``${ANALYSIS_DATA}/raw`` to ``/raw`` would write into the filesystem root.

    Raises:
        ConfigError: the path refers to a variable nothing defines.
    """

    def substitute(match: re.Match[str]) -> str:
        name = match.group(1)
        found = os.environ.get(name) or ENV_DEFAULTS.get(name)
        if not found:
            known = ", ".join(sorted(ENV_DEFAULTS))
            raise ConfigError(
                f"Duong dan dung bien {name!r} nhung bien do khong duoc dat va khong co "
                f"gia tri mac dinh. Bien co san: {known}"
            )
        return found

    return Path(_PLACEHOLDER.sub(substitute, value)).expanduser()


def _expand_layers(parsed: dict[str, Any]) -> dict[str, Any]:
    """Expand every layer path before the settings are validated."""
    layers = parsed.get("layers")
    if not isinstance(layers, dict):
        return parsed
    expanded = {
        name: (str(expand_path(value)) if isinstance(value, str) else value)
        for name, value in layers.items()
    }
    return {**parsed, "layers": expanded}


def cassette_path(settings: Settings) -> Path:
    """Where recorded model answers live.

    A relative path is relative to the repository, not to wherever the operator
    happened to be standing when they ran the command.
    """
    declared = expand_path(settings.llm.cassette_dir)
    return declared if declared.is_absolute() else REPO_ROOT / declared


def resolve(uri: str, settings: Settings) -> Path:
    """Resolve a logical layer URI such as 'staging://events.parquet' to a path.

    Args:
        uri: '<layer>://<relative path>'.
        settings: the loaded settings supplying every layer root.

    Returns:
        The absolute path the URI denotes.

    Raises:
        ConfigError: the URI is malformed, names an unknown layer, or escapes
            its layer root.
    """
    if _URI_SEPARATOR not in uri:
        raise ConfigError(f"URI khong hop le: {uri!r}. Dinh dang dung la 'tang://duong/dan'.")
    layer, _, relative = uri.partition(_URI_SEPARATOR)
    if not relative:
        raise ConfigError(f"URI {uri!r} thieu phan duong dan sau '{_URI_SEPARATOR}'.")
    if relative.startswith("/"):
        raise ConfigError(f"URI {uri!r} khong duoc dung duong dan tuyet doi.")
    root = settings.layers.root_of(layer)
    candidate = (root / relative).resolve()
    root_resolved = root.resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise ConfigError(f"URI {uri!r} tro ra ngoai tang {layer!r}.")
    return candidate


def verify_layers(settings: Settings) -> None:
    """Fail fast when a declared layer is unreachable.

    Never creates a directory and never falls back to an empty one: a missing
    layer is a configuration error the user must fix.

    Raises:
        ConfigError: at least one layer does not exist or is not a directory.
    """
    problems: list[str] = []
    for layer in LAYER_NAMES:
        root = settings.layers.root_of(layer)
        if not root.exists():
            problems.append(f"  - {layer:<11} khong ton tai: {root}")
        elif not root.is_dir():
            problems.append(f"  - {layer:<11} khong phai thu muc: {root}")
    if problems:
        raise ConfigError(
            "Cau hinh tang du lieu khong dung. Tao cac thu muc sau roi chay lai:\n"
            + "\n".join(problems)
        )
