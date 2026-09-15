"""Nhãn tiếng Việt cho GIÁ TRỊ của một cột phân loại: 0 thành "Sống sót".

Biểu đồ vẽ nhóm bằng đúng giá trị trong dữ liệu, nên một cột cờ 0/1 hiện ra
"cột=0" và "cột=1": đúng, mà người đọc báo cáo không hiểu gì. Chỗ này trả lời câu
hỏi "giá trị này gọi bằng tiếng Việt là gì", theo hai nguồn:

1. Người dùng khai trong bảng chú giải, ô "Nhãn giá trị": `0 = Sống sót; 1 = Phá
   sản`. Khai tay thắng, theo TỪNG giá trị.
2. Tự suy cho cột CỜ (đúng hai giá trị 0/1 hoặc False/True) đã có chú giải: 1 là
   nghĩa của cột, 0 là "Không" cộng nghĩa đó. Việc code làm được thì không giao
   cho model, và không cần đọc một dòng dữ liệu nào ngoài danh sách giá trị.

Không có nguồn nào thì giữ nguyên giá trị gốc. Không viết cứng tên cột nào ở đây:
nhãn đến từ dữ liệu và từ người dùng, nên dùng được cho mọi bộ dữ liệu.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

import pandas as pd

from analysis_system.services.asked_columns import ALTERNATIVES

VALUES_FILE: Final[str] = "nhan_gia_tri.json"

# Cột có nhiều giá trị hơn thế này thì không còn là một phép phân loại để đặt
# nhãn; cũng là số cột tối đa một biểu đồ cột vẽ.
MAX_CATEGORIES: Final[int] = 12

# Cột cờ: đúng hai giá trị, viết như trong khóa chỉ số (`astype(str)`).
FLAGS: Final[frozenset[frozenset[str]]] = frozenset(
    {frozenset({"0", "1"}), frozenset({"0.0", "1.0"}), frozenset({"False", "True"})}
)
TRUTHY: Final[frozenset[str]] = frozenset({"1", "1.0", "True"})

# Một cặp "giá trị = nhãn"; các cặp cách nhau bằng dấu chấm phẩy hoặc xuống dòng.
PAIR_SEPARATOR: Final[re.Pattern[str]] = re.compile(r"\s*;\s*|\n")


def _order(value: str) -> tuple[int, float, str]:
    """Số theo thứ tự số (2 trước 10), chữ theo thứ tự chữ, số đứng trước."""
    try:
        return (0, float(value), value)
    except ValueError:
        return (1, 0.0, value)


def categories_of(frame: pd.DataFrame) -> dict[str, list[str]]:
    """Cột phân loại của bảng, và các giá trị của nó viết đúng như trong khóa chỉ số.

    Cùng luật với chỗ chọn cột chia nhóm: đủ ít giá trị để là nhóm, hơn một để có
    gì mà so, và mỗi nhóm có hơn một dòng. Khác một điều: cột SỐ cũng tính, vì cờ
    0/1 là một cột số.
    """
    found: dict[str, list[str]] = {}
    rows = len(frame)
    for name in frame.columns:
        column = frame[name].dropna()
        distinct = int(column.nunique())
        if 2 <= distinct <= MAX_CATEGORIES and distinct * 2 <= rows:
            found[str(name)] = sorted({str(value) for value in column.astype(str)}, key=_order)
    return found


def parse_labels(text: str) -> dict[str, str]:
    """`0 = Sống sót; 1 = Phá sản` thành `{"0": "Sống sót", "1": "Phá sản"}`."""
    labels: dict[str, str] = {}
    for part in PAIR_SEPARATOR.split(str(text)):
        value, separator, label = part.partition("=")
        value, label = value.strip(), " ".join(label.split())
        if separator and value and label:
            labels[value] = label
    return labels


def labels_text(labels: Mapping[str, str]) -> str:
    """Viết lại đúng dạng người dùng gõ trong ô Nhãn giá trị."""
    return "; ".join(f"{value} = {label}" for value, label in labels.items())


def display_name(meaning: str) -> str:
    """Tên hiển thị của một cột: cách gọi đầu tiên trong chú giải, viết hoa chữ đầu."""
    first = next((part.strip() for part in ALTERNATIVES.split(meaning) if part.strip()), "")
    return first[:1].upper() + first[1:]


def suggested(values: Sequence[str], meaning: str) -> dict[str, str]:
    """Nhãn tự suy cho một cột cờ: 1 là nghĩa của cột, 0 là "Không" cộng nghĩa đó.

    Cột không phải cờ, hoặc chưa có chú giải, thì không đoán: một nhãn đoán sai
    trên biểu đồ tệ hơn giá trị gốc.
    """
    said = display_name(meaning)
    if not said or frozenset(values) not in FLAGS:
        return {}
    # "không có con" mà thêm "Không" thành "Không không có con": không tự suy.
    if said.lower().startswith("không "):
        return {}
    plain = said[:1].lower() + said[1:]
    return {value: said if value in TRUTHY else f"Không {plain}" for value in values}


def read_labels(run_dir: Path) -> dict[str, dict[str, str]]:
    """Nhãn giá trị người dùng đã khai, theo cột. Tệp hỏng thì coi như chưa khai."""
    path = run_dir / VALUES_FILE
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        str(column): {str(value): str(label) for value, label in values.items() if label}
        for column, values in raw.items()
        if isinstance(values, dict)
    }


def write_labels(run_dir: Path, labels: Mapping[str, Mapping[str, str]]) -> None:
    """THAY toàn bộ nhãn giá trị đã khai. Cột không còn nhãn nào thì bỏ."""
    kept = {column: dict(values) for column, values in labels.items() if values}
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / VALUES_FILE).write_text(json.dumps(kept, ensure_ascii=False, indent=1), "utf-8")


def effective_labels(
    categories: Mapping[str, Sequence[str]],
    saved: Mapping[str, Mapping[str, str]],
    meanings: Mapping[str, str],
) -> dict[str, dict[str, str]]:
    """Nhãn dùng khi vẽ: khai tay thắng theo TỪNG giá trị, còn lại tự suy."""
    found: dict[str, dict[str, str]] = {}
    for column, values in categories.items():
        auto = suggested(values, meanings.get(column, ""))
        mine = saved.get(column, {})
        merged = {value: label for value in values if (label := mine.get(value) or auto.get(value))}
        if merged:
            found[column] = merged
    return found
