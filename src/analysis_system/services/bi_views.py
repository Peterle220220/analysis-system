"""Bản tự phân tích đã lưu: mỗi bản một cấu hình kéo thả có tên, theo bộ dữ liệu.

Lưu thành một tệp JSON trong thư mục của bộ dữ liệu, cạnh bảng chú giải: xoá bộ
dữ liệu là xoá luôn các bản của nó, và không cần một máy chủ cơ sở dữ liệu
riêng. Ghi qua tệp tạm rồi đổi tên, để một lần ghi dở không làm hỏng các bản đã
lưu.

Tên cột trong bản lưu không bị đối chiếu với bảng lúc lưu: bảng có thể được làm
sạch lại và đổi cột. Trang tự bỏ những cột không còn khi mở lại, và nói ra.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator
from pydantic import Field as Default

from analysis_system.services.bi_query import AGGREGATIONS

VIEWS_FILE: Final[str] = "ban_tu_phan_tich.json"
MAX_VIEWS: Final[int] = 200
MAX_NAME: Final[int] = 120

Chart = Literal[
    "auto", "bar", "stacked", "stacked100", "line", "donut", "waterfall", "scatter", "table"
]


class ViewError(ValueError):
    """Không lưu hay xoá được. Câu lỗi viết để hiện thẳng cho người dùng."""


class ViewFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    role: Literal["dimension", "measure"]
    values: list[str] = Default(default_factory=list)
    min: float | None = None
    max: float | None = None


class ViewState(BaseModel):
    """Đúng những gì trang kéo thả cần để dựng lại một biểu đồ."""

    model_config = ConfigDict(extra="forbid")

    x: str | None = None
    y: str | None = None
    aggregation: str = "mean"
    color: str | None = None
    filters: list[ViewFilter] = Default(default_factory=list)
    chart: Chart = "auto"

    @field_validator("aggregation")
    @classmethod
    def _known_aggregation(cls, value: str) -> str:
        if value not in AGGREGATIONS:
            raise ValueError(f"không có phép gộp '{value}'")
        return value


class SavedView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    state: ViewState
    created_at: str
    updated_at: str


def _path(run_dir: Path) -> Path:
    return run_dir / VIEWS_FILE


def list_views(run_dir: Path) -> list[SavedView]:
    """Các bản đã lưu của bộ dữ liệu, bản sửa gần nhất trước.

    Một dòng hỏng trong tệp thì bỏ qua dòng đó, không làm mất cả danh sách.
    """
    path = _path(run_dir)
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    views: list[SavedView] = []
    for entry in raw if isinstance(raw, list) else []:
        try:
            views.append(SavedView.model_validate(entry))
        except ValidationError:
            continue
    return sorted(views, key=lambda view: view.updated_at, reverse=True)


def _write(run_dir: Path, views: list[SavedView]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    target = _path(run_dir)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(
        json.dumps([view.model_dump() for view in views], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(target)


def _clean_name(name: str) -> str:
    tidy = " ".join(str(name).split())
    if not tidy:
        raise ViewError("Hãy đặt tên cho bản phân tích.")
    if len(tidy) > MAX_NAME:
        raise ViewError(f"Tên dài {len(tidy)} ký tự, tối đa {MAX_NAME}.")
    return tidy


def save_view(
    run_dir: Path,
    name: str,
    state: ViewState,
    view_id: str | None = None,
    now: datetime | None = None,
) -> SavedView:
    """Lưu một bản: không có `view_id` thì tạo bản mới, có thì ghi đè đúng bản đó.

    Raises:
        ViewError: tên trống hay quá dài, quá số bản tối đa, hoặc không có bản cần sửa.
    """
    tidy = _clean_name(name)
    moment = (now or datetime.now(UTC)).isoformat()
    views = list_views(run_dir)
    if view_id is None:
        if len(views) >= MAX_VIEWS:
            raise ViewError(f"Bộ dữ liệu này đã có {MAX_VIEWS} bản; hãy xoá bớt bản cũ.")
        saved = SavedView(
            id=uuid.uuid4().hex[:12], name=tidy, state=state, created_at=moment, updated_at=moment
        )
        _write(run_dir, [*views, saved])
        return saved
    found = next((view for view in views if view.id == view_id), None)
    if found is None:
        raise ViewError("Không có bản phân tích này; có thể nó đã bị xoá.")
    saved = found.model_copy(update={"name": tidy, "state": state, "updated_at": moment})
    _write(run_dir, [saved if view.id == view_id else view for view in views])
    return saved


def delete_view(run_dir: Path, view_id: str) -> bool:
    """Xoá một bản. Trả False khi không có bản đó."""
    views = list_views(run_dir)
    kept = [view for view in views if view.id != view_id]
    if len(kept) == len(views):
        return False
    _write(run_dir, kept)
    return True
