"""Tep mang duoi Excel duoc nhan dang theo byte, va Excel 97-2003 that co bo doc nhan."""

from __future__ import annotations

from pathlib import Path

from analysis_system.services.extraction import detect
from analysis_system.services.routing import route_one

OLE2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 504


def test_a_genuine_old_xls_is_recognised_and_given_to_the_table_reader(tmp_path: Path) -> None:
    # Truoc day: "khong nhan dang duoc", khong bo doc nao duoc hoi toi.
    path = tmp_path / "bao_cao.xls"
    path.write_bytes(OLE2)
    assert detect(path).kind == "ole"
    assert route_one(path).agent == "a1_ingest"


def test_an_old_word_file_is_not_sent_to_the_table_reader(tmp_path: Path) -> None:
    path = tmp_path / "hop_dong.doc"
    path.write_bytes(OLE2)
    assert route_one(path).agent != "a1_ingest"


def test_an_html_page_named_xls_goes_to_the_table_reader(tmp_path: Path) -> None:
    # Dang bao cao tai chinh tai tu web hay gap: trang HTML mang duoi .xls.
    path = tmp_path / "bctc.xls"
    page = "<html><body><table><tr><th>A</th></tr></table></body></html>"
    path.write_text(page, encoding="utf-8")
    assert detect(path).kind == "text"
    assert route_one(path).agent == "a1_ingest"
