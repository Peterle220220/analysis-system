"""Trạng thái bộ dữ liệu và lượt hỏi mà lớp JSON trả cho giao diện Next.

Trước đây file này đối chiếu kênh HTML với kênh JSON. Giao diện HTML đã bỏ
(plans/refactor-ddd.md, quyết định 3), nên kết quả mong đợi được ghi thẳng ra đây.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from analysis_system.web.view import dataset_state, round_state, split_rounds


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
def test_dataset_status_has_a_key_and_words_for_it(
    running: bool,
    gates: list[object] | None,
    stopped: str,
    clean: bool,
    key: str,
) -> None:
    space = fake_space(running=running, gates=gates, stopped=stopped, clean=clean)
    status = dataset_state(space, "dataset")
    assert status["key"] == key
    assert status["label"].strip()


def test_an_answered_round_counts_its_claims() -> None:
    answer = Mock(claims=["one", "two"])
    space = fake_space(answers={"dataset__q1": answer})
    assert round_state(space, "dataset__q1") == {"key": "answered", "label": "2 kết luận."}


def test_rounds_are_grouped_and_numbered_in_order() -> None:
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

    def listed(*pairs: tuple[str, str]) -> list[dict[str, str]]:
        return [{"run_id": run_id, "question": question} for run_id, question in pairs]

    assert split_rounds(space, rounds) == {
        "done": listed(("dataset__q2", "two"), ("dataset__q3", "three")),
        "running": listed(("dataset__q4", "four")),
        "broken": listed(("dataset__q5", "five"), ("dataset__q10", "ten")),
    }
