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
