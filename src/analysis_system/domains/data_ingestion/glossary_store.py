"""Bảng chú giải cột: lưu riêng, không nằm chung trong ô Bối cảnh.

Trước đây chú giải nằm chung trong ô Bối cảnh, và ô đó chỉ giữ 2.000 ký tự. Một
bảng 96 cột dài gấp đôi, nên nửa sau bị cắt mà trang vẫn báo đã lưu. Quay lại
trang thì bảng không hiện lại, chỉ còn nút soạn nháp; soạn lại thì bản mới được
NỐI vào bản cũ, và hai dòng cùng một cột gộp thành "nghĩa cũ; nghĩa mới".

Giờ mỗi bộ dữ liệu có một tệp chú giải riêng, và lưu là THAY cả bảng. Những dòng
`cột = nghĩa` người dùng đã viết trong ô Bối cảnh vẫn đọc được, cho tới lần lưu
bảng đầu tiên chuyển chúng sang đây.

Cả bảng không dán vào mọi prompt: model chỉ được đưa những dòng của cột mà câu
hỏi nhắc tới. Code đối chiếu thì đọc cả bảng, qua một tham số riêng của task.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from analysis_system.domains.ai_planner.asked_columns import (
    GLOSSARY_LINE,
    _meanings_by_column,
    _tidy,
    named_by,
    parse_glossary,
)

GLOSSARY_FILE: Final[str] = "chu_giai.txt"

# Tham số của task mang bảng chú giải cho code đối chiếu (chọn phép kiểm, cảnh
# báo cột bị bỏ sót). Tách khỏi `boi_canh`, thứ đi thẳng vào prompt.
GLOSSARY_PARAM: Final[str] = "chu_giai"

# Chặn an toàn, không phải để cắt: vượt thì báo lỗi. 200 cột, mỗi dòng 200 ký
# tự mới tới 40.000; quá xa mức đó thì không còn là một bảng chú giải.
MAX_CHARACTERS: Final[int] = 200_000


class GlossaryTooLongError(ValueError):
    """Bảng chú giải dài quá mức một bảng chú giải thật có thể dài."""


def read_glossary(run_dir: Path) -> str:
    """Bảng chú giải đã lưu của bộ dữ liệu này, hoặc rỗng."""
    path = run_dir / GLOSSARY_FILE
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def as_text(rows: Iterable[tuple[str, str]]) -> str:
    """Các dòng `cột = nghĩa`: bỏ dòng để trống, mỗi cột đúng một dòng."""
    seen: set[str] = set()
    lines: list[str] = []
    for column, meaning in rows:
        name, said = _tidy(column), " ".join(str(meaning).split())
        if not name or not said or name in seen:
            continue
        seen.add(name)
        lines.append(f"{name} = {said}")
    return "\n".join(lines)


def write_glossary(run_dir: Path, rows: Iterable[tuple[str, str]]) -> str:
    """THAY cả bảng chú giải đã lưu. Không nối vào bản cũ.

    Returns:
        Đúng phần đã ghi.

    Raises:
        GlossaryTooLongError: dài quá `MAX_CHARACTERS`. Không cắt ngầm: cắt ngầm
            chính là lỗi đã làm mất nửa bảng chú giải.
    """
    text = as_text(rows)
    if len(text) > MAX_CHARACTERS:
        raise GlossaryTooLongError(
            f"Bảng chú giải dài {len(text)} ký tự, quá giới hạn {MAX_CHARACTERS}."
        )
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / GLOSSARY_FILE).write_text(text, encoding="utf-8")
    return text


def rows_for(columns: Sequence[str], saved: str, context: str) -> list[tuple[str, str]]:
    """Mỗi cột có thật một dòng, theo thứ tự của bảng: nghĩa đã lưu, hoặc rỗng.

    Tệp chú giải thắng theo TỪNG CỘT; dòng cũ trong ô Bối cảnh chỉ lấp những cột
    tệp chưa có. Không gộp hai nguồn thành "cũ; mới": gộp như thế chính là cách
    lỗi trùng từ vựng sinh ra.
    """
    from_file = _meanings_by_column(parse_glossary(saved), columns)
    from_context = _meanings_by_column(parse_glossary(context), columns)
    return [
        (column, "; ".join(from_file.get(column) or from_context.get(column) or []))
        for column in columns
    ]


def without_glossary_lines(context: str, columns: Sequence[str]) -> tuple[str, int]:
    """Ô Bối cảnh sau khi chuyển các dòng chú giải trỏ tới cột có thật đi.

    Dòng không trỏ tới cột nào thì để lại: trang đang báo chúng ra để người dùng
    sửa, chuyển đi thì chúng biến mất không lời.

    Returns:
        (phần còn lại, số dòng đã chuyển).
    """
    real = {_tidy(name) for name in columns}
    kept: list[str] = []
    moved = 0
    for line in str(context).splitlines():
        matched = GLOSSARY_LINE.match(line)
        if (
            matched is not None
            and matched.group(2).strip()
            and (_tidy(matched.group(1)) in real or _tidy(matched.group(2)) in real)
        ):
            moved += 1
            continue
        kept.append(line)
    return "\n".join(kept).strip(), moved


def for_prompt(context: str, glossary: str, question: str) -> str:
    """Bối cảnh gửi cho model: phần người dùng viết, cộng đúng những dòng chú
    giải của cột mà câu hỏi nhắc tới.

    Không có bảng chú giải, hoặc câu hỏi không nhắc cột nào, thì trả nguyên văn:
    prompt không đổi một chữ.
    """
    table = parse_glossary(glossary)
    if not table:
        return context
    asked = named_by(question, list(table), table)
    present = {line.strip() for line in str(context).splitlines()}
    extra = [
        line
        for column, meaning in table.items()
        if column in asked and (line := f"{column} = {meaning}") not in present
    ]
    if not extra:
        return context
    return "\n".join(part for part in (context.strip(), *extra) if part)


def glossary_of(params: Mapping[str, Any], context_param: str) -> str:
    """Bảng chú giải cho code đối chiếu, đọc từ tham số của task.

    Kế hoạch chưa mang tham số riêng (không có bảng chú giải đã lưu, hoặc kế
    hoạch cũ) thì đọc từ ô Bối cảnh như trước.
    """
    if GLOSSARY_PARAM in params:
        return str(params.get(GLOSSARY_PARAM) or "")
    return str(params.get(context_param) or "")
