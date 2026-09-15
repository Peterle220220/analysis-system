"""scripts/move_module.py: chuyển module và sửa mọi chỗ gọi, không sót, không sửa nhầm."""

from __future__ import annotations

from pathlib import Path

import pytest

from move_module import rewrite, run

CORE = ("analysis_system.services.storage", "analysis_system.core.storage")


def test_a_dotted_import_follows_the_module() -> None:
    text, count = rewrite("from analysis_system.services.storage import read_frame\n", *CORE)
    assert text == "from analysis_system.core.storage import read_frame\n"
    assert count == 1


def test_a_module_with_a_longer_similar_name_is_left_alone() -> None:
    source = "from analysis_system.services.scoped_storage import ScopedStorage\n"
    assert rewrite(source, *CORE) == (source, 0)


def test_a_shared_from_import_is_split_and_keeps_the_other_names() -> None:
    text, count = rewrite("from analysis_system.services import llm, storage as st\n", *CORE)
    assert text == (
        "from analysis_system.services import llm\nfrom analysis_system.core import storage as st\n"
    )
    assert count == 1


def test_a_renamed_module_keeps_its_local_name_and_its_comment() -> None:
    source = "def f():\n    from analysis_system import api  # noqa: F401\n"
    text, _ = rewrite(source, "analysis_system.api", "analysis_system.application.workspace")
    assert text == (
        "def f():\n    from analysis_system.application import workspace as api  # noqa: F401\n"
    )


def test_a_string_naming_the_module_is_rewritten() -> None:
    source = 'monkeypatch.setattr("analysis_system.services.storage.read_frame", fake)\n'
    text, _ = rewrite(source, *CORE)
    assert '"analysis_system.core.storage.read_frame"' in text


def test_a_file_path_in_config_is_rewritten() -> None:
    source = '"src/analysis_system/services/storage.py" = ["N818"]\n'
    assert rewrite(source, *CORE, python=False) == (
        '"src/analysis_system/core/storage.py" = ["N818"]\n',
        1,
    )


def test_a_package_move_carries_its_submodules() -> None:
    source = (
        "from analysis_system.contracts.base import DataRef\n"
        "PATH = 'src/analysis_system/contracts/base.py'\n"
    )
    text, count = rewrite(
        source, "analysis_system.contracts", "analysis_system.models", package=True
    )
    assert "from analysis_system.models.base import DataRef" in text
    assert "src/analysis_system/models/base.py" in text
    assert count == 2


# Bang anh xa chua ten cu lam du lieu; cong cu khong duoc sua no.
MAP_TEXT = 'MOVES = {"analysis_system.services.storage": "analysis_system.core.storage"}\n'


def project(root: Path) -> Path:
    """Một repo tí hon: một module sẽ chuyển, một module gọi nó, một test, một cấu hình."""
    files = {
        "src/analysis_system/__init__.py": "",
        "src/analysis_system/services/__init__.py": "",
        "src/analysis_system/services/storage.py": "VALUE = 1\n",
        "src/analysis_system/services/llm.py": "from analysis_system.services import storage\n",
        "tests/test_x.py": 'TARGET = "analysis_system.services.storage.VALUE"\n',
        "pyproject.toml": '"src/analysis_system/services/storage.py" = ["N818"]\n',
        "NOTES.md": "Da sua analysis_system.services.storage hom qua.\n",
        "scripts/refactor_map.py": MAP_TEXT,
    }
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def test_a_dry_run_reports_everything_and_writes_nothing(tmp_path: Path) -> None:
    root = project(tmp_path)
    report = run(root, dict([CORE]), apply=False)
    assert report.moves == [CORE]
    assert report.created == ["analysis_system.core"]
    assert set(report.edits) == {
        "src/analysis_system/services/llm.py",
        "tests/test_x.py",
        "pyproject.toml",
    }
    assert report.mentions == {"NOTES.md": 1}
    assert (root / "src/analysis_system/services/storage.py").is_file()
    assert not (root / "src/analysis_system/core").exists()


def test_applying_moves_the_file_and_every_caller(tmp_path: Path) -> None:
    root = project(tmp_path)
    run(root, dict([CORE]), apply=True, tidy=False)

    def read(name: str) -> str:
        return (root / name).read_text(encoding="utf-8")

    assert read("src/analysis_system/core/storage.py") == "VALUE = 1\n"
    assert not (root / "src/analysis_system/services/storage.py").exists()
    assert (root / "src/analysis_system/core/__init__.py").is_file()
    assert read("src/analysis_system/services/llm.py") == (
        "from analysis_system.core import storage\n"
    )
    assert "analysis_system.core.storage.VALUE" in read("tests/test_x.py")
    assert "src/analysis_system/core/storage.py" in read("pyproject.toml")
    # Tai lieu ke lai lich su: chi duoc liet ke, khong tu sua.
    assert read("NOTES.md") == "Da sua analysis_system.services.storage hom qua.\n"
    # Bang anh xa cua chinh bo cong cu giu nguyen ten cu.
    assert read("scripts/refactor_map.py") == MAP_TEXT


def test_a_move_onto_an_existing_module_is_refused(tmp_path: Path) -> None:
    root = project(tmp_path)
    target = root / "src/analysis_system/core/storage.py"
    target.parent.mkdir(parents=True)
    target.write_text("OTHER = 2\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="da co san"):
        run(root, dict([CORE]), apply=True, tidy=False)
    assert target.read_text(encoding="utf-8") == "OTHER = 2\n"


def test_a_module_that_does_not_exist_is_refused(tmp_path: Path) -> None:
    root = project(tmp_path)
    with pytest.raises(SystemExit, match="khong tim thay"):
        run(root, {"analysis_system.services.nothing": "analysis_system.core.nothing"}, apply=False)
