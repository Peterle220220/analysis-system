"""Đọc một cột số viết dạng chữ, theo đúng cách viết số của chính cột đó.

Hai cách viết cùng tồn tại, và đảo nhau:

* quốc tế: phẩy tách nghìn, chấm thập phân, "12,990.52" (báo cáo tải từ web chứng khoán)
* Việt Nam: chấm tách nghìn, phẩy thập phân, "12.990,52"

pandas chỉ biết "12990.52". Gặp "12,990.52" nó bó tay, và cả bốn cột quý của một
báo cáo tài chính bị coi là "không phải cột số" (bộ MBB, 2026-09-15). Gặp "2.000"
nó đọc thành 2.0, và cả cột bị chia 1000 trong im lặng.

Nên cách viết được quyết cho CẢ CỘT, từ những ô chỉ đọc được một cách: "12,990.52"
chỉ có thể là quốc tế, "1.234.567" chỉ có thể là Việt Nam. Một ô như "1,234" hay
"1.000" đọc được cả hai cách, lệch nhau 1000 lần, nên cột chỉ có loại ô đó thì
dừng lại và nói, không đoán (luật chủ hệ thống đã duyệt).
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

import pandas as pd

INTERNATIONAL: Final[str] = "quoc_te"
VIETNAMESE: Final[str] = "viet_nam"

_US_GROUPED: Final[re.Pattern[str]] = re.compile(r"^[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?$")
# Nhom dau khong bat dau bang 0: "0.370" la so thap phan, khong phai "0370".
_VN_GROUPED: Final[re.Pattern[str]] = re.compile(r"^[-+]?[1-9]\d{0,2}(?:\.\d{3})+(?:,\d+)?$")
_DOT_DECIMAL: Final[re.Pattern[str]] = re.compile(
    r"^[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?$"
)
_COMMA_DECIMAL: Final[re.Pattern[str]] = re.compile(r"^[-+]?\d+,\d+$")
_INTEGER: Final[re.Pattern[str]] = re.compile(r"^[-+]?\d+$")
_DOT_AMBIGUOUS: Final[re.Pattern[str]] = re.compile(r"^[-+]?[1-9]\d{0,2}(?:\.\d{3})+$")

_NO_GUESS: Final[str] = "Hai cach hieu lech nhau 1000 lan nen he thong khong tu doan"


@dataclass(frozen=True)
class Convention:
    """Cách viết số của một cột, hoặc vì sao không quyết được."""

    name: str = INTERNATIONAL
    refusal: str = ""
    # Mot o cho thay cach viet nay khac cach pandas tu doc, de noi voi nguoi dung.
    example: str = ""

    def explained(self) -> str:
        """Một câu cho nhật ký làm sạch."""
        if self.name == VIETNAMESE:
            way = "cach viet Viet Nam: dau cham tach hang nghin, dau phay thap phan"
        else:
            way = "cach viet quoc te: dau phay tach hang nghin, dau cham thap phan"
        return f"doc so theo {way} (quyet cho ca cot tu nhung o chi doc duoc mot cach)"


def _is_missing(value: object) -> bool:
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    return isinstance(value, float) and math.isnan(value)


def _texts(values: Iterable[object]) -> list[str]:
    found: list[str] = []
    for value in values:
        if _is_missing(value):
            continue
        text = str(value).strip()
        if text and text.lower() != "nan":
            found.append(text)
    return found


def readings(text: str) -> tuple[bool, bool]:
    """Ô này đọc được theo cách quốc tế không, theo cách Việt Nam không."""
    international = bool(_US_GROUPED.match(text) or _DOT_DECIMAL.match(text))
    vietnamese = bool(_VN_GROUPED.match(text) or _COMMA_DECIMAL.match(text) or _INTEGER.match(text))
    return international, vietnamese


def number_share(values: Iterable[object]) -> float:
    """Tỷ lệ ô đọc được thành số theo ít nhất một cách viết."""
    texts = _texts(values)
    if not texts:
        return 0.0
    return sum(1 for text in texts if any(readings(text))) / len(texts)


def convention_of(values: Iterable[object]) -> Convention:
    """Cách viết số của cột này, quyết từ những ô chỉ đọc được một cách."""
    texts = _texts(values)
    pairs = [(text, readings(text)) for text in texts]
    only_us = [text for text, (us, vn) in pairs if us and not vn]
    only_vn = [text for text, (us, vn) in pairs if vn and not us]
    both = [text for text, (us, vn) in pairs if us and vn]

    if only_us and only_vn:
        return Convention(
            "",
            f"cot nay tron hai cach viet so: {only_us[0]!r} (dau phay tach hang nghin) va "
            f"{only_vn[0]!r} (dau cham tach hang nghin). {_NO_GUESS}",
        )
    if only_vn:
        shown = next((text for text in [*only_vn, *both] if "." in text or "," in text), "")
        return Convention(VIETNAMESE, example=shown)
    if only_us:
        shown = next((text for text in [*only_us, *both] if "," in text), "")
        return Convention(INTERNATIONAL, example=shown)

    # Khong o nao chi doc duoc mot cach.
    comma = [text for text in both if "," in text]
    if comma:
        return Convention(
            "",
            f"cot nay co the viet so theo kieu quoc te - dau phay tach hang nghin "
            f"({comma[0]!r} la {comma[0].replace(',', '')}), hoac theo kieu Viet Nam - dau "
            f"phay thap phan. {_NO_GUESS}",
        )
    dotted = [text for text in both if _DOT_AMBIGUOUS.match(text)]
    if dotted and len(dotted) == len(texts):
        return Convention(
            "",
            f"cot nay co the viet so theo kieu Viet Nam - dau cham tach hang nghin "
            f"(vi du {dotted[0]!r}), hoac la so thap phan ba chu so. {_NO_GUESS}",
        )
    return Convention(INTERNATIONAL)


def to_numbers(values: pd.Series, convention: str) -> pd.Series:
    """Đổi cột thành số theo cách viết đã quyết; ô không đọc được thành NaN."""

    def one(value: object) -> object:
        if not isinstance(value, str):
            return None if _is_missing(value) else value
        text = value.strip()
        if convention == VIETNAMESE:
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
        return text or None

    plain = pd.Series([one(value) for value in values], index=values.index, dtype=object)
    return pd.to_numeric(plain, errors="coerce")
