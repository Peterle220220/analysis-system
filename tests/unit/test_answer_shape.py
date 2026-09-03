"""Does the answer have the shape the question asked for?

Tested from both sides throughout. A check that reported every answer as a miss
would pass every test that only looks at what it caught, and would be worse than
no check at all - so each rule is paired with a case it must let through.
"""

from __future__ import annotations

from analysis_system.services.answer_shape import (
    Demand,
    check,
    fold,
    read_question,
    satisfied_by,
)

# --- reading what the question wants ----------------------------------------------


def test_a_question_about_causes_is_read_as_one() -> None:
    for question in (
        "Yếu tố nào ảnh hưởng đến điểm thi cuối kỳ?",
        "Vì sao hồ sơ nộp qua bưu điện lâu hơn?",
        "Điểm thi phụ thuộc vào cái gì?",
        "Nguyên nhân của tỷ lệ hoàn cao là gì?",
    ):
        assert read_question(question) is Demand.CAUSE, question


def test_a_question_asking_for_a_figure_is_read_as_one() -> None:
    for question in (
        "Kênh A đạt hiệu suất bao nhiêu %?",
        "Tỷ lệ hoàn của kênh đại lý là bao nhiêu?",
        "Điểm trung bình của lớp là mấy?",
    ):
        assert read_question(question) is Demand.QUANTITY, question


def test_a_question_asking_which_one_is_read_as_a_ranking() -> None:
    assert read_question("Kênh nào có tỷ lệ hoàn cao nhất?") is Demand.RANKING
    assert read_question("Bước nào chậm nhất trong quy trình?") is Demand.RANKING


def test_an_open_question_is_read_as_open() -> None:
    assert read_question("Từ dữ liệu này có thể thấy những điều gì?") is Demand.OPEN
    assert read_question("Đánh giá tổng quan chất lượng dữ liệu?") is Demand.OPEN


def test_cause_wins_over_the_figure_words_inside_it() -> None:
    """The trap the ordering exists for.

    "Yếu tố nào ảnh hưởng đến tỷ lệ hoàn" contains "tỷ lệ", and is not a request
    for a percentage - it asks what moves one. Read the other way round, a
    correlation would be reported as failing to answer, which is backwards.
    """
    assert read_question("Yếu tố nào ảnh hưởng đến tỷ lệ hoàn?") is Demand.CAUSE
    assert read_question("Kênh nào có tỷ lệ hoàn cao nhất?") is Demand.RANKING


def test_a_question_of_no_recognisable_kind_is_treated_as_open() -> None:
    """Guessing wrong here would refuse a good answer, so it does not guess.

    The job is catching answers that miss, not inventing new ways to miss.
    """
    assert read_question("abcxyz") is Demand.OPEN
    assert read_question("") is Demand.OPEN


def test_the_question_reads_the_same_with_or_without_accents() -> None:
    assert read_question("Yếu tố nào ảnh hưởng đến điểm thi?") is Demand.CAUSE
    assert read_question("Yeu to nao anh huong den diem thi?") is Demand.CAUSE


def test_folding_keeps_the_percent_sign() -> None:
    """ "bao nhiêu %" is a request for a figure, and the sign is half the signal."""
    assert "%" in fold("Đạt bao nhiêu %?")


# --- judging whether the figures can answer it ------------------------------------


def test_a_cause_question_needs_a_relationship() -> None:
    """The failure this was built for.

    Asked which factors carry the exam score, a real run answered with the
    average attendance and the share of missing values. Both true, both about
    the right subject, and neither says what moves what.
    """
    missed = satisfied_by(Demand.CAUSE, ["attendance_percent.mean", "attendance_percent.null_pct"])
    assert missed.met is False
    assert "NGUYEN NHAN" in missed.shortfall

    met = satisfied_by(Demand.CAUSE, ["attendance_percent.corr.with.final_exam_score"])
    assert met.met is True
    assert met.shortfall == ""


def test_a_cause_question_accepts_every_relational_family() -> None:
    """All of these say something about what moves what; none is a summary."""
    for key in (
        "a.corr.with.b",
        "a.rank_corr.with.b",
        "a.r2.with.b",
        "a.diff.by.channel",
        "a.effect_size.by.channel",
        "a.eta_sq.by.grade",
        "score.importance.hours",
    ):
        assert satisfied_by(Demand.CAUSE, [key]).met is True, key


def test_a_figure_question_needs_a_figure() -> None:
    assert satisfied_by(Demand.QUANTITY, ["avg_ty_le_hoan.mean"]).met is True
    assert satisfied_by(Demand.QUANTITY, ["rows.total"]).met is True
    # A relationship is not a figure: asked what percentage A reached, a
    # correlation coefficient answers a different question.
    assert satisfied_by(Demand.QUANTITY, ["Kenh.corr.with.doanh_thu"]).met is False


def test_a_ranking_question_needs_more_than_one_thing_or_an_extreme() -> None:
    assert satisfied_by(Demand.RANKING, ["avg_ty_le_hoan.max"]).met is True
    assert satisfied_by(Demand.RANKING, ["a.events", "b.events"]).met is True
    # One figure on its own cannot show that anything came top.
    single = satisfied_by(Demand.RANKING, ["avg_ty_le_hoan.mean"])
    assert single.met is False
    assert "DUNG DAU" in single.shortfall


def test_a_comparison_question_needs_two_sides() -> None:
    assert satisfied_by(Demand.COMPARISON, ["score.diff.by.channel"]).met is True
    assert satisfied_by(Demand.COMPARISON, ["rows.total"]).met is False


def test_a_trend_question_says_so_when_nothing_is_measured_over_time() -> None:
    """The system does not compute anything by period yet, and must admit it.

    Answering a question about change over time with a total is how a report
    starts implying a trend nobody measured.
    """
    missed = satisfied_by(Demand.TREND, ["total_doanh_thu.sum", "total_doanh_thu.mean"])
    assert missed.met is False
    assert "XU HUONG" in missed.shortfall
    assert satisfied_by(Demand.TREND, ["doanh_thu.by.month"]).met is True


def test_an_open_question_takes_any_supported_claim() -> None:
    assert satisfied_by(Demand.OPEN, ["anything.at.all"]).met is True


def test_a_claim_citing_nothing_answers_nothing() -> None:
    """Every kind of question, including the open one, needs some figure."""
    for demand in Demand:
        assert satisfied_by(demand, []).met is False, demand


# --- end to end -------------------------------------------------------------------


def test_the_real_failure_is_caught_and_the_real_answer_is_not() -> None:
    """Both directions on the run that prompted the work."""
    question = "Yếu tố nào ảnh hưởng đến điểm thi cuối kỳ?"
    assert check(question, ["attendance_percent.mean"]).met is False
    assert check(question, ["attendance_percent.corr.with.final_exam_score"]).met is True


def test_the_shortfall_says_what_was_wanted_and_what_came() -> None:
    """A person has to be able to act on it - "check failed" is not actionable."""
    verdict = check("Vì sao bưu điện lâu hơn?", ["process.duration.mean_hours"])
    assert verdict.met is False
    assert verdict.shortfall
    assert "tung cot rieng le" in verdict.shortfall
