"""Dang chay hay da dung - noi ra, dung de nguoi dung doan.

Chu he thong tich cac muc lam sach roi ngoi nhin mot trang khong noi gi:
"khong biet he thong co dang chay hay khong hay dung lai roi". Luc do no da chet
duoc nam phut - buoc lam sach hong vi mot luat khong the chay, va trang van hien
bang du lieu voi o dat cau hoi nhu the moi thu binh thuong.

Mot trang im lang noi hai dieu cung luc, "dang chay" va "da xong", va nguoi doc
khong co cach nao tach chung ra.
"""

from __future__ import annotations

from analysis_system.agents.a3_cleaner import specs_and_skipped
from analysis_system.models.base import ErrorDetail
from analysis_system.services.rule_names import in_plain_words
from analysis_system.services.rulebook import RuleSpec, cannot_run

# Nguyen van luat da lam chet luot chay cua chu he thong.
THIEU_COT = RuleSpec("replace_sentinel_with_null", (), {"sentinels": ["unknown"]})
THIEU_GIA_TRI = RuleSpec("replace_sentinel_with_null", ("job",), {})
CHAY_DUOC = RuleSpec("replace_sentinel_with_null", ("job",), {"sentinels": ["unknown"]})


# --- biet TRUOC luat nao khong chay duoc --------------------------------------


def test_a_rule_with_no_columns_is_known_to_be_unrunnable() -> None:
    assert cannot_run(THIEU_COT)
    assert "cột" in cannot_run(THIEU_COT)


def test_a_rule_with_no_sentinel_values_is_known_to_be_unrunnable() -> None:
    assert cannot_run(THIEU_GIA_TRI)


def test_a_complete_rule_is_left_alone() -> None:
    assert cannot_run(CHAY_DUOC) == ""


def test_the_ordinary_rules_are_never_blocked() -> None:
    for rule_id in ("trim_whitespace", "cast_numeric_safe", "drop_exact_duplicates"):
        assert cannot_run(RuleSpec(rule_id)) == ""


# --- bo ra thi phai NOI RA ----------------------------------------------------


def test_an_unrunnable_rule_is_skipped_instead_of_killing_the_run() -> None:
    """Truoc day ca buoc lam sach chet, va nguoi dung mat het moi luat khac."""
    specs, skipped = specs_and_skipped(
        [
            {"rule_id": "trim_whitespace", "reason": "x"},
            {"rule_id": "replace_sentinel_with_null", "reason": "y"},
        ]
    )
    assert [spec.rule_id for spec in specs] == ["trim_whitespace"]
    assert len(skipped) == 1


def test_the_skipped_rule_is_named_in_words_and_says_why() -> None:
    """Bo trong im lang la dung thu du an nay tranh: nguoi duyet tin rang thu
    ho tich da chay."""
    _, skipped = specs_and_skipped(
        [
            {
                "rule_id": "replace_sentinel_with_null",
                "reason": "y",
                "params": {"sentinels": ["unknown"]},
            }
        ]
    )
    assert "Coi các ô đánh dấu là để trống" in skipped[0]
    assert "replace_sentinel_with_null" in skipped[0]
    assert "cột" in skipped[0]


def test_nothing_is_skipped_when_everything_can_run() -> None:
    specs, skipped = specs_and_skipped([{"rule_id": "trim_whitespace", "reason": "x"}])
    assert len(specs) == 1
    assert skipped == []


# --- cau bao loi phai doc duoc ------------------------------------------------


def test_an_error_object_gives_up_its_message_not_its_repr() -> None:
    """`str(ErrorDetail)` cho ra ban in may - code='...' message="..." - va ca
    cum do tung di thang len man hinh nguoi dung."""
    from analysis_system.api import _message_of

    detail = ErrorDetail(code="RULE_REJECTED", message="Rule 'x' bat buoc chi ro cot.")
    assert _message_of(detail) == "Rule 'x' bat buoc chi ro cot."
    assert "code=" not in _message_of(detail)


def test_a_rule_id_in_an_error_becomes_a_name_a_person_can_read() -> None:
    said = in_plain_words("Rule 'replace_sentinel_with_null' bat buoc chi ro cot.")
    assert "Coi các ô đánh dấu là để trống" in said
    # Ma luat van con, cho nguoi van hanh doi chieu voi nhat ky.
    assert "[replace_sentinel_with_null]" in said


def test_a_sentence_naming_no_rule_is_left_alone() -> None:
    assert in_plain_words("Khong doc duoc tep.") == "Khong doc duoc tep."
