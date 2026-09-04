"""Đếm từ trong văn xuôi, và nói thật về việc đếm nói lên được gì.

Tested from both ends throughout, because the whole point of the module is that
**neither end of the frequency range means "important" on its own**. A test
suite that only checked rare words would pass a module that called every rare
word a finding, which is the mistake the design exists to avoid.
"""

from __future__ import annotations

from analysis_system.services.salience import (
    MAX_MENTIONS,
    RARE_AT_MOST,
    WALLPAPER_SHARE,
    Reading,
    content_words,
    fold,
    read,
)

# The boss's own example: 500 words where one term fills 300 slots and another
# is mentioned twice.
WALLPAPER = " ".join(["doanh thu"] * 150) + (
    " bao cao quy ba ghi nhan tang truong 12,5% so cung ky"
    " nhom ky thuat da thu nghiem machine learning de du bao ton kho"
    " ket qua machine learning cho sai so 3,2% tren tap kiem tra"
)


# --- folding and word selection ---------------------------------------------------


def test_the_same_word_written_both_ways_is_one_term() -> None:
    """Half a document rarely agrees with the other half about accents."""
    assert fold("Doanh Thu") == fold("doanh thu")
    assert fold("Điểm") == "diem"


def test_grammar_is_not_subject() -> None:
    words = content_words("doanh thu cua chung toi la rat cao")
    assert "doanh" in words
    assert "cua" not in words
    assert "la" not in words


def test_a_single_letter_is_not_a_term() -> None:
    assert content_words("a b doanh") == ["doanh"]


# --- the two ends of the range ----------------------------------------------------


def test_a_word_filling_the_document_is_called_wallpaper() -> None:
    """It is what the text is about, so it separates no part of it from another.

    Not a judgement of worth: a table built on this term would have one row.
    """
    found = read(WALLPAPER)
    wallpaper = {term.term for term in found.band("nen")}
    assert "doanh thu" in wallpaper
    assert all(term.share >= WALLPAPER_SHARE for term in found.band("nen"))


def test_wallpaper_says_why_it_is_not_useful_for_a_table() -> None:
    found = read(WALLPAPER)
    assert "mot dong" in found.band("nen")[0].note


def test_a_word_mentioned_twice_is_a_question_not_a_conclusion() -> None:
    """The boss's case: a report thick with figures naming machine learning twice.

    It is reported as worth asking about, and the note says plainly that
    frequency alone cannot tell a real emphasis from a passing mention.
    """
    found = read(WALLPAPER)
    rare = {term.term for term in found.band("hiem")}
    assert "machine learning" in rare
    note = next(term.note for term in found.terms if term.term == "machine learning")
    assert "HOI VI SAO" in note


def test_the_band_boundary_holds_in_both_directions() -> None:
    body = " ".join(["alpha"] * 3 + ["beta"] * 8 + ["gamma"] * 200)
    found = read(body)
    bands = {term.term: term.band for term in found.terms}
    assert bands["alpha"] == "hiem", "3 lan tro xuong thi dang hoi"
    assert bands["beta"] == "vua", "khong hiem ma cung khong phai nen"
    assert bands["gamma"] == "nen"
    assert RARE_AT_MOST == 3


# --- phrases, because Vietnamese counts in phrases ---------------------------------


def test_two_words_making_one_idea_are_counted_as_one() -> None:
    """Counting the halves apart is how the term worth noticing disappears."""
    found = read(WALLPAPER)
    assert any(term.term == "machine learning" and term.is_phrase for term in found.terms)


def test_a_pair_seen_once_is_not_a_term() -> None:
    found = read("doanh thu tang manh trong quy nay")
    assert not any(term.is_phrase for term in found.terms)


def test_the_reversed_artefact_of_a_repeated_pair_is_dropped() -> None:
    """ "doanh thu" repeated also produces "thu doanh", and only one is a term."""
    found = read(WALLPAPER)
    reported = {term.term for term in found.terms}
    assert "doanh thu" in reported
    assert "thu doanh" not in reported


def test_a_syllable_only_ever_seen_inside_a_phrase_is_dropped() -> None:
    """Vietnamese is monosyllabic: `buu` is noise, `buu dien` is the post office.

    Reporting all three buries the term in its own fragments.
    """
    found = read("kenh buu dien cham hon. Ty le hoan cua buu dien la 9,4%.")
    reported = {term.term for term in found.terms}
    assert "buu dien" in reported
    assert "buu" not in reported
    assert "dien" not in reported


def test_a_word_used_alone_as_well_as_in_a_phrase_is_kept() -> None:
    """Then it really is being used by itself too, and dropping it loses that."""
    found = read("machine learning rat manh. Machine learning tot. Con machine thi cu.")
    reported = {term.term for term in found.terms}
    assert "machine learning" in reported
    assert "machine" in reported


# --- the bridge to a table ---------------------------------------------------------


def test_the_figures_beside_a_term_are_captured_with_it() -> None:
    """What makes the next step possible: "tu nay di voi nhung so nao".

    Measured while reading rather than hunted for by hand afterwards.
    """
    found = read(
        "Ap dung machine learning cho du bao. "
        "Do chinh xac cua machine learning dat 87% tren tap kiem tra."
    )
    term = next(item for item in found.terms if item.term == "machine learning")
    assert "87%" in term.numbers


def test_a_figure_far_from_a_term_is_not_credited_to_it() -> None:
    far = "machine learning ke tiep. machine learning " + " ".join(["xen"] * 30) + " 4880"
    found = read(far)
    term = next(item for item in found.terms if item.term == "machine learning")
    assert "4880" not in term.numbers


def test_a_term_traces_back_to_where_it_was_read() -> None:
    """Same rule as every other claim in this system: it points at a source."""
    lines = ["Bao cao quy III.", "Ap dung machine learning.", "Do chinh xac machine learning 87%."]
    found = read("\n".join(lines), locators=["trang 1", "trang 2", "trang 5"])
    term = next(item for item in found.terms if item.term == "machine learning")
    assert term.where == ("trang 2", "trang 5")


# --- and it admits what it did not do ----------------------------------------------


def test_nothing_to_read_is_said_rather_than_returned_empty() -> None:
    for empty in ("", "   ", "\n\n"):
        found = read(empty)
        assert found.terms == ()
        assert found.declined


def test_text_of_pure_grammar_says_so() -> None:
    found = read("la cua va co the cho voi tu den")
    assert found.terms == ()
    assert any("khong co tu nao mang noi dung" in note for note in found.declined)


def test_a_long_tail_that_was_cut_is_reported() -> None:
    """A list nobody can read is a list nobody reads - but the cut is admitted."""
    body = " ".join(f"tu{index}" for index in range(200))
    found = read(body, max_terms=10)
    assert len(found.terms) == 10
    assert any("chi bao cao" in note for note in found.declined)


def test_a_reading_can_be_asked_for_one_band() -> None:
    found = read(WALLPAPER)
    assert all(term.band == "hiem" for term in found.band("hiem"))
    assert isinstance(found, Reading)


# --- van ban tieng Anh tu dau den cuoi -----------------------------------------

REVIEWS = """I would not recommend this service. The delivery was very slow and they \
did not answer my emails for three days.
Very slow delivery. I waited two weeks and they told me it was lost. The refund \
process is so complicated.
The support team was helpful but the app keeps crashing. I would like a refund \
if this is not fixed.
Delivery was fast and the packaging was good. My only complaint is that the app \
is slow to load.
They charged me twice. I called support and they said it would take ten days to \
refund. Very frustrating."""


def test_english_pronouns_do_not_crowd_out_the_subject() -> None:
    # Measured before this was fixed: "they" came first, ahead of delivery,
    # refund and support. The stopword list was written for Vietnamese text with
    # the English that leaks into a technical document, and English-throughout
    # text is a different thing.
    top = [term.term for term in read(REVIEWS).terms[:6]]
    assert "they" not in top
    assert "would" not in top
    assert {"delivery", "refund", "slow"} <= set(top)


def test_an_intensifier_survives_because_it_builds_a_phrase() -> None:
    # "very" is grammar on its own and would be easy to add to the stopword
    # list. It is deliberately absent: it makes "very slow", which says
    # something "slow" alone does not.
    terms = [term.term for term in read(REVIEWS).terms]
    assert "very slow" in terms


def test_a_term_in_thousands_of_rows_lists_only_a_few_of_them() -> None:
    # In an extracted document "a place" is a page and there are a handful. In a
    # table it is a ROW, so mining a column of 4,666 sentences gave one mention
    # per row and the report grew until one call to the Manager needed 113,554
    # tokens against a 50,000 limit.
    lines = [f"khach hang phan nan ve dich vu {index}" for index in range(500)]
    locators = [f"dong {index}" for index in range(500)]
    found = read("\n".join(lines), locators=locators)
    crowded = [term for term in found.terms if term.term == "khach hang"]
    assert crowded, "cum 'khach hang' phai co trong bao cao"
    assert len(crowded[0].mentions) == MAX_MENTIONS
    # The real number is not lost - it is what `count` has always been.
    assert crowded[0].count == 500


def test_the_report_says_it_only_listed_some_of_the_places() -> None:
    # Truncating without saying so is the failure this codebase keeps refusing.
    lines = [f"khach hang phan nan ve dich vu {index}" for index in range(500)]
    locators = [f"dong {index}" for index in range(500)]
    found = read("\n".join(lines), locators=locators)
    assert any("vi tri dau tien" in note for note in found.declined)


def test_a_short_document_lists_every_place_it_has() -> None:
    # The cap must not bite on the ordinary case, or every report would carry a
    # warning about nothing.
    found = read("doanh thu tang manh\ndoanh thu quy hai", locators=["trang 1", "trang 2"])
    assert not any("vi tri dau tien" in note for note in found.declined)
