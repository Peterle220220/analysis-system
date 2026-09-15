"""Tính chéo dòng trên bảng dài: xoay ngang tạm thời bằng code, rồi mới tính.

Bảng BCTC xoay dọc có dạng `Chỉ tiêu | Kỳ báo cáo | Giá trị`. "Lợi nhuận sau thuế" và
"Tổng cộng tài sản" không còn là hai cột mà là hai DÒNG của cột `Chỉ tiêu`, nên ROA
(lợi nhuận chia tài sản, từng quý) phải lấy hai dòng về cùng một dòng trước rồi mới
chia được. Planner lập đúng kế hoạch đó; model viết SQL thì hỏng ba kiểu trong ba lượt
(dấu `...` kiểu MySQL, trả rỗng, không khai nguồn gốc cột `roa`), và lượt hỏi dừng
(bao_cao_tai_chinh_mb_cua_4_quy_gan_nhat__q2, 2026-09-15).

Đây là việc code làm được, nên code làm: nhận ra bảng dài (đúng một cột số, một cột
chữ chứa những tên câu hỏi gọi), dựng câu SQL xoay ngang (mỗi tên được hỏi thành một
cột, gom theo cột còn lại, cộng cột tỷ lệ khi câu hỏi hỏi A trên B), và TỰ KHAI nguồn gốc
từng cột. Cột chỉ mô tả chỉ tiêu (như "Bảng": lợi nhuận thuộc "Kết quả kinh doanh", tài
sản thuộc "Cân đối kế toán") không được đem gom, nếu không hai chỉ tiêu nằm hai dòng khác
nhau và phép chia ra rỗng.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Final

import pandas as pd

from analysis_system.models.agents import ColumnLineage, SqlProposal
from analysis_system.services.question_labels import is_ratio_gap, named_positions, period_columns

# Danh dau cau lenh do code dung, de A4 khong ap nhung phep kiem danh cho SQL cua model.
PIVOT_REASON: Final[str] = "xoay ngang tam thoi bang code (khong qua model)"
PIVOT_TABLE: Final[str] = "xoay_ngang"


@dataclass(frozen=True)
class CrossRow:
    """Một phép tính chéo dòng câu hỏi đòi trên một bảng dài."""

    label: str
    value: str
    items: tuple[object, ...]
    group_by: tuple[str, ...]
    ratio: tuple[object, object] | None = None


def read_cross_row(frame: pd.DataFrame, question: str) -> CrossRow | None:
    """Câu hỏi này có gọi tên những dòng của một bảng dài không, và có hỏi A chia B không."""
    if not question.strip():
        return None
    numeric = [
        str(column)
        for column in frame.columns
        if pd.api.types.is_numeric_dtype(frame[column])
        and not pd.api.types.is_bool_dtype(frame[column])
    ]
    if len(numeric) != 1:
        return None
    value = numeric[0]
    positions = named_positions(frame, question)
    periods = set(period_columns(frame))
    choices = [column for column in positions if column != value and column not in periods]
    if not choices:
        return None
    label = max(
        choices,
        key=lambda column: (
            len(positions[column]),
            sum(end - start for start, end, _ in positions[column]),
        ),
    )
    hits = positions[label]
    items = tuple(hit[2] for hit in hits)

    others = [str(column) for column in frame.columns if str(column) not in (label, value)]
    rows = frame[frame[label].isin(list(items))]
    # Cot chi mo ta chi tieu: moi chi tieu duoc hoi chi co mot gia tri o cot do.
    attributes = [
        column
        for column in others
        if column not in periods
        and all(rows.loc[rows[label] == item, column].nunique(dropna=False) <= 1 for item in items)
    ]
    group_by = tuple(column for column in others if column not in attributes)

    ratio = next(
        (
            (first[2], second[2])
            for first, second in itertools.pairwise(hits)
            if is_ratio_gap(question, first, second)
        ),
        None,
    )
    return CrossRow(label=label, value=value, items=items, group_by=group_by, ratio=ratio)


def _ident(name: object) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _text(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def ratio_name(cross: CrossRow) -> str:
    """Tên cột tỷ lệ: "A / B"."""
    assert cross.ratio is not None
    return f"{cross.ratio[0]} / {cross.ratio[1]}"


def _pick(cross: CrossRow, item: object) -> str:
    return f"SUM(CASE WHEN {_ident(cross.label)} = {_text(item)} THEN {_ident(cross.value)} END)"


def pivot_proposal(tables: dict[str, pd.DataFrame], *texts: str) -> SqlProposal | None:
    """Câu SQL xoay ngang tạm thời kèm nguồn gốc từng cột, khi câu hỏi (hay lời dặn) đòi nó.

    Chỉ khi có thật một phép tính chéo dòng: câu hỏi gọi tên ít nhất hai dòng của cột
    chỉ tiêu, hoặc hỏi A chia B. Một tên thôi (lọc một chỉ tiêu) thì để model viết như cũ.
    """
    if len(tables) != 1:
        return None
    ((table, frame),) = tables.items()
    for text in texts:
        cross = read_cross_row(frame, text)
        if cross is None or not cross.group_by:
            continue
        if cross.ratio is None and len(cross.items) < 2:
            continue
        return _proposal(table, cross)
    return None


def _proposal(table: str, cross: CrossRow) -> SqlProposal:
    groups = ", ".join(_ident(column) for column in cross.group_by)
    selected = [_ident(column) for column in cross.group_by]
    selected += [f"{_pick(cross, item)} AS {_ident(item)}" for item in cross.items]
    if cross.ratio is not None:
        top, bottom = cross.ratio
        selected.append(
            f"{_pick(cross, top)} / NULLIF({_pick(cross, bottom)}, 0) "
            f"AS {_ident(ratio_name(cross))}"
        )
    wanted = ", ".join(_text(item) for item in cross.items)
    sql = (
        f"SELECT {', '.join(selected)} FROM {_ident(table)} "
        f"WHERE {_ident(cross.label)} IN ({wanted}) GROUP BY {groups} ORDER BY {groups}"
    )

    sources = (f"{table}.{_ident(cross.label)}", f"{table}.{_ident(cross.value)}")
    over = ", ".join(cross.group_by)
    lineage = [
        ColumnLineage(
            output=str(item),
            sources=sources,
            transform=f"'{cross.value}' ở các dòng {cross.label} = {item}, cộng theo {over} "
            "(xoay ngang tạm thời bằng code)",
        )
        for item in cross.items
    ]
    if cross.ratio is not None:
        top, bottom = cross.ratio
        lineage.append(
            ColumnLineage(
                output=ratio_name(cross),
                sources=sources,
                transform=f"{top} chia {bottom} theo từng {over}; mẫu bằng 0 thì để trống",
            )
        )
    return SqlProposal(sql=sql, target_table=PIVOT_TABLE, lineage=lineage, reason=PIVOT_REASON)
