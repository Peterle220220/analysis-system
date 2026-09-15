"""Dashboard: một trang trình bày ghép widget từ hai luồng và hộp văn bản.

Widget KHÔNG giữ số liệu (chủ hệ thống chọn widget "sống"): widget Tự phân tích
giữ bộ dữ liệu và cấu hình kéo thả, widget kết luận giữ lượt hỏi và số thứ tự
kết luận; trang tính lại mỗi lần mở. Nguồn bị xoá thì widget nói ra, không hiện
số cũ.

Một Dashboard gom widget của nhiều bộ dữ liệu nên không thuộc thư mục của bộ
nào. Cả sổ là một tệp JSON ở gốc thư mục runs, không phải một thư mục con:
`retention.runs` coi mọi thư mục ở đó là một lần chạy. Ghi qua tệp tạm rồi đổi
tên, có khoá cho hai lần ghi cùng lúc.
"""

from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator
from pydantic import Field as Default

from analysis_system.domains.visualization.bi_views import ViewState

DASHBOARDS_FILE: Final[str] = "bang_dieu_khien.json"
GRID_COLUMNS: Final[int] = 12
MAX_DASHBOARDS: Final[int] = 100
MAX_WIDGETS: Final[int] = 60
MAX_TEXT: Final[int] = 5000
MAX_NAME: Final[int] = 120
# Mã bộ dữ liệu và lượt hỏi: chữ, số, gạch dưới (như `api_id_is_safe`).
SAFE_ID: Final[str] = r"^[A-Za-z0-9_]{1,120}$"
KEY: Final[str] = r"^[0-9a-f]{12}$"

_LOCK = threading.Lock()


class DashboardError(ValueError):
    """Không làm được. Câu lỗi viết để hiện thẳng cho người dùng."""


class Layout(BaseModel):
    """Vị trí trên lưới 12 cột; mọi con số là ô lưới, nên luôn thẳng hàng."""

    model_config = ConfigDict(extra="forbid")

    x: int = Default(ge=0, lt=GRID_COLUMNS)
    y: int = Default(ge=0, le=10_000)
    w: int = Default(ge=1, le=GRID_COLUMNS)
    h: int = Default(ge=1, le=60)

    @model_validator(mode="after")
    def _inside_grid(self) -> Layout:
        if self.x + self.w > GRID_COLUMNS:
            raise ValueError(f"widget tràn khỏi lưới {GRID_COLUMNS} cột")
        return self


class BiSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset: str = Default(pattern=SAFE_ID)
    state: ViewState


class ClaimSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset: str = Default(pattern=SAFE_ID)
    round: str = Default(pattern=SAFE_ID)
    index: int = Default(ge=0, le=500)


class TextBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    style: Literal["title", "subtitle", "body"] = "body"
    text: str = Default(default="", max_length=MAX_TEXT)


class WidgetDraft(BaseModel):
    """Một widget chưa có chỗ trên lưới: đúng một nguồn khớp với loại."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["bi", "claim", "text"]
    title: str = Default(default="", max_length=200)
    bi: BiSource | None = None
    claim: ClaimSource | None = None
    text: TextBody | None = None

    @model_validator(mode="after")
    def _one_source(self) -> WidgetDraft:
        present = {name for name in ("bi", "claim", "text") if getattr(self, name) is not None}
        if present != {self.kind}:
            raise ValueError(f"widget loại '{self.kind}' phải có đúng phần '{self.kind}'")
        return self


class Widget(WidgetDraft):
    id: str = Default(pattern=KEY)
    layout: Layout


class Dashboard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Default(pattern=KEY)
    name: str
    widgets: list[Widget] = Default(default_factory=list, max_length=MAX_WIDGETS)
    created_at: str
    updated_at: str


def _path(root: Path) -> Path:
    return root / DASHBOARDS_FILE


def _read(root: Path) -> list[Dashboard]:
    try:
        raw = json.loads(_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    found: list[Dashboard] = []
    for entry in raw if isinstance(raw, list) else []:
        try:
            found.append(Dashboard.model_validate(entry))
        except ValidationError:
            continue
    return found


def _write(root: Path, boards: list[Dashboard]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    target = _path(root)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(
        json.dumps([board.model_dump() for board in boards], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(target)


def _clean_name(name: str) -> str:
    tidy = " ".join(str(name).split())
    if not tidy:
        raise DashboardError("Hãy đặt tên cho Dashboard.")
    if len(tidy) > MAX_NAME:
        raise DashboardError(f"Tên dài {len(tidy)} ký tự, tối đa {MAX_NAME}.")
    return tidy


def _moment(now: datetime | None) -> str:
    return (now or datetime.now(UTC)).isoformat()


def list_dashboards(root: Path) -> list[Dashboard]:
    """Mọi Dashboard, bản sửa gần nhất trước. Một dòng hỏng không làm mất các dòng khác."""
    return sorted(_read(root), key=lambda board: board.updated_at, reverse=True)


def get_dashboard(root: Path, board_id: str) -> Dashboard | None:
    return next((board for board in _read(root) if board.id == board_id), None)


def create_dashboard(root: Path, name: str, now: datetime | None = None) -> Dashboard:
    """Tạo một Dashboard trống.

    Raises:
        DashboardError: tên trống hay quá dài, hoặc đã đủ số Dashboard tối đa.
    """
    tidy = _clean_name(name)
    moment = _moment(now)
    with _LOCK:
        boards = _read(root)
        if len(boards) >= MAX_DASHBOARDS:
            raise DashboardError(f"Đã có {MAX_DASHBOARDS} Dashboard; hãy xoá bớt.")
        board = Dashboard(
            id=uuid.uuid4().hex[:12], name=tidy, created_at=moment, updated_at=moment
        )
        _write(root, [*boards, board])
    return board


def _change(
    root: Path, board_id: str, edit: Callable[[Dashboard], Dashboard], now: datetime | None
) -> Dashboard:
    with _LOCK:
        boards = _read(root)
        found = next((board for board in boards if board.id == board_id), None)
        if found is None:
            raise DashboardError("Không có Dashboard này; có thể nó đã bị xoá.")
        changed = edit(found).model_copy(update={"updated_at": _moment(now)})
        _write(root, [changed if board.id == board_id else board for board in boards])
    return changed


def replace_dashboard(
    root: Path, board_id: str, name: str, widgets: list[Widget], now: datetime | None = None
) -> Dashboard:
    """Ghi lại tên và toàn bộ widget (kéo đổi chỗ, đổi cỡ, sửa chữ, xoá widget).

    Raises:
        DashboardError: không có Dashboard, tên không hợp lệ, quá số widget, hay trùng mã widget.
    """
    tidy = _clean_name(name)
    if len(widgets) > MAX_WIDGETS:
        raise DashboardError(f"Một Dashboard tối đa {MAX_WIDGETS} widget.")
    if len({widget.id for widget in widgets}) != len(widgets):
        raise DashboardError("Hai widget trùng mã.")
    return _change(
        root,
        board_id,
        lambda board: board.model_copy(update={"name": tidy, "widgets": list(widgets)}),
        now,
    )


def default_size(draft: WidgetDraft) -> tuple[int, int]:
    """Cỡ mặc định (cột, hàng) khi mới thả vào lưới."""
    if draft.kind == "text" and draft.text is not None:
        return {"title": (12, 2), "subtitle": (12, 2)}.get(draft.text.style, (6, 4))
    return 6, 9


def add_widget(
    root: Path, board_id: str, draft: WidgetDraft, now: datetime | None = None
) -> Dashboard:
    """Thêm một widget vào cuối lưới (dưới mọi widget đang có), cột trái.

    Raises:
        DashboardError: không có Dashboard, hoặc đã đủ số widget tối đa.
    """
    width, height = default_size(draft)

    def place(board: Dashboard) -> Dashboard:
        if len(board.widgets) >= MAX_WIDGETS:
            raise DashboardError(f"Một Dashboard tối đa {MAX_WIDGETS} widget.")
        bottom = max((widget.layout.y + widget.layout.h for widget in board.widgets), default=0)
        widget = Widget(
            **draft.model_dump(),
            id=uuid.uuid4().hex[:12],
            layout=Layout(x=0, y=bottom, w=width, h=height),
        )
        return board.model_copy(update={"widgets": [*board.widgets, widget]})

    return _change(root, board_id, place, now)


def delete_dashboard(root: Path, board_id: str) -> bool:
    """Xoá một Dashboard. Trả False khi không có."""
    with _LOCK:
        boards = _read(root)
        kept = [board for board in boards if board.id != board_id]
        if len(kept) == len(boards):
            return False
        _write(root, kept)
    return True
