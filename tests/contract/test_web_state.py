"""HTML and JSON channels must share the same state decisions."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from analysis_system.web.render import _dataset_state, _state_of
from analysis_system.web.render import split_rounds as html_split_rounds
from analysis_system.web.view import dataset_state, round_state
from analysis_system.web.view import split_rounds as json_split_rounds


def fake_space(
    *,
    running: bool = False,
    gates: list[object] | None = None,
    stopped: str = "",
    clean: bool = False,
    answers: dict[str, object] | None = None,
) -> Mock:
    space = Mock()
    space.running.side_effect = lambda _run_id: running
    space.gates.side_effect = lambda _run_id: gates or []
    space.why_stopped.side_effect = lambda _run_id: stopped
    space.clean_table.side_effect = lambda _run_id: object() if clean else None
    space.answer.side_effect = lambda run_id: (answers or {}).get(run_id)
    return space


@pytest.mark.parametrize(
    ("running", "gates", "stopped", "clean", "key"),
    [
        (True, None, "", False, "running"),
        (False, [object()], "", False, "waiting"),
        (False, None, "Bị dừng", False, "stopped"),
        (False, None, "", True, "ready"),
        (False, None, "", False, "unclean"),
    ],
)
def test_dataset_status_is_identical_in_html_and_json(
    running: bool,
    gates: list[object] | None,
    stopped: str,
    clean: bool,
    key: str,
) -> None:
    space = fake_space(running=running, gates=gates, stopped=stopped, clean=clean)
    json_status = dataset_state(space, "dataset")
    assert json_status["key"] == key
    assert json_status["label"] == _dataset_state(space, "dataset")


def test_round_status_is_identical_in_html_and_json() -> None:
    answer = Mock(claims=["one", "two"])
    space = fake_space(answers={"dataset__q1": answer})

    assert round_state(space, "dataset__q1") == {"key": "answered", "label": "2 kết luận."}
    assert _state_of(space, "dataset__q1") == "2 kết luận."


def test_round_grouping_is_identical_in_html_and_json() -> None:
    answers = {"dataset__q2": Mock(claims=["one"])}
    space = Mock()
    space.gates.side_effect = lambda run_id: [object()] if run_id == "dataset__q3" else []
    space.answer.side_effect = lambda run_id: answers.get(run_id)
    space.running.side_effect = lambda run_id: run_id == "dataset__q4"

    rounds = [
        ("dataset__q10", "ten"),
        ("dataset__q2", "two"),
        ("dataset__q4", "four"),
        ("dataset__q3", "three"),
        ("dataset__q5", "five"),
    ]
    html = html_split_rounds(space, rounds)
    json = json_split_rounds(space, rounds)
    assert html[0] == [("dataset__q2", "two"), ("dataset__q3", "three")]
    assert html[1] == [("dataset__q4", "four")]
    assert html[2] == [("dataset__q5", "five"), ("dataset__q10", "ten")]
    assert json == {
        "done": [{"run_id": run_id, "question": question} for run_id, question in html[0]],
        "running": [{"run_id": run_id, "question": question} for run_id, question in html[1]],
        "broken": [{"run_id": run_id, "question": question} for run_id, question in html[2]],
    }
