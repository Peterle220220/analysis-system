"""Loads prompt files from prompts/.

Prompts live in their own files, versioned like code, so a change to one shows
up in review as a diff rather than hiding inside a string literal. Agents cannot
read files themselves, so they come through here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from analysis_system.services import storage
from analysis_system.settings import resource_root

PROMPT_DIR: Final[Path] = resource_root() / "prompts"
PROMPT_SUFFIX: Final[str] = ".md"


class PromptError(RuntimeError):
    """A prompt file is missing."""


def prompt_path(name: str, directory: Path | None = None) -> Path:
    """Where a named prompt lives."""
    return (directory or PROMPT_DIR) / f"{name}{PROMPT_SUFFIX}"


def load_prompt(name: str, directory: Path | None = None) -> str:
    """Read one prompt by name.

    Raises:
        PromptError: the prompt file does not exist. A missing prompt is never
            replaced by an improvised default - that would put unreviewed text
            in front of the model.
    """
    path = prompt_path(name, directory)
    if not path.is_file():
        raise PromptError(
            f"Khong tim thay prompt {name!r} tai {path}. "
            "Prompt phai nam trong prompts/ va duoc version nhu code."
        )
    return storage.read_text(path).strip()


def available_prompts(directory: Path | None = None) -> tuple[str, ...]:
    """Every prompt name on disk, sorted."""
    root = directory or PROMPT_DIR
    if not root.is_dir():
        return ()
    return tuple(sorted(path.stem for path in root.glob(f"*{PROMPT_SUFFIX}")))
