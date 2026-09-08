"""Han gio cho mot lan goi model, co gian theo co prompt.

Mot bang 96 cot lam lo cho nay. Prompt 54.000 ky tu, ba model trong chan du
phong deu qua han o 120 giay, va nguoi hoi doi sau phut roi khong nhan duoc gi:

    Goi OpenRouter qua han sau 120s: The read operation timed out

Mot con so co dinh phai chon giua hai cai deu te. 120 giay thi bang lon chet;
600 giay thi mot cau hoi nho gap truc trac mang cung bat nguoi ta ngoi cho muoi
phut. Nen no ti le voi thu that su lam cuoc goi lau: so chu phai doc va sinh ra.
"""

from __future__ import annotations

from analysis_system.services.llm import (
    HTTP_TIMEOUT_S,
    MAX_TIMEOUT_S,
    timeout_for,
)


def test_a_small_prompt_still_fails_fast() -> None:
    """Cau hoi nho gap truc trac mang thi khong duoc bat nguoi ta ngoi cho lau."""
    assert timeout_for("cau hoi ngan") <= HTTP_TIMEOUT_S + 5


def test_an_empty_prompt_gets_the_floor() -> None:
    assert timeout_for("") == HTTP_TIMEOUT_S


def test_the_prompt_that_broke_the_run_gets_room_to_breathe() -> None:
    """54.000 ky tu la co that: bang bankruptcy_prediction, 96 cot."""
    assert timeout_for("x" * 54_432) > 200


def test_it_grows_with_the_prompt() -> None:
    assert timeout_for("x" * 100_000) > timeout_for("x" * 10_000) > timeout_for("x" * 1_000)


def test_it_never_grows_without_end() -> None:
    """Qua tran thi van de khong con la "prompt lon", va cho them thoi gian chi
    lam cho lan hong den cham hon."""
    assert timeout_for("x" * 10_000_000) == MAX_TIMEOUT_S


def test_it_never_goes_below_the_floor_given() -> None:
    assert timeout_for("x" * 100, floor=300) >= 300


def test_it_takes_a_string_of_any_shape() -> None:
    # Prompt den tu nhieu cho; mot cai None hay mot so khong duoc lam no vo.
    assert timeout_for("") == HTTP_TIMEOUT_S
    assert timeout_for("có dấu tiếng Việt") == HTTP_TIMEOUT_S
