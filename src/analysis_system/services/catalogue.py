"""Moi bo du lieu goc, va tat ca nhung gi sinh ra tu no.

The layers answer *what kind of thing is this* - raw, clean, mart, artifacts -
and that is what the boundary needs: an agent may read `clean://` and not
`raw://`, and the prefix is how that is said.

It is not what a person needs. Somebody looking at eight folders with forty
files spread across them cannot tell which clean table came from which source,
or which chart belongs to which question. The layers are how the *system* sees
the data; this is how a *person* does.

Nothing here moves a file. The grouping is worked out from what is already
written down - a run records its source, and every working file carries the id
of the run that made it - so the same files answer both views at once.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from analysis_system.services.retention import WORKING_LAYERS
from analysis_system.settings import Settings

# What each layer holds, said the way somebody would say it out loud rather
# than the way the code names it.
MEANS: Final[dict[str, str]] = {
    "staging": "bang tho vua doc vao",
    "clean": "du lieu sach",
    "mart": "bang de phan tich",
    "profile": "ho so mo ta du lieu",
    "validation": "ket qua cham du lieu",
    "artifacts": "ket luan, bieu do, bao cao",
    "extracted": "van ban trich tu tai lieu",
}

# Files whose name says what they are, and that a person looks for by name.
CHART_SUFFIX: Final[str] = ".png"


@dataclass
class Derived:
    """One file that came out of working on a dataset."""

    path: str
    layer: str
    size_bytes: int
    run_id: str = ""

    @property
    def is_chart(self) -> bool:
        """True for a picture, which is what somebody scanning a list wants first."""
        return self.path.endswith(CHART_SUFFIX)


@dataclass
class Dataset:
    """One source file, and everything the system has made from it."""

    name: str
    source: str = ""
    source_bytes: int = 0
    derived: list[Derived] = field(default_factory=list)

    @property
    def total_bytes(self) -> int:
        """Source plus everything made from it."""
        return self.source_bytes + sum(item.size_bytes for item in self.derived)

    def by_layer(self) -> dict[str, list[Derived]]:
        """What was made, grouped by what kind of thing it is."""
        grouped: dict[str, list[Derived]] = {}
        for item in self.derived:
            grouped.setdefault(item.layer, []).append(item)
        return grouped

    @property
    def charts(self) -> list[Derived]:
        """Just the pictures."""
        return [item for item in self.derived if item.is_chart]


def _stem(name: str) -> str:
    """The dataset a file name belongs to, before any extension."""
    return Path(name).stem


def _runs_by_dataset(settings: Settings) -> dict[str, str]:
    """Which dataset each run was working on.

    Read from the run's own state, which records the source it was given. A
    question run is named after the cleaning run it was asked of, so the
    prefix carries the answer even when the question run recorded nothing.
    """
    import json

    root = Path(settings.layers.runs)
    found: dict[str, str] = {}
    if not root.is_dir():
        return found
    for run_dir in sorted(root.iterdir()):
        state = run_dir / "state.json"
        if not state.is_file():
            continue
        try:
            data = json.loads(state.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        source = (data.get("source") or {}).get("path") or ""
        if source:
            found[run_dir.name] = _stem(source.partition("://")[2])
    # A question run inherits its parent's dataset: `em1__q3` came from `em1`.
    for run_id in sorted(found):
        parent, mark, _ = run_id.partition("__")
        if mark and parent in found:
            found[run_id] = found[parent]
    return found


def survey(settings: Settings) -> list[Dataset]:
    """Every source file, with everything made from it hanging off it.

    A working file whose run cannot be traced still appears, under the dataset
    its own name points at. Dropping it would hide exactly the file somebody is
    hunting for.
    """
    datasets: dict[str, Dataset] = {}

    raw = Path(settings.layers.raw)
    if raw.is_dir():
        for path in sorted(raw.iterdir()):
            if path.is_file():
                name = _stem(path.name)
                datasets[name] = Dataset(
                    name=name, source=path.name, source_bytes=path.stat().st_size
                )

    owners = _runs_by_dataset(settings)
    for layer in WORKING_LAYERS:
        root = Path(getattr(settings.layers, layer, "") or "")
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            run_id = _run_of(path.name, owners)
            name = owners.get(run_id, "") or _stem(path.name)
            dataset = datasets.setdefault(name, Dataset(name=name))
            dataset.derived.append(
                Derived(
                    path=f"{layer}://{path.relative_to(root)}",
                    layer=layer,
                    size_bytes=path.stat().st_size,
                    run_id=run_id,
                )
            )

    return sorted(datasets.values(), key=lambda item: (-item.total_bytes, item.name))


def _run_of(filename: str, owners: dict[str, str]) -> str:
    """The run that wrote this file, from the run id its name begins with.

    Longest first, so `em1__q3_findings.json` is matched by `em1__q3` and not
    by `em1` - the parent would put every question's working files under the
    cleaning run and lose which question produced what.
    """
    for run_id in sorted(owners, key=len, reverse=True):
        if filename.startswith(run_id + "_"):
            return run_id
    return ""
