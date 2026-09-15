"""Hai giao dien, mot su that.

Ban Next la mot giao dien VIET MOI - no khong dung chung mot dong nao voi
`render.py`. Nen moi canh bao ma giao dien Python co, giao dien Next chi co neu
tang JSON mang no sang.

Do lai sau khi tron: nam viec da lam cho ban Python thi ban Next thieu ba. Hai
trong ba cai thieu la CANH BAO - va mot canh bao chi hien o mot nua so giao
dien thi no la mot canh bao khong dang tin.

Test nay giu tang JSON mang du hai canh bao do, de khong ai phai nho.
"""

from __future__ import annotations

from analysis_system.api import TableReport
from analysis_system.services.updater import Update, Version
from analysis_system.web.view import _stale_columns, system


def _table(*columns: str) -> TableReport:
    return TableReport(uri="mart://x.parquet", rows=0, columns=tuple(columns))


# --- bang lam sach bang ban cu ---------------------------------------------------


def test_a_table_with_stale_names_is_counted() -> None:
    """Ten cot mang mot dau cach vo hinh o dau - bang lam sach truoc ban sua."""
    assert _stale_columns(_table("Bankrupt?", " Operating Gross Margin")) == 1


def test_the_real_shape_of_the_bankruptcy_table() -> None:
    stale = _stale_columns(_table(" ROA(C) before interest", " Debt ratio %", "Bankrupt?"))
    assert stale == 2


def test_a_clean_table_counts_zero() -> None:
    """Im lang la truong hop thuong gap, va la ly do canh bao con dang doc."""
    assert _stale_columns(_table("Bankrupt?", "doanh_thu")) == 0


def test_no_table_at_all_counts_zero() -> None:
    assert _stale_columns(None) == 0


# --- ban da tai ve nhung chua chay -------------------------------------------------


def _version() -> Version:
    return Version(sha="abc1234", subject="mot thay doi", when="09/09", branch="main")


def test_the_system_payload_carries_the_stale_warning() -> None:
    payload = system(_version(), Update(), "", "thu muc da la def5678, tien trinh van abc1234")
    assert payload["stale"] == "thu muc da la def5678, tien trinh van abc1234"


def test_it_is_empty_when_the_process_is_in_step() -> None:
    assert system(_version(), Update(), "", "")["stale"] == ""


def test_the_field_is_always_present_so_the_page_can_rely_on_it() -> None:
    # Thieu khoa thi ben Next phai doan, va doan sai o day nghia la im lang.
    assert "stale" in system(_version(), Update())
