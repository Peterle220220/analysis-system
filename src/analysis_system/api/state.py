"""Các quyết định trạng thái dùng chung cho HTML cũ và JSON API.

Module này không biết gì về cách trình bày. Nó chỉ đọc Workspace và trả về
những cờ mà cả ``render.py`` lẫn ``view.py`` phải hiểu giống nhau.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Final

from analysis_system.application.workspace import ServiceError, Workspace
from analysis_system.domains.execution_engine.forecast import (
    Projection,
    Refusal,
    project,
    series_in,
)
from analysis_system.models.base import ROUND_MARK


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
            return Status("stopped", "đã dừng, xem chi tiết")
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


# --- noi lai bang tieng nguoi nhung gi he thong KHONG ket luan -----------------
#
# Chuyen tu render.py sang day de ban Python va ban Next dung CHUNG mot ban. Ban
# Next viet moi, khong dung chung dong nao voi render.py, nen truoc day no in
# thang cau may: "cau chot co con so go truc tiep - moi so phai la placeholder".
# Hai ban sao cua mot luat la hai cau tra loi dang cho de mau thuan voi nhau.

# Dong noi voi nguoi cau hinh he thong, khong phai nguoi doc.
FOR_OPERATORS: Final[tuple[str, ...]] = ("tests.regressions", "'tests'")

# Nhung gi he thong KHONG ket luan, chia theo dung hai loai khac nhau. Truoc day
# ca hai nam chung mot khoi ten "Khong ket luan duoc", nen viec he thong tu gioi
# han de tranh ket luan sai trong y het mot that bai.
GAP_KINDS: Final[tuple[tuple[str, str, tuple[str, ...]], ...]] = (
    (
        "Đã giới hạn để tránh kết luận sai",
        "Chạy càng nhiều phép kiểm thì càng dễ có kết quả trông có ý nghĩa "
        "nhưng thật ra là ngẫu nhiên, nên hệ thống tự dừng ở 8 phép mỗi loại.",
        ("chỉ chạy", "ngẫu nhiên"),
    ),
    (
        "Dữ liệu chưa đủ để nói",
        "Các nhóm quá ít dòng thì con số trung bình của nhóm không nói lên điều gì.",
        ("quá ít", "đủ lớn", "cần ít nhất", "không đổi"),
    ),
)

BLOCKED_KINDS: Final[tuple[tuple[str, str, tuple[str, ...]], ...]] = (
    (
        "nói sai so với dữ liệu",
        "Hệ thống đối chiếu lại với số đã đo và thấy không khớp.",
        ("nhung nhom cao nhat that su", "nhưng nhóm cao nhất thật sự"),
    ),
    (
        "không dẫn được về chỉ số nào",
        "Mọi con số phải truy được về một phép đo. Câu này gõ số thẳng vào, "
        "hoặc dẫn tới một chỉ số không tồn tại.",
        ("go truc tiep", "gõ trực tiếp", "metric_keys", "placeholder"),
    ),
    (
        "không trả lời câu hỏi đã hỏi",
        "Đúng nhưng lạc đề.",
        ("khong tra loi cau hoi", "không trả lời câu hỏi", "khong lien quan"),
    ),
)

OTHER_NOTES: Final[str] = "Ghi chú khác"


def for_operators_only(line: str) -> bool:
    """Dòng này nói với người cấu hình hệ thống, không phải người đọc."""
    return any(mark in line for mark in FOR_OPERATORS)


def kind_of(line: str) -> str:
    """Dòng không kết luận được này thuộc loại nào; rỗng nếu không loại nào."""
    lowered = line.lower()
    for title, _, marks in GAP_KINDS:
        if any(mark in lowered for mark in marks):
            return title
    return ""


def blocked_kind(line: str) -> tuple[str, str]:
    """Câu này bị chặn vì loại lý do nào, và giải thích của loại đó."""
    lowered = line.lower()
    for title, explain, marks in BLOCKED_KINDS:
        if any(mark.lower() in lowered for mark in marks):
            return title, explain
    return "bị chặn vì lý do khác", ""


def gap_groups(lines: Iterable[str]) -> list[dict[str, Any]]:
    """Những gì không kết luận được, chia loại, bỏ dòng dành cho người cấu hình."""
    groups: dict[str, list[str]] = {}
    for line in (str(item) for item in lines):
        if not for_operators_only(line):
            groups.setdefault(kind_of(line), []).append(line)
    found = [
        {"title": title, "explain": explain, "items": groups[title]}
        for title, explain, _ in GAP_KINDS
        if groups.get(title)
    ]
    if groups.get(""):
        found.append({"title": OTHER_NOTES, "explain": "", "items": groups[""]})
    return found


def blocked_groups(lines: Iterable[str]) -> list[dict[str, Any]]:
    """Những kết luận bị chặn, gom theo loại lý do."""
    groups: dict[str, list[str]] = {}
    explains: dict[str, str] = {}
    for line in (str(item) for item in lines):
        title, explain = blocked_kind(line)
        groups.setdefault(title, []).append(line)
        explains[title] = explain
    return [
        {"title": title, "explain": explains[title], "items": items}
        for title, items in groups.items()
    ]
