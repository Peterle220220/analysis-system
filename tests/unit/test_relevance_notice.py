"""Lop loc "dung chu de" khong chay duoc thi phai NOI RA.

Cau hoi go khong dau -> `comparable()` tra False -> moi ket luan duoc giu
nguyen, chua qua kiem. Do la lua chon dung: cham cheo dau da nem di 8 tren 16
cau tra loi dung khi do lan dau.

Van de la no IM LANG. Cau tra loi hien ra y het mot cau da qua du lop kiem.

Da do phuong an ha xuong LexicalScorer (thuoc do nay bo dau truoc khi so):
36 cap tu ba luot chay that, 12 cap dung chu de.

    semantic (du dau)     0.25   giu 11/12 dung, bo oan 1
    lexical (hoi mat dau) 0.05   giu  8/12 dung, bo oan 4
    lexical (hoi mat dau) 0.10   giu  6/12 dung, bo oan 6

Nem oan mot phan ba ket luan dung la mot cuoc doi chac toi, nen khong ha xuong
lexical. Con lai dung mot viec dang lam: noi ra.
"""

from __future__ import annotations

from analysis_system.services.relevance_notice import unchecked_note
from analysis_system.services.risk_notes import is_risk, risks


def test_it_says_how_many_claims_went_unchecked() -> None:
    assert "3" in unchecked_note("cau hoi khong dau", 3)


def test_an_unaccented_question_is_told_what_to_do_about_it() -> None:
    """Noi ra ma khong chi cach chua thi nguoi doc chi biet lo lang."""
    note = unchecked_note("ty le nam nu the nao", 4)
    assert "có dấu" in note


def test_an_accented_question_is_not_told_to_add_accents_it_already_has() -> None:
    note = unchecked_note("tỷ lệ nam nữ thế nào", 4)
    assert "Gõ lại câu hỏi có dấu" not in note


def test_the_note_reaches_the_banner_at_the_top_of_the_page() -> None:
    """Nam duoi `unanswered` thoi thi nguoi doc gap no SAU khi da tin moi con so."""
    note = unchecked_note("ty le nam nu the nao", 4)
    assert is_risk(note)
    assert risks([note]) == (note,)


def test_one_line_for_the_whole_answer_not_one_per_claim() -> None:
    """Truoc day moi luan diem di mot dong. Nam dong giong nhau thi nguoi ta thoi doc ca cum."""
    assert unchecked_note("ty le nam nu", 5).count("\n") == 0
