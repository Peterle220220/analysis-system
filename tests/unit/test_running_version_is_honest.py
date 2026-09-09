"""Trang He thong tung noi sai mot cau khong ai nghi la co the sai.

`git pull` doi THU MUC ngay lap tuc. TIEN TRINH thi chi doi khi duoc khoi dong
lai. Ca hai dong tren trang - "Ban dang chay 5e1d518" va "Dang chay ban moi
nhat" - deu doc tu thu muc, nen chung noi that ve thu muc va noi doi ve thu
dang chay.

Chu he thong bam cap nhat, doc thay "dang chay ban moi nhat", roi khong thay
tinh nang dau: *"khong the nao toi dang chay ban ms nhat nhung van khong thay
tinh nang cua ban"*. Khong co gi tren man hinh giai thich duoc, va cach duy nhat
de biet la doc code.

Cach chua: doc ma commit MOT LAN luc nap module - tuc la luc tien trinh bat dau
- roi doi chieu voi thu muc moi lan mo trang.
"""

from __future__ import annotations

from pathlib import Path

from analysis_system.services import updater
from analysis_system.web.render import system_page

MOI = updater.Update()


def _version(sha: str = "abc1234") -> updater.Version:
    return updater.Version(sha=sha, subject="mot thay doi", when="09/09 17:19", branch="main")


# --- cau canh bao --------------------------------------------------------------


def test_the_page_says_so_when_the_process_is_behind() -> None:
    shown = system_page(_version(), MOI, "", "thu muc da la def5678, tien trinh van la abc1234")
    assert "CHƯA chạy" in shown


def test_it_tells_you_how_to_restart() -> None:
    # Mot canh bao khong noi phai lam gi thi chi lam nguoi doc lo them.
    shown = system_page(_version(), MOI, "", "lech nhau")
    assert "restart" in shown


def test_it_covers_docker_too() -> None:
    """May chu that dang chay bang Docker, noi `systemctl --user` khong co tac dung."""
    shown = system_page(_version(), MOI, "", "lech nhau")
    assert "docker" in shown.lower()


def test_a_process_in_step_with_the_folder_says_nothing() -> None:
    shown = system_page(_version(), MOI, "", "")
    assert "CHƯA chạy" not in shown


# --- chinh phep do -------------------------------------------------------------


def test_the_loaded_sha_is_read_once_at_import() -> None:
    """Doc lai moi lan goi thi sau khi pull no se tra ve ma MOI - dung cai loi
    dang chua."""
    assert isinstance(updater.LOADED, str)


def test_a_folder_matching_the_process_is_not_flagged() -> None:
    # Kho cua chinh du an nay, khong ai vua pull giua chung.
    assert updater.stale(updater.repo_root()) == ""


def test_an_unreadable_folder_is_not_flagged(tmp_path: Path) -> None:
    """Doan bua o day se keu oan moi lan chay, va mot canh bao keu mai thi khong
    ai doc nua."""
    assert updater.stale(tmp_path) == ""


def test_the_warning_names_both_versions(monkeypatch) -> None:
    monkeypatch.setattr(updater, "LOADED", "aaaaaaa")
    said = updater.stale(updater.repo_root())
    assert "aaaaaaa" in said
    assert "khởi động lại" in said


def test_the_running_card_shows_what_the_process_loaded() -> None:
    """Khong phai ma tren dia - do la ca cho hong."""
    shown = system_page(_version(sha="tren_dia"), MOI, "", "")
    assert updater.LOADED in shown
