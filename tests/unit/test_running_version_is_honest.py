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

Cau canh bao do nay di qua lop JSON (test_view_carries_the_warnings.py); giao dien
HTML cu da bo (plans/refactor-ddd.md).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from analysis_system.core import updater


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


def test_the_warning_names_both_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(updater, "LOADED", "aaaaaaa")
    said = updater.stale(updater.repo_root())
    assert "aaaaaaa" in said
    assert "khởi động lại" in said
