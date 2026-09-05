"""Sua MOT dong trong .env, khong dung toi dong nao khac.

`.env` holds the API keys as well as the dashboard password, so anything that
writes to it has to be careful in a particular way: it must change the one line
it means to and leave every other byte alone, and it must never print what it
read.

Rewriting the file from parsed key-value pairs would be the obvious approach and
the wrong one - it would drop comments, reorder lines, and quietly reformat
values somebody wrote by hand. This replaces one line in place.
"""

from __future__ import annotations

import os
from pathlib import Path


class EnvError(RuntimeError):
    """The file cannot be updated safely, so it is not updated at all."""


def set_value(path: Path, name: str, value: str) -> str:
    """Put `name=value` into the file, replacing any line that sets `name`.

    Returns:
        What happened, as something to show a person: whether a line was
        replaced or added.

    Raises:
        EnvError: the file cannot be read or written, or `value` spans lines -
            which would silently turn one setting into two.
    """
    if "\n" in value or "\r" in value:
        raise EnvError("Gia tri khong duoc xuong dong.")

    try:
        original = path.read_text(encoding="utf-8") if path.is_file() else ""
    except OSError as error:
        raise EnvError(f"Khong doc duoc {path}: {error}") from error

    lines = original.splitlines()
    wanted = f"{name}={value}"
    replaced = 0
    kept: list[str] = []
    for line in lines:
        if line.startswith(f"{name}="):
            replaced += 1
            # Only the first one becomes the new value. A file that somehow has
            # two is left with one, which is the state it should have been in.
            if replaced == 1:
                kept.append(wanted)
            continue
        kept.append(line)
    if not replaced:
        kept.append(wanted)

    try:
        path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    except OSError as error:
        raise EnvError(f"Khong ghi duoc {path}: {error}") from error

    if replaced > 1:
        return f"Da thay {replaced} dong {name} bang mot dong duy nhat."
    if replaced:
        return f"Da thay dong {name} cu."
    return f"Da them dong {name}."


def load_env(path: Path) -> tuple[str, ...]:
    """Read `.env` into the environment, for names not already set.

    Without this, `asys serve` in a fresh terminal fails with "no password
    configured" while the password sits in `.env` one directory away - the file
    was only ever read by a shell that had been told to source it. Somebody who
    has just set a password and is told to set a password has been sent in a
    circle by their own tools.

    An exported variable wins over the file. Someone who set a name on the
    command line meant that one, and a file quietly overruling it is how you end
    up debugging the wrong value.

    Returns:
        The names taken from the file, never the values: this is the one module
        that reads API keys, and it does not get to say what it saw.
    """
    try:
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
    except OSError:
        # A missing or unreadable .env is not an error here: the environment may
        # well be configured some other way, and that is the caller's business.
        return ()

    taken: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # `export NAME=value` is valid in a file meant to be sourced.
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].lstrip()
        name, sep, value = stripped.partition("=")
        name = name.strip()
        if not sep or not name or name in os.environ:
            continue
        value = value.strip()
        # A shell strips one layer of matching quotes; so does this, or the key
        # arrives with quote marks in it and every request comes back 401.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ[name] = value
        taken.append(name)
    return tuple(taken)
