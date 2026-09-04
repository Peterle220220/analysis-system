"""Xem va don nhung gi mot lan chay de lai.

Every run writes a directory of state and a scattering of artefacts named after
it, and until now nothing ever removed any of it. Ninety-four runs accumulated
during one week of testing, and the count only ever goes up: a system somebody
uses daily would bury them under its own working papers.

Two rules shape this module.

**A run's leavings are the files named after it, and nothing else.** The cleaned
table `clean://emotions.parquet` is the data itself and survives every run that
reads it; `mart://em1__q9_t2_output.parquet` is one run's working paper. The
prefix is what tells them apart, which is the reason artefact names carry the
run id in the first place.

**Nothing is deleted without being listed first.** `plan()` says what would go;
removing it is a second, explicit act. A retention rule that quietly ate the
wrong week's evidence would be worse than no retention rule at all.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from analysis_system.settings import Settings

# The layers a run writes working papers into. `raw` is never touched - it holds
# what the person gave us, and no run owns it.
WORKING_LAYERS: tuple[str, ...] = (
    "staging",
    "profile",
    "clean",
    "mart",
    "validation",
    "artifacts",
    "extracted",
)


@dataclass(frozen=True)
class RunInfo:
    """One run, as somebody deciding whether to keep it would want to see it."""

    run_id: str
    started: datetime
    phase: str
    tasks: int
    files: int
    bytes_used: int

    @property
    def age_days(self) -> int:
        """How many whole days ago this run started."""
        return max(0, (datetime.now(UTC) - self.started).days)


def _size(paths: list[Path]) -> int:
    total = 0
    for path in paths:
        if path.is_dir():
            total += sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
        elif path.is_file():
            total += path.stat().st_size
    return total


def belongings(settings: Settings, run_id: str) -> list[Path]:
    """Every path that exists because of this run.

    The run directory, plus files in the working layers whose name begins with
    the run id. A file named after a different run that merely mentions this one
    is not this run's to delete.
    """
    found: list[Path] = []
    run_dir = Path(settings.layers.runs) / run_id
    if run_dir.is_dir():
        found.append(run_dir)
    for layer in WORKING_LAYERS:
        root = Path(getattr(settings.layers, layer, "") or "")
        if not root.is_dir():
            continue
        found.extend(sorted(path for path in root.glob(f"{run_id}_*") if path.is_file()))
    return found


def _started(run_dir: Path) -> datetime:
    """When the run began, from its own state rather than from the clock."""
    state = run_dir / "state.json"
    source = state if state.is_file() else run_dir
    return datetime.fromtimestamp(source.stat().st_mtime, tz=UTC)


def runs(settings: Settings) -> list[RunInfo]:
    """Every run on disk, newest first."""
    root = Path(settings.layers.runs)
    if not root.is_dir():
        return []
    found: list[RunInfo] = []
    for run_dir in root.iterdir():
        if not run_dir.is_dir():
            continue
        phase, tasks = _phase_of(run_dir)
        owned = belongings(settings, run_dir.name)
        found.append(
            RunInfo(
                run_id=run_dir.name,
                started=_started(run_dir),
                phase=phase,
                tasks=tasks,
                files=len(owned),
                bytes_used=_size(owned),
            )
        )
    return sorted(found, key=lambda run: run.started, reverse=True)


def _phase_of(run_dir: Path) -> tuple[str, int]:
    """The run's phase and task count, read cheaply and never fatally."""
    import json

    state = run_dir / "state.json"
    if not state.is_file():
        return "?", 0
    try:
        data = json.loads(state.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return "?", 0
    return str(data.get("phase") or "?"), len(data.get("tasks") or {})


def older_than(settings: Settings, days: int) -> list[RunInfo]:
    """Runs that started more than `days` days ago."""
    return [run for run in runs(settings) if run.age_days >= days]


def all_but_newest(settings: Settings, keep: int) -> list[RunInfo]:
    """Every run except the `keep` most recent."""
    return runs(settings)[max(keep, 0) :]


def forget(settings: Settings, run_ids: list[str]) -> tuple[int, int]:
    """Delete these runs and everything named after them.

    Returns:
        How many paths were removed, and how many bytes that freed.

    Raises:
        OSError: a path could not be removed. Nothing is swallowed - a run
            reported as gone must actually be gone.
    """
    removed = 0
    freed = 0
    for run_id in run_ids:
        for path in belongings(settings, run_id):
            freed += _size([path])
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            removed += 1
    return removed, freed
