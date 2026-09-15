"""Cau tra loi bi CAT khac han cau tra loi SAI DINH DANG.

Mot luot chay that: bang 96 cot, model viet SQL liet ke tung cot mot voi
TRY_CAST, cau lenh dai hon han muc chu dau ra, va phan hoi dut giua chung o
dong `" Realized Sales Gross Profit Growth Rate",`.

He thong bao "khong tim thay JSON" - dung ve hien tuong, SAI ve nguyen nhan, va
nguoi doc di tim nham cho. Ba model, ba lan, cung mot kieu hong.
"""

from __future__ import annotations

import pytest

from analysis_system.domains.ai_planner.llm import CUT_SHORT, truncated

# --- nhan ra bi cat -----------------------------------------------------------


@pytest.mark.parametrize("field", ["finish_reason", "native_finish_reason", "stop_reason"])
def test_openrouter_says_it_ran_out_of_room(field: str) -> None:
    assert truncated({"choices": [{field: "length"}]})


def test_max_tokens_is_the_same_thing_said_differently() -> None:
    assert truncated({"choices": [{"finish_reason": "max_tokens"}]})


def test_gemini_says_it_in_its_own_shape() -> None:
    assert truncated({"candidates": [{"finishReason": "MAX_TOKENS"}]})


def test_case_does_not_hide_it() -> None:
    assert truncated({"choices": [{"finish_reason": "LENGTH"}]})


# --- KHONG duoc bao nham ------------------------------------------------------


def test_a_normal_finish_is_not_a_truncation() -> None:
    assert not truncated({"choices": [{"finish_reason": "stop"}]})


def test_a_refusal_is_not_a_truncation() -> None:
    """Model tu choi tra loi la mot chuyen khac, va sua bang mot cach khac."""
    assert not truncated({"choices": [{"finish_reason": "content_filter"}]})


def test_an_empty_payload_is_not_a_truncation() -> None:
    assert not truncated({})
    assert not truncated({"choices": []})


def test_a_payload_of_the_wrong_shape_does_not_crash() -> None:
    # Phan hoi den tu ben ngoai; mot hinh dang la khong duoc lam vo phep kiem.
    assert not truncated({"choices": ["mot chuoi"]})
    assert not truncated({"candidates": [None]})


# --- cau noi cho nguoi doc ----------------------------------------------------


def test_the_message_names_the_real_cause() -> None:
    assert "CAT" in CUT_SHORT
    assert "han muc" in CUT_SHORT


def test_the_message_says_what_to_do_instead() -> None:
    """Noi hong ma khong noi lam gi tiep thi nguoi doc van tac."""
    assert "SELECT *" in CUT_SHORT
