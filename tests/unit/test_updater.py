"""Lay code moi tu Git ngay tren may chu.

Mot nut chay duoc code moi tren may chu la MOT CUA DE CHAY CODE TU XA, nen bai
nay danh phan lon cho cac cho phai TU CHOI. Moi lop chan deu dung truoc lenh
ghi dau tien: hong thi khong co gi bi doi.

Dung kho git that, khong gia lap. Mot ban gia lap `git merge --ff-only` se luon
noi dieu ma nguoi viet no tin, chu khong phai dieu git lam.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from analysis_system.services.updater import apply, check, current


def run(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )
    return done.stdout.strip()


def commit(repo: Path, name: str, text: str) -> None:
    (repo / name).write_text(text, encoding="utf-8")
    run(repo, "add", "-A")
    run(repo, "commit", "-m", f"them {name}")


@pytest.fixture
def paired(tmp_path: Path) -> tuple[Path, Path]:
    """Mot kho 'tu xa' va mot ban sao dang chay, giong tren may chu."""
    origin = tmp_path / "origin"
    origin.mkdir()
    run(origin, "init", "--bare", "--initial-branch=main")

    work = tmp_path / "work"
    work.mkdir()
    run(work, "init", "--initial-branch=main")
    run(work, "config", "user.email", "test@example.com")
    run(work, "config", "user.name", "Test")
    commit(work, "mot.txt", "ban dau")
    run(work, "remote", "add", "origin", str(origin))
    run(work, "push", "-u", "origin", "main")
    return origin, work


def push_new_commit(paired: tuple[Path, Path], tmp_path: Path, name: str = "hai.txt") -> None:
    """Ai do day mot commit moi len kho tu xa."""
    origin, _ = paired
    other = tmp_path / f"other_{name}"
    run(tmp_path, "clone", str(origin), str(other))
    run(other, "config", "user.email", "test@example.com")
    run(other, "config", "user.name", "Test")
    commit(other, name, "moi")
    run(other, "push")


# --- doc duoc ban dang chay ---------------------------------------------------


def test_it_reads_the_running_version(paired: tuple[Path, Path]) -> None:
    _, work = paired
    found = current(work)
    assert found.sha
    assert found.branch == "main"
    assert not found.dirty


def test_it_notices_uncommitted_changes(paired: tuple[Path, Path]) -> None:
    _, work = paired
    (work / "mot.txt").write_text("sua tay tren may chu", encoding="utf-8")
    assert current(work).dirty


def test_a_folder_that_is_not_a_repo_says_nothing_rather_than_crashing(tmp_path: Path) -> None:
    assert current(tmp_path / "khong_co").sha == ""


# --- xem co gi moi khong ------------------------------------------------------


def test_nothing_new_is_reported_as_nothing_new(paired: tuple[Path, Path]) -> None:
    _, work = paired
    found = check(work)
    assert found.behind == 0
    assert not found.available
    assert not found.problem


def test_a_new_commit_upstream_is_seen(paired: tuple[Path, Path], tmp_path: Path) -> None:
    push_new_commit(paired, tmp_path)
    _, work = paired
    found = check(work)
    assert found.behind == 1
    assert found.available
    assert found.commits


def test_checking_never_touches_the_working_tree(paired: tuple[Path, Path], tmp_path: Path) -> None:
    """Chi fetch. Goi bao nhieu lan cung an toan."""
    push_new_commit(paired, tmp_path)
    _, work = paired
    was = current(work).sha
    check(work)
    check(work)
    assert current(work).sha == was


def test_a_branch_with_no_upstream_says_so(tmp_path: Path) -> None:
    """Khong kiem duoc khac han khong co ban moi."""
    work = tmp_path / "le_loi"
    work.mkdir()
    run(work, "init", "--initial-branch=main")
    run(work, "config", "user.email", "test@example.com")
    run(work, "config", "user.name", "Test")
    commit(work, "mot.txt", "ban dau")

    found = check(work)
    assert found.problem
    assert not found.available


# --- cap nhat -----------------------------------------------------------------


def test_it_fast_forwards_to_the_new_commit(paired: tuple[Path, Path], tmp_path: Path) -> None:
    push_new_commit(paired, tmp_path)
    _, work = paired

    done = apply(work)

    assert done.moved
    assert not done.problem
    assert done.was != done.now
    assert (work / "hai.txt").is_file()


def test_nothing_to_do_is_not_a_failure(paired: tuple[Path, Path]) -> None:
    _, work = paired
    done = apply(work)
    assert not done.problem
    assert not done.moved


# --- cac cho phai TU CHOI -----------------------------------------------------


def test_local_edits_stop_the_update(paired: tuple[Path, Path], tmp_path: Path) -> None:
    """Ghi de len thay doi cua nguoi khac la chuyen khong lui duoc, va o day
    khong ai dung canh de hoi."""
    push_new_commit(paired, tmp_path)
    _, work = paired
    (work / "mot.txt").write_text("sua tay tren may chu", encoding="utf-8")

    done = apply(work)

    assert done.problem
    assert "chua luu" in done.problem
    assert not done.moved
    # Va khong co gi bi doi.
    assert (work / "mot.txt").read_text(encoding="utf-8") == "sua tay tren may chu"
    assert not (work / "hai.txt").is_file()


def test_a_diverged_history_stops_the_update(paired: tuple[Path, Path], tmp_path: Path) -> None:
    """`--ff-only`: mot lan tron hong tren may chu la mot dich vu chet ma khong
    ai dang ngoi truoc man hinh."""
    push_new_commit(paired, tmp_path)
    _, work = paired
    commit(work, "rieng.txt", "chi co tren may chu")

    done = apply(work)

    assert done.problem
    assert "re khoi" in done.problem
    assert not done.moved
    assert not (work / "hai.txt").is_file()


def test_a_folder_that_is_not_a_repo_is_refused(tmp_path: Path) -> None:
    done = apply(tmp_path / "khong_co")
    assert done.problem
    assert not done.moved


def test_it_takes_no_command_from_anywhere() -> None:
    """Khong co o nhap nhanh, nhap remote, nhap gi ca - ca hai ham chi nhan mot
    duong dan, va git chay voi cac tham so co dinh trong code."""
    import inspect

    from analysis_system.services import updater

    for name in ("check", "apply", "current"):
        params = list(inspect.signature(getattr(updater, name)).parameters)
        assert params == ["repo"], name
