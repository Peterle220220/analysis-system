"""Đọc hết một đoạn văn và nói xem từ nào đáng để tâm — kèm bằng chứng.

Turning prose into a table starts here, with a question code can answer
honestly: **which words is this text actually about?**

Frequency alone does not answer it, and the trap runs both ways. A word filling
three hundred of five hundred slots is the wallpaper of the document: it appears
everywhere, so it distinguishes no part of the text from any other, and a table
built on it would have one row. A word appearing twice may be the reason the
document was written, or may be a slip of the keyboard. **Neither end is
"important" on its own**, and code claiming to rank importance from counts alone
is guessing with a confident face.

So nothing here ranks importance. It reports what can be counted, splits the
range into bands with a plain statement of what each band *means*, and leaves
the judgement to the person who knows what they are looking for:

    nen    chiem phan lon van ban - la CHU DE, khong phan biet duoc gi ben trong
    vua    xuat hien deu - thuong la thuat ngu chinh cua linh vuc
    hiem   xuat hien it - dang HOI VI SAO it, chu khong dang tin ngay

Two things are measured beyond the count, because both carry a reader towards a
table rather than towards another list of words:

* **Cụm từ.** "machine learning" is one idea appearing twice, not two words
  appearing twice. Counting the halves apart loses exactly the term worth
  noticing.
* **Số liệu ở gần.** Every figure standing near a mention is captured with it.
  That is the bridge from prose to a table: when the reader asks *"từ này đi
  với những số nào"*, the candidates have already been gathered rather than
  hunted for by hand. **Ở gần không phải là thuộc về** - whether a figure
  describes the term or merely sits close to it is a reading of the paragraph,
  and that reading belongs to the person, not to a word counter.

Every term keeps the locators of the places it was found, so a claim about it
traces back to a page and a line exactly like every other claim in this system.

Không dùng model nào. Đếm từ, ghép cụm và nhặt số là việc của code.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Final

# A term filling this much of the text is what the text is *about*, and so says
# nothing about which part of it to read. Not a judgement of worth - a statement
# about discrimination.
WALLPAPER_SHARE: Final[float] = 0.05
# At or below this many mentions a term is worth a question rather than a
# conclusion. Two occurrences can be the point of the document or a typo.
RARE_AT_MOST: Final[int] = 3
# Shorter than this is almost always grammar rather than subject.
MIN_TERM_CHARS: Final[int] = 2
# How far either side of a mention a figure is still worth showing next to it.
#
# Measured rather than guessed: eight words returned nothing at all for a term
# whose figure sits in the following sentence - "...thu nghiem machine learning
# de du bao nhu cau ton kho theo tung kenh. Do chinh xac du bao dat 87%..." is
# seventeen words apart, and that is ordinary business writing rather than an
# awkward case.
#
# Roughly two sentences. Wider than this and every figure on the page attaches
# to every term, which is the same as attaching to none.
NUMBER_WINDOW: Final[int] = 25
# A pair of words seen once is a pair of words, not a term.
MIN_PHRASE_COUNT: Final[int] = 2

# Words carrying grammar rather than subject: Vietnamese, then the English that
# turns up in any technical document written here.
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
        "se",
        "da",
        "dang",
        "bi",
        "boi",
        "tai",
        "khi",
        "neu",
        "thi",
        "ma",
        "hon",
        "rat",
        "cung",
        "van",
        "chi",
        "moi",
        "nen",
        "phai",
        "can",
        "sau",
        "truoc",
        "giua",
        "hoac",
        "tuy",
        "vi",
        "nhat",
        "vao",
        "len",
        "xuong",
        "qua",
        "lai",
        "day",
        "no",
        "ho",
        "ai",
        "dau",
        "sao",
        "bao",
        "and",
        "or",
        "of",
        "to",
        "in",
        "on",
        "for",
        "with",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "an",
        "this",
        "that",
        "these",
        "it",
        "as",
        "at",
        "by",
        "from",
        "has",
        "have",
        "had",
        "not",
        "but",
        "we",
        "the",
    ]
    # fmt: on
)

TOKEN: Final[re.Pattern[str]] = re.compile(r"[a-z][a-z0-9_]*")
NUMBER: Final[re.Pattern[str]] = re.compile(r"-?\d[\d.,]*%?")

BAND_MEANING: Final[dict[str, str]] = {
    "nen": (
        "chiem phan lon van ban - day la CHU DE chung, nen no khong phan biet duoc "
        "doan nao voi doan nao. Lap bang theo tu nay thi bang chi co mot dong"
    ),
    "vua": (
        "xuat hien deu khap van ban - thuong la thuat ngu chinh cua linh vuc, va la "
        "cho de bat dau neu muon mot bang nhieu dong"
    ),
    "hiem": (
        "xuat hien it - dang HOI VI SAO it. Co the la diem nhan that su, co the chi "
        "la nhac thoang qua; tan suat mot minh khong phan biet duoc hai kha nang do"
    ),
}


def fold(text: str) -> str:
    """Lowercase, strip diacritics, keep the letters and figures.

    The same folding `relevance` uses, and for the same reason: two halves of a
    document rarely agree about accents, and "doanh thu" written both ways is
    one term rather than two.
    """
    plain = unicodedata.normalize("NFD", text.lower())
    plain = "".join(char for char in plain if unicodedata.category(char) != "Mn")
    return plain.replace(chr(273), "d")


def content_words(text: str) -> list[str]:
    """The words that carry subject, with the grammar removed."""
    return [
        word
        for word in TOKEN.findall(fold(text))
        if word not in STOPWORDS and len(word) >= MIN_TERM_CHARS
    ]


@dataclass(frozen=True)
class Mention:
    """Một lần từ xuất hiện: ở đâu, và có số nào bên cạnh CHÍNH CHỖ ĐÓ.

    Kept per mention rather than per term because a row pairing a page with
    figures from another page is not a small inaccuracy - it is the traceability
    this system rests on, pointed at the wrong place.
    """

    where: str = ""
    numbers: tuple[str, ...] = ()


@dataclass(frozen=True)
class Term:
    """One word or phrase, how often it appeared, and where."""

    term: str
    count: int
    share: float
    band: str
    # Figures found NEAR a mention, in the order met - not figures established
    # to belong to it. Proximity is measurable and belonging is not: a reader
    # knows 87% describes the forecast because of how the paragraph hangs
    # together, and no count can see that. These are the candidates a person
    # judges, and the bridge from prose to a table.
    numbers: tuple[str, ...] = ()
    where: tuple[str, ...] = ()
    # Every appearance separately, each with the figures beside that one. The
    # aggregate above is assembled from these rather than instead of them.
    mentions: tuple[Mention, ...] = ()
    is_phrase: bool = False

    @property
    def note(self) -> str:
        """What this band means, in words a reader can act on."""
        return BAND_MEANING[self.band]


@dataclass
class Reading:
    """Everything counted in one body of text."""

    total_words: int = 0
    distinct_terms: int = 0
    terms: tuple[Term, ...] = ()
    # Said out loud rather than left to be inferred, the same shape every other
    # skill uses for what it could not do.
    declined: tuple[str, ...] = field(default_factory=tuple)

    def band(self, name: str) -> tuple[Term, ...]:
        """Just the terms in one band, most frequent first."""
        return tuple(term for term in self.terms if term.band == name)


def _band(count: int, share: float) -> str:
    """Which end of the range this term sits at."""
    if share >= WALLPAPER_SHARE:
        return "nen"
    if count <= RARE_AT_MOST:
        return "hiem"
    return "vua"


def _where(position: int, line_of: Sequence[int], locators: Sequence[str]) -> str:
    """Which page or timestamp this one position sits on."""
    if position >= len(line_of):
        return ""
    line = line_of[position]
    return locators[line] if line < len(locators) else ""


def _numbers_near(
    tokens: Sequence[str],
    positions: Iterable[int],
    line_of: Sequence[int] = (),
    locators: Sequence[str] = (),
) -> tuple[str, ...]:
    """Figures sitting within NUMBER_WINDOW words of any of these positions.

    Near, not belonging to. Whether a figure describes the term or merely stands
    close to it is a reading of the paragraph, and this function counts words.

    The window stops at the mention's own page. Tokens run on across the whole
    document, so twenty-five words back from the top of page three reaches into
    page two - and a row that names page three while listing page two's figures
    sends the reader somewhere they will not find them.
    """
    found: list[str] = []
    for position in positions:
        home = _where(position, line_of, locators)
        low = max(0, position - NUMBER_WINDOW)
        high = min(len(tokens), position + NUMBER_WINDOW + 1)
        for index in range(low, high):
            token = tokens[index]
            if not NUMBER.fullmatch(token) or token in found:
                continue
            if home and _where(index, line_of, locators) != home:
                continue
            found.append(token)
    return tuple(found)


def _mentions_at(
    positions: Sequence[int],
    tokens: Sequence[str],
    line_of: Sequence[int],
    locators: Sequence[str],
) -> tuple[Mention, ...]:
    """Each appearance with the figures beside *that* appearance.

    One mention per place rather than per position: a term named three times on
    one page is one row a reader would go and look at, not three.
    """
    grouped: dict[str, list[int]] = defaultdict(list)
    for position in positions:
        grouped[_where(position, line_of, locators)].append(position)
    return tuple(
        Mention(where=place, numbers=_numbers_near(tokens, at, line_of, locators))
        for place, at in grouped.items()
    )


def read(text: str, *, locators: Sequence[str] = (), max_terms: int = 40) -> Reading:
    """Count every term in this text, and say what each end of the range means.

    Args:
        text: everything read out of the document, one line per line read.
        locators: where each line came from, one per line, so a term traces
            back. Fewer than the lines is fine - those mentions carry no
            locator rather than a wrong one.
        max_terms: how many terms to report. The tail of any document is mostly
            words used once, and a list nobody can read is a list nobody reads.

    Returns:
        Every term with its count, share, band, the figures beside it and where
        it was found - and what was left out, said plainly.
    """
    lines = text.splitlines()
    if not any(line.strip() for line in lines):
        return Reading(declined=("khong co chu nao de dem.",))

    # Counted across the whole document, but every mention remembers its line.
    # That is what keeps a term traceable back to a page.
    tokens: list[str] = []
    line_of: list[int] = []
    for index, line in enumerate(lines):
        folded = fold(line)
        for match in re.finditer(r"[a-z][a-z0-9_]*|-?\d[\d.,]*%?", folded):
            tokens.append(match.group())
            line_of.append(index)

    subject = [
        (position, word)
        for position, word in enumerate(tokens)
        if word not in STOPWORDS and len(word) >= MIN_TERM_CHARS and not NUMBER.fullmatch(word)
    ]
    if not subject:
        return Reading(declined=("van ban khong co tu nao mang noi dung.",))

    counts: Counter[str] = Counter(word for _, word in subject)
    places: dict[str, list[int]] = defaultdict(list)
    for position, word in subject:
        places[word].append(position)

    # Phrases: two subject words adjacent in the original text. "machine
    # learning" is one idea, and counting its halves apart is how the term
    # worth noticing disappears.
    phrases: Counter[str] = Counter()
    phrase_places: dict[str, list[int]] = defaultdict(list)
    for (left_at, left), (right_at, right) in zip(subject, subject[1:], strict=False):
        # A word repeated back to back is repetition, not a compound: "doanh
        # doanh" names nothing, and counting it lets the self-phrase absorb the
        # very word it was made of.
        if right_at == left_at + 1 and left != right:
            phrase = f"{left} {right}"
            phrases[phrase] += 1
            phrase_places[phrase].append(left_at)

    # Both orderings of a repeated pair get counted - "doanh thu" 150 times
    # and "thu doanh" 149 - and only one of them is a term. Keep the ordering
    # the text actually favours.
    for phrase in list(phrases):
        left, right = phrase.split(" ", 1)
        mirror = f"{right} {left}"
        if mirror in phrases and phrases[mirror] > phrases[phrase]:
            del phrases[phrase]

    kept_phrases = {phrase: count for phrase, count in phrases.items() if count >= MIN_PHRASE_COUNT}

    # A syllable whose every appearance is inside one phrase says nothing the
    # phrase does not. Vietnamese makes this the common case rather than the
    # exception: `buu` and `dien` are noise, `buu dien` is the post office, and
    # reporting all three buries the term in its own fragments.
    #
    # A word used inside a phrase *and* on its own is kept - it is then really
    # being used by itself as well.
    inside: Counter[str] = Counter()
    for phrase, count in kept_phrases.items():
        for word in phrase.split(" "):
            inside[word] += count
    absorbed = {word for word, seen in inside.items() if seen >= counts.get(word, 0)}

    total = len(subject)
    terms: list[Term] = []
    for word, count in counts.most_common():
        if word in absorbed:
            continue
        terms.append(
            Term(
                term=word,
                count=count,
                share=round(count / total, 4),
                band=_band(count, count / total),
                numbers=_numbers_near(tokens, places[word], line_of, locators),
                where=tuple(
                    dict.fromkeys(
                        _where(at, line_of, locators)
                        for at in places[word]
                        if _where(at, line_of, locators)
                    )
                ),
                mentions=_mentions_at(places[word], tokens, line_of, locators),
            )
        )
    for phrase, count in sorted(kept_phrases.items(), key=lambda item: -item[1]):
        terms.append(
            Term(
                term=phrase,
                count=count,
                share=round(count / total, 4),
                band=_band(count, count / total),
                numbers=_numbers_near(tokens, phrase_places[phrase], line_of, locators),
                where=tuple(
                    dict.fromkeys(
                        _where(at, line_of, locators)
                        for at in phrase_places[phrase]
                        if _where(at, line_of, locators)
                    )
                ),
                mentions=_mentions_at(phrase_places[phrase], tokens, line_of, locators),
                is_phrase=True,
            )
        )

    kept = _share_out(terms, max_terms)
    declined: list[str] = []
    if len(terms) > len(kept):
        declined.append(
            f"co {len(terms)} tu va cum, chi bao cao {len(kept)} - moi bang duoc mot "
            "phan rieng, va trong bang thi cum tu va tu co so di kem duoc uu tien."
        )
    return Reading(
        total_words=total,
        distinct_terms=len(counts),
        terms=tuple(kept),
        declined=tuple(declined),
    )


def _worth_showing(term: Term) -> tuple[int, int, int, str]:
    """Thu tu trong mot bang - theo cai lam nen mot thuat ngu, khong theo chu cai.

    Sorting by count alone left ties broken alphabetically, which decided which
    rare term survived the cut by its first letter. These three say what a term
    actually is:

    * **cum tu** - Vietnamese counts in phrases, so `buu dien` is a term where
      `buu` is a fragment of one
    * **co so di kem** - only a term standing next to figures can become a
      table, and a table is where this is all going
    * **so lan** - last, because inside a band the counts are close by
      construction
    """
    return (-int(term.is_phrase), -int(bool(term.numbers)), -term.count, term.term)


def _share_out(terms: list[Term], max_terms: int) -> list[Term]:
    """Chia suat cho tung bang, thay vi de mot bang lan at ca danh sach.

    The bands answer different questions - what the document is about, what its
    working vocabulary is, and what is worth asking about - so a cut that lets
    one crowd out the others throws away a whole question. Slots a band does not
    need pass to the next rather than going to waste.
    """
    by_band = {
        name: sorted((t for t in terms if t.band == name), key=_worth_showing)
        for name in ("nen", "vua", "hiem")
    }
    quota = max(1, max_terms // len(by_band))
    kept: list[Term] = []
    spare = max_terms
    # Smallest band first, so the slots it cannot use are still available to the
    # others rather than being reserved and left empty.
    for name in sorted(by_band, key=lambda item: len(by_band[item])):
        take = min(len(by_band[name]), max(quota, 0))
        kept.extend(by_band[name][:take])
        spare -= take
    if spare > 0:
        already = {term.term for term in kept}
        rest = sorted((t for t in terms if t.term not in already), key=_worth_showing)
        kept.extend(rest[:spare])
    kept.sort(key=lambda item: (-item.count, item.term))
    return kept
