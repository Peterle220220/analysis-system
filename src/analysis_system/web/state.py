"""Các quyết định trạng thái dùng chung cho HTML cũ và JSON API.

Module này không biết gì về cách trình bày. Nó chỉ đọc Workspace và trả về
những cờ mà cả ``render.py`` lẫn ``view.py`` phải hiểu giống nhau.
"""

from __future__ import annotations

from dataclasses import dataclass

from analysis_system.api import ServiceError, Workspace
from analysis_system.services.forecast import Projection, Refusal, project, series_in
from analysis_system.web.naming import ROUND_MARK


@dataclass(frozen=True)
class Status:
    """Một trạng thái nghiệp vụ, gồm mã ổn định và nhãn cho người dùng."""

    key: str
    label: str


@dataclass(frozen=True)
class Forecast:
    """Một dự báo đã được tính ở Python, luôn tách khỏi số đo."""

    name: str
    last_period: str
    low: float
    high: float
    r2: float
    periods: int
    caveat: str


def forecast_values(measured: dict[str, float]) -> tuple[Forecast, ...]:
    """Các ước lượng đủ điều kiện, dùng chung cho HTML và JSON."""
    found: list[Forecast] = []
    for name, pairs in sorted(series_in(measured).items()):
        projection = project([value for _, value in pairs], ahead=1)
        if isinstance(projection, Refusal):
            continue
        if not isinstance(projection, Projection):  # pragma: no cover - type guard
            continue
        found.append(
            Forecast(
                name=name,
                last_period=pairs[-1][0],
                low=projection.low,
                high=projection.high,
                r2=projection.r2,
                periods=len(pairs),
                caveat=projection.caveat,
            )
        )
    return tuple(found)


def pending_count(space: Workspace, run_id: str) -> int:
    """Số gate còn chờ duyệt; lỗi đọc state được coi là không có gate."""
    try:
        return len(space.gates(run_id))
    except ServiceError:
        return 0


def round_has_result(space: Workspace, run_id: str) -> bool:
    """Một lượt có nội dung để xem: câu trả lời hoặc gate đang chờ."""
    if pending_count(space, run_id):
        return True
    try:
        return space.answer(run_id) is not None
    except ServiceError:
        return False


def round_is_active(space: Workspace, run_id: str) -> bool:
    """Một lượt còn đang chạy hoặc đang chờ người duyệt."""
    if pending_count(space, run_id):
        return True
    try:
        return space.running(run_id)
    except ServiceError:
        return False


def dataset_status(space: Workspace, run_id: str) -> Status:
    """Trạng thái của cả bộ dữ liệu."""
    try:
        if space.running(run_id):
            return Status("running", "đang làm sạch")
        if space.gates(run_id):
            return Status("waiting", "chờ bạn duyệt")
        stopped = space.why_stopped(run_id)
        if stopped:
            return Status("stopped", "đã dừng — xem chi tiết")
        if space.clean_table(run_id):
            return Status("ready", "sẵn sàng để hỏi")
        return Status("unclean", "chưa làm sạch")
    except ServiceError:
        return Status("unreadable", "không đọc được")


def round_status(space: Workspace, run_id: str) -> Status:
    """Trạng thái của một lượt hỏi, kể cả khi lượt đó không có answer."""
    if pending_count(space, run_id):
        return Status("waiting", "Đang chờ bạn duyệt.")
    try:
        answer = space.answer(run_id)
    except ServiceError:
        answer = None
    if answer is not None:
        return Status("answered", f"{len(answer.claims)} kết luận.")
    try:
        reason = space.why_stopped(run_id)
    except ServiceError:
        reason = ""
    return Status("unanswered", reason or "Chưa có câu trả lời.")


def _round_number(run_id: str) -> tuple[int, str]:
    """Sắp xếp lượt theo số sau ``__q``, không theo thứ tự chữ."""
    _, mark, tail = run_id.partition(ROUND_MARK)
    if mark and tail.isdigit():
        return (int(tail), "")
    return (10**9, run_id)


def split_rounds(
    space: Workspace, rounds: list[tuple[str, str]]
) -> tuple[list[tuple[str, str]], list[tuple[str, str]], list[tuple[str, str]]]:
    """Chia lượt thành done/running/broken bằng đúng một quyết định."""
    oldest_first = sorted(rounds, key=lambda item: _round_number(item[0]))
    done: list[tuple[str, str]] = []
    running: list[tuple[str, str]] = []
    broken: list[tuple[str, str]] = []
    for pair in oldest_first:
        if round_has_result(space, pair[0]):
            done.append(pair)
        elif round_is_active(space, pair[0]):
            running.append(pair)
        else:
            broken.append(pair)
    return done, running, broken
