"""Dashboard: tao, ghim widget, doi cho va doi co, xoa; widget khong giu so lieu."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from analysis_system.services.dashboards import (
    DASHBOARDS_FILE,
    DashboardError,
    Layout,
    Widget,
    WidgetDraft,
    add_widget,
    create_dashboard,
    default_size,
    delete_dashboard,
    get_dashboard,
    list_dashboards,
    replace_dashboard,
)

NOW = datetime(2026, 9, 14, 9, 0, tzinfo=UTC)
STATE = {"x": "Bankrupt?", "y": "Debt ratio %"}
BI = {"kind": "bi", "title": "Nợ", "bi": {"dataset": "bankruptcy", "state": STATE}}
CLAIM = {"kind": "claim", "claim": {"dataset": "bankruptcy", "round": "bankruptcy__q5", "index": 0}}
TITLE = {"kind": "text", "text": {"style": "title", "text": "BÁO CÁO TÀI CHÍNH QUÝ 3"}}
PLACE = {"x": 0, "y": 0, "w": 6, "h": 9}


def draft(value: Mapping[str, object]) -> WidgetDraft:
    return WidgetDraft.model_validate(value)


def test_pinned_widgets_stack_down_the_left_edge(tmp_path: Path) -> None:
    board = create_dashboard(tmp_path, "  Báo cáo   quý 3 ", now=NOW)
    assert board.name == "Báo cáo quý 3"
    add_widget(tmp_path, board.id, draft(TITLE), now=NOW)
    add_widget(tmp_path, board.id, draft(BI), now=NOW)
    after = add_widget(tmp_path, board.id, draft(CLAIM), now=NOW)
    layouts = [widget.layout for widget in after.widgets]
    assert [(item.x, item.y, item.w, item.h) for item in layouts] == [
        (0, 0, 12, 2),
        (0, 2, 6, 9),
        (0, 11, 6, 9),
    ]
    assert get_dashboard(tmp_path, board.id) == after


def test_a_widget_keeps_its_source_not_its_numbers(tmp_path: Path) -> None:
    board = create_dashboard(tmp_path, "Một", now=NOW)
    saved = add_widget(tmp_path, board.id, draft(BI), now=NOW).widgets[0]
    assert saved.bi is not None
    assert saved.bi.dataset == "bankruptcy"
    assert saved.bi.state.x == "Bankrupt?"
    assert "values" not in saved.model_dump_json()


def test_moving_and_resizing_is_saved_as_the_whole_layout(tmp_path: Path) -> None:
    board = create_dashboard(tmp_path, "Một", now=NOW)
    board = add_widget(tmp_path, board.id, draft(BI), now=NOW)
    board = add_widget(tmp_path, board.id, draft(CLAIM), now=NOW)
    moved = [
        board.widgets[0].model_copy(update={"layout": Layout(x=6, y=0, w=6, h=12)}),
        board.widgets[1].model_copy(update={"layout": Layout(x=0, y=0, w=6, h=12)}),
    ]
    saved = replace_dashboard(tmp_path, board.id, "Đổi tên", moved, now=NOW + timedelta(hours=1))
    assert saved.name == "Đổi tên"
    assert [(widget.layout.x, widget.layout.h) for widget in saved.widgets] == [(6, 12), (0, 12)]
    removed = replace_dashboard(tmp_path, board.id, "Đổi tên", moved[:1], now=NOW)
    assert len(removed.widgets) == 1


def test_a_layout_cannot_leave_the_twelve_column_grid() -> None:
    with pytest.raises(ValidationError):
        Layout(x=8, y=0, w=6, h=4)
    with pytest.raises(ValidationError):
        Layout(x=0, y=0, w=0, h=4)


def test_a_widget_must_carry_exactly_the_source_of_its_kind() -> None:
    with pytest.raises(ValidationError):
        WidgetDraft.model_validate({"kind": "bi", "text": {"text": "x"}})
    with pytest.raises(ValidationError):
        WidgetDraft.model_validate({**BI, "claim": CLAIM["claim"]})
    escape = {"dataset": "../x", "round": "a", "index": 0}
    with pytest.raises(ValidationError):
        WidgetDraft.model_validate({"kind": "claim", "claim": escape})
    with pytest.raises(ValidationError):
        WidgetDraft.model_validate({"kind": "text", "text": {"text": "x" * 6000}})
    with pytest.raises(ValidationError):
        WidgetDraft.model_validate({**TITLE, "sql": "DROP TABLE t"})


def test_what_cannot_be_done_is_refused_in_words(tmp_path: Path) -> None:
    with pytest.raises(DashboardError, match="đặt tên"):
        create_dashboard(tmp_path, "  ")
    with pytest.raises(DashboardError, match="đã bị xoá"):
        add_widget(tmp_path, "000000000000", draft(BI))
    board = create_dashboard(tmp_path, "Một", now=NOW)
    board = add_widget(tmp_path, board.id, draft(BI), now=NOW)
    twice = [board.widgets[0], board.widgets[0]]
    with pytest.raises(DashboardError, match="trùng mã"):
        replace_dashboard(tmp_path, board.id, "Một", twice)


def test_text_boxes_start_wide_for_titles_and_half_for_paragraphs() -> None:
    assert default_size(draft(TITLE)) == (12, 2)
    assert default_size(draft({"kind": "text", "text": {"style": "body", "text": ""}})) == (6, 4)
    assert default_size(draft(BI)) == (6, 9)


def test_boards_are_listed_newest_first_and_deleted_one_at_a_time(tmp_path: Path) -> None:
    first = create_dashboard(tmp_path, "Một", now=NOW)
    second = create_dashboard(tmp_path, "Hai", now=NOW + timedelta(minutes=1))
    assert [board.id for board in list_dashboards(tmp_path)] == [second.id, first.id]
    assert delete_dashboard(tmp_path, first.id) is True
    assert delete_dashboard(tmp_path, first.id) is False
    assert [board.name for board in list_dashboards(tmp_path)] == ["Hai"]


def test_one_broken_board_does_not_lose_the_others(tmp_path: Path) -> None:
    kept = create_dashboard(tmp_path, "Còn", now=NOW)
    path = tmp_path / DASHBOARDS_FILE
    path.write_text(path.read_text(encoding="utf-8")[:-2] + ', {"id": 1}]', encoding="utf-8")
    assert [board.id for board in list_dashboards(tmp_path)] == [kept.id]
    assert sorted(item.name for item in tmp_path.iterdir()) == [DASHBOARDS_FILE]


def test_a_saved_widget_keeps_its_id_and_layout() -> None:
    widget = Widget.model_validate({**BI, "id": "a" * 12, "layout": PLACE})
    assert widget.id == "a" * 12
    with pytest.raises(ValidationError):
        Widget.model_validate({**BI, "id": "../../x", "layout": PLACE})
