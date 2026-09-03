"""Does this answer the question that was asked?

A claim can be true, cite a real metric, and still be noise. Asked which factors
carry exam results, a real run came back with the average attendance and the
share of missing values - both correct, both traceable, neither an answer. Put
enough of those in a report and the reader has to do the sorting the system was
supposed to do.

So each claim is scored against the question and the ones that are not about it
are set aside. Set aside and *reported*, with the score, because a claim dropped
in silence is indistinguishable from a claim never made.

Two ways of scoring, and the difference between them is words versus meaning:

* **Lexical** compares the words. It needs nothing beyond what is already
  installed and gives the same answer every time, but "doanh thu" and "thu nhap"
  are unrelated to it.
* **Semantic** compares meaning through a language model. It handles synonyms and
  paraphrase, and costs a model on disk.

What neither of them can do is worth stating plainly: this measures whether a
claim is *about* the question, not whether it *answers* it, and not whether the
two are talking about the same thing at the same scale. "The school average is
82.62" is entirely on-topic for a question about one pupil, and entirely the
wrong figure.

Accents matter more than they look like they should. Measured on the same
sixteen cases, scored as people actually write them:

    written with diacritics on both sides   13/16, nothing relevant lost
    diacritics on one side only              8/16, **8 relevant claims lost**
    diacritics on neither side               7/16, a filter that barely filters

So a mismatch is refused rather than scored, and a question typed without accents
gets a weaker check rather than a wrong one. The failure that mattered was the
middle row: it is silent, and it throws away answers.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol

if TYPE_CHECKING:  # pragma: no cover - the import costs seconds at runtime
    from sentence_transformers import SentenceTransformer

# The line a claim has to clear to stay in the answer.
DEFAULT_THRESHOLD: Final[float] = 0.25
# Words that appear in every business question and carry no subject at all.
# Left in, they pull unrelated claims up towards the question.
STOPWORDS: Final[frozenset[str]] = frozenset(
    # fmt: off
    [
        "la",
        "cua",
        "va",
        "co",
        "the",
        "cho",
        "voi",
        "tu",
        "den",
        "nhu",
        "nao",
        "gi",
        "khong",
        "duoc",
        "mot",
        "cac",
        "cai",
        "nhung",
        "hay",
        "o",
        "ra",
        "ve",
        "theo",
        "trong",
        "tren",
        "duoi",
        "ban",
        "toi",
        "chung",
        "ta",
        "minh",
        "nay",
        "do",
        "kia",
        # These turn up in every analytical question ever typed at this system,
        # which makes them worth nothing for telling one question from another.
        "phan",
        "tich",
        "du",
        "lieu",
        "ket",
        "qua",
        "so",
        "bao",
        "cao",
        "muc",
        "gia",
        "tri",
    ]
    # fmt: on
)


def fold(text: str) -> str:
    """Lowercase, strip diacritics, keep only words.

    Diacritics are folded because the two sides rarely agree about them: a
    person types "thoi quen hoc tap" and the model writes "thói quen học tập",
    and to a word counter those share nothing at all. Folding loses a little
    precision - Vietnamese diacritics do distinguish words - and gains far more
    than it loses on input that mixes both.
    """
    plain = unicodedata.normalize("NFD", text.lower())
    plain = "".join(char for char in plain if unicodedata.category(char) != "Mn")
    return " ".join(re.findall(r"[a-z0-9_]+", plain.replace("đ", "d")))


def accented(text: str) -> bool:
    """Whether this text is written with Vietnamese diacritics."""
    return any(unicodedata.category(char) == "Mn" for char in unicodedata.normalize("NFD", text))


def comparable(question: str, claim: str) -> bool:
    """Whether these two can be scored against each other at all.

    They cannot when one is written with diacritics and the other is not, and the
    cost of ignoring that is not small. Measured on the sixteen cases: scored as
    written, thirteen came out right and nothing relevant was lost. Strip the
    accents from one side only and **eight of the sixteen relevant claims are
    thrown away** - the model has no idea that "diem thi" and "điểm thi" are the
    same words, so a claim that answers the question perfectly lands nowhere near
    it.

    That failure is silent and it runs in the worst direction, so a mismatch is
    treated as *unable to judge* rather than as a low score. The claim stays and
    the answer says the check could not be made.
    """
    return accented(question) == accented(claim)


def content_words(text: str) -> list[str]:
    """The words that carry the subject, with the furniture removed."""
    return [word for word in fold(text).split() if word not in STOPWORDS and len(word) > 1]


class Scorer(Protocol):
    """Something that can say how close a claim is to a question."""

    name: str

    def score(self, question: str, claims: Sequence[str]) -> list[float]:
        """One number per claim, higher meaning closer to the question."""
        ...


@dataclass
class LexicalScorer:
    """Compares the words a claim and a question have in common.

    Deterministic, instant, and needs nothing that is not already installed.
    Blind to synonyms: a claim about "thu nhap" scores zero against a question
    about "doanh thu", however plainly it answers it.
    """

    name: str = "lexical"

    def score(self, question: str, claims: Sequence[str]) -> list[float]:
        """Cosine similarity over word and word-pair counts.

        Fitted on the question and the claims together, which is all the text
        there is. Word pairs as well as single words, so "diem thi" counts for
        more than "diem" and "thi" appearing separately.
        """
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        if not claims:
            return []
        documents = [" ".join(content_words(text)) for text in (question, *claims)]
        if not any(documents):
            return [0.0] * len(claims)
        try:
            matrix = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True).fit_transform(documents)
        except ValueError:
            # Nothing left after the stopwords came out.
            return [0.0] * len(claims)
        return [float(value) for value in cosine_similarity(matrix[0:1], matrix[1:])[0]]


@dataclass
class SemanticScorer:
    """Compares what a claim and a question mean, through a language model.

    Handles synonyms and paraphrase, which is most of what the lexical scorer
    misses. Costs a model on disk and a few seconds to load it the first time.
    """

    model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    name: str = "semantic"

    def score(self, question: str, claims: Sequence[str]) -> list[float]:
        """Cosine similarity between sentence embeddings."""
        from sentence_transformers import util

        if not claims:
            return []
        model = _model(self.model_name)
        vectors = model.encode([question, *claims], convert_to_tensor=True, show_progress_bar=False)
        similarity = util.cos_sim(vectors[0:1], vectors[1:])[0]
        return [float(value) for value in similarity]


_LOADED: dict[str, SentenceTransformer] = {}


def _model(name: str) -> SentenceTransformer:
    """The embedding model, loaded once and kept.

    Loading it per call would spend seconds on every claim, and the model is the
    same one every time.
    """
    if name not in _LOADED:
        from sentence_transformers import SentenceTransformer

        _LOADED[name] = SentenceTransformer(name)
    return _LOADED[name]


@dataclass(frozen=True)
class Judged:
    """One claim, and how close it was judged to be to the question."""

    claim: str
    score: float
    kept: bool
    # False where the two could not be compared at all. A claim that was never
    # judged is kept, and it is not the same thing as a claim that passed.
    checked: bool = True


def judge(
    question: str,
    claims: Sequence[str],
    scorer: Scorer,
    threshold: float = DEFAULT_THRESHOLD,
) -> list[Judged]:
    """Score every claim against the question and mark which ones stay.

    Args:
        question: what was asked.
        claims: what the Manager wants to say.
        scorer: how closeness is measured.
        threshold: the line a claim has to clear.

    Returns:
        Every claim with its score, kept or not - never a filtered list. What was
        set aside and why is part of the answer, not swept out of it. A claim that
        could not be compared at all comes back kept and marked unchecked.
    """
    scores = scorer.score(question, claims)
    return [
        Judged(claim=claim, score=round(score, 4), kept=score >= threshold)
        if comparable(question, claim)
        # Not judged, so not dropped. Scoring accented text against unaccented
        # text discarded half the real answers when it was measured, and it did
        # so without any sign that anything had gone wrong.
        else Judged(claim=claim, score=0.0, kept=True, checked=False)
        for claim, score in zip(claims, scores, strict=True)
    ]
