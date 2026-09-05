"""Sua .env: dung mot dong, va khong dung toi byte nao khac.

This file holds the API keys as well as the dashboard password, so the whole
requirement is restraint. Every test here is about what must NOT change.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from analysis_system.web.envfile import EnvError, set_value

EXISTING = """# Khoa API - khong commit file nay
GEMINI_API_KEY=abc123
OPENROUTER_API_KEY=def456

ASYS_PASSWORD_HASH=cu:cu
"""


def test_only_the_named_line_changes(tmp_path: Path) -> None:
    # The point of the whole module. The API keys sit in this file.
    path = tmp_path / ".env"
    path.write_text(EXISTING, encoding="utf-8")
    set_value(path, "ASYS_PASSWORD_HASH", "moi:moi")
    lines = path.read_text(encoding="utf-8").splitlines()
    assert "GEMINI_API_KEY=abc123" in lines
    assert "OPENROUTER_API_KEY=def456" in lines
    assert "ASYS_PASSWORD_HASH=moi:moi" in lines
    assert "ASYS_PASSWORD_HASH=cu:cu" not in lines


def test_comments_and_blank_lines_survive(tmp_path: Path) -> None:
    # Rewriting the file from parsed pairs would be the obvious approach and
    # would quietly throw these away.
    path = tmp_path / ".env"
    path.write_text(EXISTING, encoding="utf-8")
    set_value(path, "ASYS_PASSWORD_HASH", "moi:moi")
    text = path.read_text(encoding="utf-8")
    assert "# Khoa API - khong commit file nay" in text
    assert "\n\n" in text


def test_a_missing_line_is_added(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("GEMINI_API_KEY=abc123\n", encoding="utf-8")
    what = set_value(path, "ASYS_PASSWORD_HASH", "moi:moi")
    assert "them" in what
    assert "ASYS_PASSWORD_HASH=moi:moi" in path.read_text(encoding="utf-8")


def test_a_file_that_is_not_there_yet_is_created(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    set_value(path, "ASYS_PASSWORD_HASH", "moi:moi")
    assert path.read_text(encoding="utf-8") == "ASYS_PASSWORD_HASH=moi:moi\n"


def test_two_lines_for_one_name_become_one(tmp_path: Path) -> None:
    # The state hand-editing produces: a line pasted in rather than replaced.
    # The last one wins when a shell reads it, so the file "works" while saying
    # two different things.
    path = tmp_path / ".env"
    path.write_text("ASYS_PASSWORD_HASH=a:a\nASYS_PASSWORD_HASH=b:b\n", encoding="utf-8")
    what = set_value(path, "ASYS_PASSWORD_HASH", "moi:moi")
    assert "2 dong" in what
    assert path.read_text(encoding="utf-8").count("ASYS_PASSWORD_HASH=") == 1


def test_a_name_that_merely_starts_the_same_is_left_alone(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("ASYS_PASSWORD_HASH_OLD=giu\n", encoding="utf-8")
    set_value(path, "ASYS_PASSWORD_HASH", "moi:moi")
    text = path.read_text(encoding="utf-8")
    assert "ASYS_PASSWORD_HASH_OLD=giu" in text


def test_a_value_with_a_newline_is_refused(tmp_path: Path) -> None:
    # Would turn one setting into two, and the second would be whatever the
    # rest of the value happened to look like.
    path = tmp_path / ".env"
    with pytest.raises(EnvError):
        set_value(path, "ASYS_PASSWORD_HASH", "moi\nMALICIOUS=1")
    assert not path.exists()
