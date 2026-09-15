"""Does the relevance check keep answers and drop the rest?

Every rule is tested from both sides, because a filter that keeps everything
passes any test that only checks what survived. What matters more here than
anywhere else is the direction of the mistake: a claim wrongly kept is noise the
reader can skip, while a claim wrongly dropped is a finding that leaves no trace
of having existed.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from analysis_system.core.vietnamese_text import fold
from analysis_system.domains.ai_planner.relevance import (
    DEFAULT_THRESHOLD,
    LexicalScorer,
    SemanticScorer,
    comparable,
    content_words,
    judge,
)


class FixedScorer:
    """A scorer that returns what a test told it to, so thresholds can be tested alone."""

    name = "fixed"

    def __init__(self, scores: list[float]) -> None:
        self.scores = scores
        self.seen: list[tuple[str, tuple[str, ...]]] = []

    def score(self, question: str, claims: Sequence[str]) -> list[float]:
        self.seen.append((question, tuple(claims)))
        return self.scores


# --- folding text ---------------------------------------------------------------


def test_fold_strips_diacritics_so_both_spellings_meet() -> None:
    """A person types without accents and the model writes with them."""
    assert fold("Điểm Thi Cuối Kỳ") == "diem thi cuoi ky"


def test_fold_keeps_letters_apart_from_punctuation() -> None:
    assert fold("tỷ lệ hoàn: 9.4%!") == "ty le hoan 9 4"


def test_content_words_removes_the_furniture() -> None:
    """Words in every question tell one question from another not at all."""
    words = content_words("phân tích dữ liệu của kênh bưu điện")
    assert "kenh" in words
    assert "buu" in words
    assert "phan" not in words
    assert "cua" not in words


def test_content_words_keeps_something_when_all_of_it_is_furniture() -> None:
    """A question of nothing but stopwords yields nothing, and must not explode."""
    assert content_words("của và có thể") == []


# --- the threshold, tested with the scoring held fixed ---------------------------


def test_claim_above_the_line_is_kept() -> None:
    judged = judge("cau hoi", ["luan diem"], FixedScorer([0.9]), 0.25)
    assert judged[0].kept is True
    assert judged[0].score == 0.9


def test_claim_below_the_line_is_dropped() -> None:
    judged = judge("cau hoi", ["luan diem"], FixedScorer([0.1]), 0.25)
    assert judged[0].kept is False


def test_claim_exactly_on_the_line_is_kept() -> None:
    """The threshold is a floor to clear, not a bar to beat."""
    assert judge("cau hoi", ["luan diem"], FixedScorer([0.25]), 0.25)[0].kept is True


def test_every_claim_comes_back_kept_or_not() -> None:
    """Never a filtered list: what was set aside is part of the answer.

    A dropped claim that is simply missing from the result is indistinguishable
    from a claim that was never made, and the caller cannot report what it
    cannot see.
    """
    judged = judge("q", ["a", "b", "c"], FixedScorer([0.9, 0.01, 0.5]), 0.25)
    assert [item.claim for item in judged] == ["a", "b", "c"]
    assert [item.kept for item in judged] == [True, False, True]


def test_no_claims_asks_the_scorer_nothing() -> None:
    scorer = FixedScorer([])
    assert judge("cau hoi", [], scorer) == []


def test_threshold_defaults_to_the_measured_line() -> None:
    """0.25 was measured, not picked - the highest line that drops nothing real."""
    assert judge("q", ["c"], FixedScorer([0.26]))[0].kept is True
    assert judge("q", ["c"], FixedScorer([0.24]))[0].kept is False
    assert DEFAULT_THRESHOLD == 0.25


# --- accents, which turned out to matter far more than they look like they should ---


def test_accented_and_unaccented_are_not_compared() -> None:
    """The measurement that forced this: a mismatch loses half the real answers.

    Scored as written, thirteen of sixteen cases came out right and nothing
    relevant was lost. Strip the accents from one side only and eight of the
    sixteen relevant claims are discarded - the model cannot tell that "diem thi"
    and "điểm thi" are the same words, so a claim that answers the question
    exactly lands nowhere near it.
    """
    assert comparable("điểm thi phụ thuộc gì", "Giờ học đi kèm điểm thi.") is True
    assert comparable("diem thi phu thuoc gi", "Gio hoc di kem diem thi.") is True
    assert comparable("điểm thi phụ thuộc gì", "Gio hoc di kem diem thi.") is False


def test_a_claim_that_cannot_be_compared_is_kept_and_marked() -> None:
    """Unable to judge is not the same as judged and failed.

    A mismatch fails silently and in the destructive direction, so it must never
    turn into a low score. The claim stays, and it stays flagged - a caller that
    could not see the difference would report an unjudged claim as an approved one.
    """
    judged = judge("điểm thi phụ thuộc gì", ["Gio hoc di kem diem thi."], FixedScorer([0.01]))[0]
    assert judged.kept is True
    assert judged.checked is False


def test_a_claim_that_was_compared_says_so() -> None:
    judged = judge("điểm thi phụ thuộc gì", ["Giờ học đi kèm điểm thi."], FixedScorer([0.9]))[0]
    assert judged.kept is True
    assert judged.checked is True


def test_text_without_accents_on_both_sides_is_still_judged() -> None:
    """A weaker check, not a suspended one.

    Someone typing Vietnamese without accents gets a filter that keeps too much -
    seven of sixteen when it was measured, mostly noise retained. That is the
    safe direction, and refusing to check at all would be worse.
    """
    assert (
        judge("diem thi phu thuoc gi", ["Bang co 60 dong."], FixedScorer([0.01]))[0].kept is False
    )


# --- comparing words ------------------------------------------------------------


def test_lexical_scores_a_shared_subject_above_an_unrelated_one() -> None:
    scores = LexicalScorer().score(
        "Tỷ lệ hoàn của kênh bưu điện ra sao?",
        ["Kênh bưu điện có tỷ lệ hoàn 9.4%.", "Bảng có 6 dòng và 4 cột."],
    )
    assert scores[0] > scores[1]


def test_lexical_is_blind_to_synonyms() -> None:
    """The limit that decided the choice, written down so it stays known.

    "thu nhap" answers a question about "doanh thu" and shares no word with it.
    """
    score = LexicalScorer().score(
        "Doanh thu đến từ đâu nhiều nhất?",
        ["Kênh trực tuyến đóng góp phần lớn tổng thu nhập kỳ này."],
    )[0]
    assert score < DEFAULT_THRESHOLD


def test_lexical_survives_a_question_of_pure_stopwords() -> None:
    """Nothing left to compare must score zero, not raise."""
    assert LexicalScorer().score("của và có thể", ["của và"]) == [0.0]


def test_lexical_handles_no_claims() -> None:
    assert LexicalScorer().score("cau hoi", []) == []


# --- comparing meaning ----------------------------------------------------------


# The embedding model is a download, not a dependency that pip put in place.
# Where it is absent these skip rather than fail, the same way the transcription
# tests do - and the Manager, for the same reason, filters nothing and says so.
EMBEDDINGS = Path.home() / ".cache" / "huggingface"
HAS_MODEL = EMBEDDINGS.is_dir()
NEEDS_MODEL = pytest.mark.skipif(not HAS_MODEL, reason="chua tai model do do lien quan")


@NEEDS_MODEL
def test_semantic_reads_synonyms_that_words_cannot() -> None:
    """The case the lexical scorer fails, and the reason this one is the default."""
    score = SemanticScorer().score(
        "Doanh thu đến từ đâu nhiều nhất?",
        ["Kênh trực tuyến đóng góp phần lớn tổng thu nhập kỳ này."],
    )[0]
    assert score >= DEFAULT_THRESHOLD


@NEEDS_MODEL
def test_semantic_separates_an_answer_from_a_true_irrelevance() -> None:
    """The run that prompted all of this.

    Asked which factors carry exam results, the Manager reported the average
    attendance and the share of missing values. Both true. Neither an answer.
    """
    scores = SemanticScorer().score(
        "Yếu tố nào ảnh hưởng đến điểm thi cuối kỳ?",
        [
            "Giờ học có tương quan với điểm thi cuối kỳ, hệ số 0.62.",
            "Bảng có 6 dòng và 4 cột.",
        ],
    )
    assert scores[0] >= DEFAULT_THRESHOLD
    assert scores[1] < DEFAULT_THRESHOLD


@NEEDS_MODEL
def test_semantic_handles_no_claims() -> None:
    assert SemanticScorer().score("cau hoi", []) == []
