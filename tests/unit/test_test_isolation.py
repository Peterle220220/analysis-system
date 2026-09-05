"""Mot test khong duoc ghi vao tang du lieu that cua nguoi dung.

Two fixtures claimed to build a private workspace and did not. They filtered the
layer fields with `isinstance(..., str)`, and `LayerPaths` holds `Path` - so the
condition was never true, the update dict was always empty, and `model_copy`
returned the real settings unchanged.

Nothing failed. The tests passed, against the user's own data, writing files
into their raw layer. It surfaced only when that layer was emptied and one test
run put the files straight back.

The lesson is the one this codebase keeps relearning: a thing that looks right
and silently does nothing is worse than a thing that breaks.
"""

from __future__ import annotations

import re
from pathlib import Path

TESTS = Path(__file__).resolve().parents[1]

# The shape that failed. `LayerPaths` fields are Path, so filtering the update
# by `str` empties it and the copy changes nothing.
BROKEN_FILTER = re.compile(r"isinstance\(\s*getattr\(\s*\w+\.layers\s*,\s*\w+\s*\)\s*,\s*str\s*\)")


def test_no_fixture_filters_layer_fields_by_string_type() -> None:
    guilty = [
        path.relative_to(TESTS)
        for path in TESTS.rglob("test_*.py")
        if BROKEN_FILTER.search(path.read_text(encoding="utf-8"))
    ]
    assert not guilty, (
        "Fixture nay loc truong layer bang isinstance(..., str), ma chung la Path - "
        f"nen no khong doi gi va test se chay vao du lieu that: {guilty}"
    )


def test_every_settings_fixture_points_somewhere_temporary() -> None:
    """A fixture named `settings` must build its layers from `tmp_path`.

    Not a style rule. The one thing that separates a test writing to a scratch
    directory from a test writing to somebody's data is where the layer roots
    point, and a fixture that never mentions `tmp_path` cannot be pointing
    anywhere safe.
    """
    missing: list[str] = []
    for path in TESTS.rglob("test_*.py"):
        text = path.read_text(encoding="utf-8")
        for block in re.findall(r"def settings\((.*?)\n\n", text, flags=re.DOTALL):
            if "tmp_path" not in block:
                missing.append(str(path.relative_to(TESTS)))
    assert not missing, f"fixture 'settings' khong dung tmp_path: {missing}"
