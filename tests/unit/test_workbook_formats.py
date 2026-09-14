"""Tep mang duoi Excel duoc doc theo noi dung that, giu nguyen chu trong tung o.

Tep that lam hong luong: mot "bao cao tai chinh 4 quy" tai tu web, duoi .xls,
ben trong la trang HTML hai bang (Ket qua kinh doanh, Can doi ke toan) cung 4
cot quy. Bang HTML duoi day mo phong dung cau truc do.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from analysis_system.services.storage import (
    ITEM_COLUMN,
    READ_NOTES,
    SECTION_COLUMN,
    StorageError,
    excel_sheets,
    read_excel,
    workbook_kind,
)

HEAD = (
    '<html xmlns:o="urn:schemas-microsoft-com:office:office" '
    'xmlns:x="urn:schemas-microsoft-com:office:excel"><head><meta charset="utf-8" />'
    "<!--[if gte mso 9]><xml><x:ExcelWorkbook><x:ExcelWorksheets><x:ExcelWorksheet>"
    "<x:Name>BCTC</x:Name></x:ExcelWorksheet></x:ExcelWorksheets></x:ExcelWorkbook>"
    "</xml><![endif]--></head><body>"
)


def table(title: str, columns: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{name}</th>" for name in [title, *columns])
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


QUARTERS = ["Q1-2026", "Q2-2026"]
INCOME = table(
    "Kết quả kinh doanh",
    QUARTERS,
    [["Thu nhập lãi thuần", "14913.12", "16893.65"], ["Lãi/lỗ khác", "-31.71", "137.24"]],
)
BALANCE = table(
    "Cân đối kế toán",
    QUARTERS,
    [["Tài sản", "-", "-"], ["Cho vay khách hàng", "1105852.15", "1210891.60"]],
)


def page(tmp_path: Path, *tables: str, name: str = "bctc.xls") -> Path:
    path = tmp_path / name
    path.write_text(HEAD + "".join(tables) + "</body></html>", encoding="utf-8")
    return path


def notes(frame: pd.DataFrame) -> list[Any]:
    return list(frame.attrs.get(READ_NOTES, []))


def test_an_excel_html_export_stacks_tables_that_share_their_columns(tmp_path: Path) -> None:
    path = page(tmp_path, INCOME, BALANCE)
    assert workbook_kind(path) == "html"
    frame = read_excel(path)
    assert list(frame.columns) == [SECTION_COLUMN, ITEM_COLUMN, *QUARTERS]
    assert len(frame) == 4
    first = ["Kết quả kinh doanh", "Thu nhập lãi thuần", "14913.12", "16893.65"]
    assert frame.iloc[0].tolist() == first
    # Chu nguyen van: so khong bi doi (1210891.60 giu so 0 cuoi), dau "-" giu nguyen.
    last = ["Cân đối kế toán", "Cho vay khách hàng", "1105852.15", "1210891.60"]
    assert frame.iloc[3].tolist() == last
    assert frame.iloc[2, 2] == "-"
    assert "2 bảng cùng cột" in notes(frame)[0]


def test_each_table_can_still_be_read_on_its_own(tmp_path: Path) -> None:
    path = page(tmp_path, INCOME, BALANCE)
    assert excel_sheets(path) == ["Kết quả kinh doanh", "Cân đối kế toán"]
    by_name = read_excel(path, sheet="Cân đối kế toán")
    assert list(by_name.columns) == ["Cân đối kế toán", *QUARTERS]
    assert len(by_name) == 2
    assert read_excel(path, sheet=1).equals(by_name)
    with pytest.raises(StorageError, match="Khong co bang"):
        read_excel(path, sheet="Không có")


def test_tables_with_different_columns_are_not_forced_together(tmp_path: Path) -> None:
    other = table("Chỉ số", ["Năm 2025"], [["ROE", "21.5"]])
    frame = read_excel(page(tmp_path, INCOME, other))
    assert list(frame.columns) == ["Kết quả kinh doanh", *QUARTERS]
    assert len(frame) == 2
    assert "bỏ: Chỉ số" in notes(frame)[0]


def test_a_table_without_header_cells_takes_its_first_row(tmp_path: Path) -> None:
    body = (
        "<table><tr><td>Tên</td><td></td><td>Tên</td></tr>"
        '<tr><td colspan="2">A</td><td>B</td></tr></table>'
    )
    frame = read_excel(page(tmp_path, body))
    assert list(frame.columns) == ["Tên", "Cột 2", "Tên (2)"]
    assert frame.iloc[0].tolist() == ["A", None, "B"]
    assert notes(frame) == []


def test_a_merged_title_row_above_the_header_names_the_table(tmp_path: Path) -> None:
    body = (
        '<table><tr><th colspan="3">BÁO CÁO QUÝ</th></tr>'
        "<tr><th>Chỉ tiêu</th><th>Q1</th><th>Q2</th></tr>"
        "<tr><td>Doanh thu</td><td>1</td><td>2</td></tr></table>"
    )
    path = page(tmp_path, body)
    assert excel_sheets(path) == ["BÁO CÁO QUÝ"]
    assert list(read_excel(path).columns) == ["Chỉ tiêu", "Q1", "Q2"]


def cell(text: str, attrs: str = "") -> str:
    return f'<Cell{attrs}><Data ss:Type="String">{text}</Data></Cell>'


def row(*cells: str) -> str:
    return "<Row>" + "".join(cells) + "</Row>"


SPREADSHEET_ML = (
    '<?xml version="1.0"?>\n<?mso-application progid="Excel.Sheet"?>\n'
    '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" '
    'xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">'
    '<Worksheet ss:Name="Doanh thu"><Table>'
    + row(cell("Tháng"), cell("Doanh thu"), cell("Ghi chú"))
    + row(cell("1"), cell("nghỉ Tết", ' ss:Index="3"'))
    + '</Table></Worksheet><Worksheet ss:Name="Chi phí"><Table>'
    + row(cell("Khoản", ' ss:MergeAcross="1"'), cell("Tiền"))
    + row(cell("Điện"), cell("x"), cell("5.50"))
    + "</Table></Worksheet></Workbook>"
)


def test_a_spreadsheetml_2003_file_named_xls_is_read_sheet_by_sheet(tmp_path: Path) -> None:
    path = tmp_path / "so_lieu.xls"
    path.write_text(SPREADSHEET_ML, encoding="utf-8")
    assert workbook_kind(path) == "spreadsheetml"
    assert excel_sheets(path) == ["Doanh thu", "Chi phí"]
    first = read_excel(path)
    assert list(first.columns) == ["Tháng", "Doanh thu", "Ghi chú"]
    assert first.iloc[0].tolist() == ["1", None, "nghỉ Tết"]
    second = read_excel(path, sheet="Chi phí")
    assert list(second.columns) == ["Khoản", "Cột 2", "Tiền"]
    assert second.iloc[0].tolist() == ["Điện", "x", "5.50"]


def test_a_real_xlsx_renamed_to_xls_is_read_with_openpyxl(tmp_path: Path) -> None:
    source = tmp_path / "that.xlsx"
    pd.DataFrame({"a": ["1", "2"], "b": ["x", "y"]}).to_excel(source, index=False)
    renamed = source.rename(tmp_path / "doi_ten.xls")
    assert workbook_kind(renamed) == "xlsx"
    assert read_excel(renamed).to_dict("list") == {"a": ["1", "2"], "b": ["x", "y"]}
    assert excel_sheets(renamed) == ["Sheet1"]


def test_a_genuine_old_xls_says_how_to_get_it_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "cu.xls"
    path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 504)
    assert workbook_kind(path) == "xls"

    def no_reader(*_args: object, **_kwargs: object) -> pd.DataFrame:
        raise ImportError("Missing optional dependency 'xlrd'")

    monkeypatch.setattr(pd, "read_excel", no_reader)
    with pytest.raises(StorageError, match=r"lưu lại thành \.xlsx"):
        read_excel(path)


def test_a_page_without_any_table_is_refused_in_words(tmp_path: Path) -> None:
    path = page(tmp_path, "<p>không có bảng</p>")
    with pytest.raises(StorageError, match="Khong tim thay bang"):
        read_excel(path)
