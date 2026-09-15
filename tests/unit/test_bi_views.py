"""Ban tu phan tich da luu: tao, sua, xoa theo bo du lieu, va khong mat vi mot dong hong."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from analysis_system.domains.visualization.bi_views import (
    VIEWS_FILE,
    ViewError,
    ViewState,
    delete_view,
    list_views,
    save_view,
)

NOW = datetime(2026, 9, 14, 9, 0, tzinfo=UTC)


def state(**values: object) -> ViewState:
    return ViewState.model_validate({"x": "Bankrupt?", "y": "Debt ratio %", **values})


def test_a_saved_view_comes_back_exactly(tmp_path: Path) -> None:
    chosen = state(
        chart="stacked100",
        color="Region",
        filters=[{"field": "Region", "role": "dimension", "values": ["Nam"]}],
    )
    saved = save_view(tmp_path, "  Nợ theo   phá sản ", chosen, now=NOW)
    assert saved.name == "Nợ theo phá sản"
    assert [view.model_dump() for view in list_views(tmp_path)] == [saved.model_dump()]


def test_saving_again_with_an_id_updates_that_view_only(tmp_path: Path) -> None:
    first = save_view(tmp_path, "Một", state(), now=NOW)
    second = save_view(tmp_path, "Hai", state(), now=NOW + timedelta(minutes=1))
    changed = save_view(
        tmp_path, "Một (sửa)", state(chart="donut"), view_id=first.id, now=NOW + timedelta(hours=1)
    )
    views = list_views(tmp_path)
    assert [view.id for view in views] == [first.id, second.id]
    assert views[0].name == "Một (sửa)"
    assert views[0].state.chart == "donut"
    assert changed.created_at == first.created_at


def test_deleting_removes_one_view(tmp_path: Path) -> None:
    first = save_view(tmp_path, "Một", state(), now=NOW)
    save_view(tmp_path, "Hai", state(), now=NOW)
    assert delete_view(tmp_path, first.id) is True
    assert [view.name for view in list_views(tmp_path)] == ["Hai"]
    assert delete_view(tmp_path, first.id) is False


def test_what_cannot_be_saved_is_refused_in_words(tmp_path: Path) -> None:
    with pytest.raises(ViewError, match="đặt tên"):
        save_view(tmp_path, "   ", state())
    with pytest.raises(ViewError, match="tối đa"):
        save_view(tmp_path, "x" * 500, state())
    with pytest.raises(ViewError, match="đã bị xoá"):
        save_view(tmp_path, "Một", state(), view_id="khongco")


def test_a_state_with_unknown_keys_or_aggregation_is_refused() -> None:
    with pytest.raises(ValidationError):
        ViewState.model_validate({"x": "a", "sql": "DROP TABLE t"})
    with pytest.raises(ValidationError):
        ViewState.model_validate({"x": "a", "aggregation": "drop"})
    with pytest.raises(ValidationError):
        ViewState.model_validate({"x": "a", "chart": "radar"})


def test_one_broken_entry_does_not_lose_the_others(tmp_path: Path) -> None:
    kept = save_view(tmp_path, "Còn", state(), now=NOW)
    path = tmp_path / VIEWS_FILE
    path.write_text(path.read_text(encoding="utf-8")[:-2] + ', {"id": 1}]', encoding="utf-8")
    assert [view.id for view in list_views(tmp_path)] == [kept.id]
    path.write_text("không phải JSON", encoding="utf-8")
    assert list_views(tmp_path) == []


def test_writing_leaves_no_temporary_file(tmp_path: Path) -> None:
    save_view(tmp_path, "Một", state(), now=NOW)
    assert sorted(item.name for item in tmp_path.iterdir()) == [VIEWS_FILE]
