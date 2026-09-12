"""Một câu trả lời, đưa ra Excel và Word.

Dashboard đọc được ngay trên màn hình, nhưng câu trả lời còn phải đi tiếp: dán
vào một bản trình bày, gửi cho người không có tài khoản, mở lại sau sáu tháng.
Chụp màn hình thì mất mọi thứ nằm sau con số.

Bốn thứ đi kèm mỗi con số, và cả bốn đều phải sống sót qua chuyến đi:

* **câu trả lời thẳng** — dòng người ta đọc đầu tiên, và là thứ duy nhất nhiều
  người đọc. Bỏ nó lại trên màn hình thì tệp gửi đi chỉ còn là số liệu rời.

* **cảnh báo độ tin cậy** — nằm ngay trên đầu, trước mọi kết luận, y như trên
  màn hình. Một bảng Excel toàn số mà bỏ mất dòng *"nhóm này chỉ có 3 dòng"*
  là một bảng nguy hiểm hơn không có bảng.
* **metric key** — thứ để lần ngược về chỉ số đã tính.
* **những gì không xác lập được** — một kết luận chỉ đáng tin bằng đúng những
  khoảng trống nó chịu thừa nhận.

Không có PDF. BUILD_SPEC ghi thẳng là hoãn, và hoãn thì để nguyên là hoãn.

`openpyxl` và `python-docx` đều đã nằm trong Mục 3 của BUILD_SPEC từ Phase 2 và
Phase 3, nên đây không phải một thư viện mới xin thêm.
"""

from __future__ import annotations

from collections.abc import Mapping
from io import BytesIO
from typing import TYPE_CHECKING, Final

from analysis_system.services.display_names import localize
from analysis_system.services.punctuation import plain_dashes

if TYPE_CHECKING:  # pragma: no cover - chỉ dùng cho kiểu
    from analysis_system.contracts.agents import ManagerAnswer

# Tên sheet, và thứ tự người ta gặp chúng khi mở tệp.
SHEET_CLAIMS: Final[str] = "Kết luận"
SHEET_WARNINGS: Final[str] = "Cảnh báo"
SHEET_GAPS: Final[str] = "Chưa xác lập được"

# Excel giới hạn tên sheet 31 ký tự và cấm một số ký tự; các tên trên đều an
# toàn, hằng số này chỉ để ai đổi tên còn biết mà kiểm.
MAX_SHEET_NAME: Final[int] = 31


def _shown(text: str, aliases: Mapping[str, str] | None) -> str:
    """Chữ đưa ra tệp: bỏ gạch ngang dài, tên cột gốc đổi sang tên tiếng Việt."""
    return localize(plain_dashes(str(text)), aliases or {})


def to_excel(answer: ManagerAnswer, aliases: Mapping[str, str] | None = None) -> bytes:
    """Câu trả lời dưới dạng .xlsx.

    Cảnh báo đứng thành một sheet riêng và là sheet **đầu tiên**: người mở tệp
    gặp nó trước khi gặp bất kỳ con số nào.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font

    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.title = SHEET_WARNINGS[:MAX_SHEET_NAME]

    bold = Font(bold=True)
    wrap = Alignment(wrap_text=True, vertical="top")

    sheet["A1"] = "Câu hỏi"
    sheet["A1"].font = bold
    sheet["B1"] = answer.question
    sheet["B1"].alignment = wrap
    sheet.column_dimensions["A"].width = 22
    sheet.column_dimensions["B"].width = 100

    row = 3
    if answer.summary:
        # Cau tra loi thang. Tep nay di ra ngoai cho nguoi khong mo dashboard
        # duoc, nen dong quan trong nhat khong duoc phep o lai tren man hinh.
        sheet.cell(row=row, column=1, value="Trả lời").font = bold
        sheet.cell(row=row, column=2, value=_shown(answer.summary, aliases)).alignment = wrap
        row += 2

    sheet.cell(row=row, column=1, value="Cảnh báo độ tin cậy").font = bold
    row += 1
    for line in answer.warnings or ("(không có)",):
        sheet.cell(row=row, column=2, value=_shown(line, aliases)).alignment = wrap
        row += 1

    claims = book.create_sheet(SHEET_CLAIMS[:MAX_SHEET_NAME])
    _header(claims, ("Kết luận", "Chỉ số đã dùng", "Nguồn dữ liệu"), bold)
    for index, claim in enumerate(answer.claims, start=2):
        claims.cell(row=index, column=1, value=_shown(claim.claim, aliases)).alignment = wrap
        claims.cell(row=index, column=2, value="\n".join(claim.metric_keys)).alignment = wrap
        claims.cell(row=index, column=3, value=claim.evidence_ref).alignment = wrap
    claims.column_dimensions["A"].width = 90
    claims.column_dimensions["B"].width = 40
    claims.column_dimensions["C"].width = 32

    gaps = book.create_sheet(SHEET_GAPS[:MAX_SHEET_NAME])
    _header(gaps, ("Chưa xác lập được",), bold)
    for index, line in enumerate(answer.unanswered, start=2):
        gaps.cell(row=index, column=1, value=_shown(line, aliases)).alignment = wrap
    gaps.column_dimensions["A"].width = 110

    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _header(sheet: object, titles: tuple[str, ...], bold: object) -> None:
    for column, title in enumerate(titles, start=1):
        cell = sheet.cell(row=1, column=column, value=title)  # type: ignore[attr-defined]
        cell.font = bold


def to_word(answer: ManagerAnswer, aliases: Mapping[str, str] | None = None) -> bytes:
    """Câu trả lời dưới dạng .docx.

    Cùng một thứ tự như trên màn hình, và thứ tự đó là có chủ ý: cảnh báo trước,
    kết luận sau. Đọc cảnh báo sau khi đã đọc hết số là đọc sau khi đã tin.
    """
    from docx import Document

    document = Document()
    document.add_heading("Kết quả phân tích", level=1)

    document.add_heading("Câu hỏi", level=2)
    document.add_paragraph(answer.question)

    if answer.warnings:
        document.add_heading("Cảnh báo độ tin cậy", level=2)
        for line in answer.warnings:
            document.add_paragraph(_shown(line, aliases), style="List Bullet")

    if answer.summary:
        # Sau canh bao, truoc ket luan - dung thu tu nhu tren man hinh. Mot cau
        # chot doc truoc khi biet du lieu mong la mot cau chot duoc tin nham.
        document.add_heading("Trả lời", level=2)
        document.add_paragraph(_shown(answer.summary, aliases))

    document.add_heading("Kết luận", level=2)
    if not answer.claims:
        document.add_paragraph("Không có kết luận nào qua được kiểm tra.")
    for index, claim in enumerate(answer.claims, start=1):
        document.add_paragraph(f"{index}. {_shown(claim.claim, aliases)}")
        if claim.metric_keys:
            # Chỉ số in nhạt và nhỏ hơn, nhưng vẫn in: đây là thứ để lần ngược
            # về con số gốc, và một kết luận không lần ngược được là một ý kiến.
            note = document.add_paragraph("Chỉ số: " + ", ".join(claim.metric_keys))
            note.runs[0].italic = True

    if answer.unanswered:
        document.add_heading("Chưa xác lập được", level=2)
        for line in answer.unanswered:
            document.add_paragraph(_shown(line, aliases), style="List Bullet")

    if answer.needs:
        document.add_heading("Cần thêm gì để trả lời rõ hơn", level=2)
        for need in answer.needs:
            document.add_paragraph(need.ask, style="List Bullet")

    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()
