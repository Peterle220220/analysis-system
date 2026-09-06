"""Statistics tests: what it computes, and - more importantly - what it declines.

Most tools will compute a p-value from eleven rows and print it to three decimal
places. The refusals here are the point: a test that states what it needs and
declines when it has not got it is the difference between a measurement and a
number that merely looks like one.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analysis_system.services.statistics import (
    MAX_GROUPS,
    MIN_GROUP,
    MIN_PER_PREDICTOR,
    MIN_SAMPLE,
    StatisticsError,
    StatisticsSpec,
    compute_statistics,
    suggest_spec,
)


def linked(rows: int = 200, noise: float = 3.0) -> pd.DataFrame:
    """A table where hours and score really do move together."""
    generator = np.random.default_rng(11)
    hours = generator.uniform(0.5, 8.0, rows)
    return pd.DataFrame(
        {
            "hours": hours,
            "score": 50 + 5 * hours + generator.normal(0, noise, rows),
            "shoe_size": generator.uniform(35, 45, rows),
            "job": ["Yes" if index % 2 else "No" for index in range(rows)],
            "grade": [("A", "B", "C", "D")[index % 4] for index in range(rows)],
        }
    )


def run(frame: pd.DataFrame, **spec: object) -> tuple[dict[str, float], list[str]]:
    metrics, refused = compute_statistics(frame, StatisticsSpec(**spec))  # type: ignore[arg-type]
    return {key: metric.value for key, metric in metrics.items()}, refused


# --- correlation ----------------------------------------------------------------


def test_a_real_relationship_is_measured() -> None:
    values, refused = run(linked(), correlations=(("hours", "score"),))
    assert refused == []
    assert values["hours.corr.with.score"] > 0.9
    assert values["hours.corr.with.score.p_value"] < 0.001
    assert values["hours.corr.with.score.n"] == 200


def test_the_share_of_variation_is_reported_too() -> None:
    # r on its own reads as bigger than it is. r squared says how much of the
    # spread the two actually share.
    values, _ = run(linked(), correlations=(("hours", "score"),))
    assert values["hours.r2.with.score"] == pytest.approx(
        values["hours.corr.with.score"] ** 2 * 100, rel=0.01
    )


def test_a_rank_correlation_is_reported_beside_the_linear_one() -> None:
    # Pearson only sees straight lines; a relationship that bends would look
    # weaker than it is.
    values, _ = run(linked(), correlations=(("hours", "score"),))
    assert "hours.rank_corr.with.score" in values


def test_two_unrelated_columns_report_a_correlation_near_zero() -> None:
    values, _ = run(linked(), correlations=(("shoe_size", "score"),))
    assert abs(values["shoe_size.corr.with.score"]) < 0.2


def test_too_few_pairs_is_refused_rather_than_computed() -> None:
    tiny = linked(rows=MIN_SAMPLE - 1)
    values, refused = run(tiny, correlations=(("hours", "score"),))
    assert values == {}
    assert any("cần ít nhất" in reason for reason in refused)


def test_a_column_that_never_changes_has_nothing_to_correlate() -> None:
    frame = linked()
    frame["flat"] = 7.0
    values, refused = run(frame, correlations=(("flat", "score"),))
    assert values == {}
    assert any("không đổi" in reason for reason in refused)


def test_a_text_column_is_refused_not_coerced() -> None:
    values, refused = run(linked(), correlations=(("job", "score"),))
    assert values == {}
    assert any("không phải cả hai đều là cột số" in reason for reason in refused)


# --- comparing groups -----------------------------------------------------------


def test_two_groups_get_a_t_test_and_the_size_of_the_gap() -> None:
    frame = linked()
    frame.loc[frame["job"] == "Yes", "score"] += 10
    values, _ = run(frame, group_differences=(("score", "job"),))
    assert values["score.ttest.by.job.p_value"] < 0.001
    assert values["score.diff.by.job"] < 0  # No is the first group, and now lower
    assert abs(values["score.effect_size.by.job"]) > 0.5


def test_effect_size_is_reported_because_a_p_value_alone_misleads() -> None:
    # With a thousand rows almost any gap is "significant"; only its size says
    # whether anyone should act on it.
    frame = linked(rows=2000)
    frame.loc[frame["job"] == "Yes", "score"] += 0.3
    values, _ = run(frame, group_differences=(("score", "job"),))
    assert values["score.ttest.by.job.p_value"] < 0.5
    assert abs(values["score.effect_size.by.job"]) < 0.2  # tiny, whatever p says


def test_three_groups_or_more_get_an_anova_and_eta_squared() -> None:
    frame = linked()
    values, _ = run(frame, group_differences=(("score", "grade"),))
    assert "score.anova.by.grade.p_value" in values
    assert "score.eta_sq.by.grade" in values
    assert values["score.anova.by.grade.groups"] >= 3


def test_a_group_too_small_to_speak_for_is_dropped_and_said_so() -> None:
    frame = linked(rows=60)
    frame.loc[frame.index[:2], "job"] = "Maybe"
    _, refused = run(frame, group_differences=(("score", "job"),))
    assert any(f"dưới {MIN_GROUP} dòng" in reason for reason in refused)


def test_an_identifier_column_is_refused_as_a_grouping() -> None:
    # A thousand groups of one row each is not a categorisation, and this is
    # exactly what a naive tool would happily run an ANOVA over.
    frame = linked()
    frame["student_id"] = range(len(frame))
    values, refused = run(frame, group_differences=(("score", "student_id"),))
    assert values == {}
    assert any("dưới hai nhóm đủ lớn" in reason for reason in refused)


def test_a_dimension_that_is_not_there_is_refused() -> None:
    values, refused = run(linked(), group_differences=(("score", "khong_co"),))
    assert values == {}
    assert any("không có cột" in reason for reason in refused)


def test_too_many_groups_is_refused() -> None:
    frame = linked(rows=(MAX_GROUPS + 2) * MIN_GROUP * 2)
    frame["many"] = [f"g{index % (MAX_GROUPS + 2)}" for index in range(len(frame))]
    values, refused = run(frame, group_differences=(("score", "many"),))
    assert values == {}
    assert any("định danh" in reason for reason in refused)


# --- the spec itself ------------------------------------------------------------


def test_a_malformed_spec_is_refused_rather_than_guessed_at() -> None:
    # Guessing what was meant would mean running a test nobody asked for.
    with pytest.raises(StatisticsError, match="phai la mot object"):
        StatisticsSpec.from_params("tuong quan het di")


def test_a_pair_that_is_not_a_pair_is_refused() -> None:
    with pytest.raises(StatisticsError, match="cap hai ten cot"):
        StatisticsSpec.from_params({"correlations": [["only_one"]]})


def test_an_empty_spec_runs_nothing_and_complains_about_nothing() -> None:
    values, refused = run(linked())
    assert values == {} and refused == []


# --- multiple regression: what each explanation is worth on its own -------------


def confounded(rows: int = 400) -> pd.DataFrame:
    """Two explanations that travel together, plus one that does nothing."""
    generator = np.random.default_rng(7)
    hours = generator.uniform(0.5, 8.0, rows)
    # Attendance follows hours closely, which is what a simple correlation
    # cannot see past.
    attendance = 60 + 4 * hours + generator.normal(0, 2, rows)
    return pd.DataFrame(
        {
            "hours": hours,
            "attendance": attendance,
            "noise": generator.normal(0, 1, rows),
            "score": 50 + 5 * hours + generator.normal(0, 2, rows),
        }
    )


def test_each_explanation_gets_a_coefficient_and_a_p_value() -> None:
    values, refused = run(linked(), regressions=(("score", ("hours",)),))
    assert values["score.coef.hours"] == pytest.approx(5.0, abs=0.5)
    assert values["score.coef.hours.p_value"] < 0.001
    assert values["score.regression.n"] == 200


def test_the_model_reports_how_much_it_explains() -> None:
    values, _ = run(linked(), regressions=(("score", ("hours",)),))
    assert values["score.regression.r2"] > 90
    # Adjusted, because adding any column at all raises the plain figure.
    assert values["score.regression.r2_adj"] <= values["score.regression.r2"]


def test_a_predictor_that_explains_nothing_gets_a_coefficient_near_zero() -> None:
    values, _ = run(confounded(), regressions=(("score", ("hours", "noise")),))
    assert abs(values["score.coef.noise"]) < 0.5
    assert values["score.coef.noise.p_value"] > 0.01


def test_regression_separates_what_a_correlation_cannot() -> None:
    # Attendance correlates with score only because it tracks hours. The simple
    # correlation is large; the coefficient, once hours are accounted for, is
    # not - and a reader who added the two correlations would have been misled.
    frame = confounded()
    simple, _ = run(frame, correlations=(("attendance", "score"),))
    fitted, _ = run(frame, regressions=(("score", ("hours", "attendance")),))
    assert simple["attendance.corr.with.score"] > 0.8
    assert abs(fitted["score.coef.attendance"]) < 1.0


def test_overlapping_explanations_are_flagged_by_their_vif() -> None:
    _, refused = run(confounded(), regressions=(("score", ("hours", "attendance")),))
    assert any("VIF" in reason for reason in refused)


def test_a_vif_is_reported_for_every_predictor() -> None:
    values, _ = run(confounded(), regressions=(("score", ("hours", "attendance")),))
    assert values["score.vif.hours"] > 1.0
    assert values["score.vif.attendance"] > 1.0


def test_too_few_rows_for_the_number_of_predictors_is_refused() -> None:
    frame = confounded(rows=MIN_PER_PREDICTOR * 3 - 1)
    values, refused = run(frame, regressions=(("score", ("hours", "attendance", "noise")),))
    assert values == {}
    assert any("mỗi biến" in reason for reason in refused)


def test_an_explanation_that_repeats_another_exactly_is_refused() -> None:
    # There is no unique fit, and printing one anyway would be inventing it.
    frame = confounded()
    frame["hours_again"] = frame["hours"]
    values, refused = run(frame, regressions=(("score", ("hours", "hours_again")),))
    assert values == {}
    assert any("trùng lặp hoàn toàn" in reason for reason in refused)


def test_a_constant_predictor_is_refused() -> None:
    frame = confounded()
    frame["flat"] = 1.0
    values, refused = run(frame, regressions=(("score", ("hours", "flat")),))
    assert values == {}
    assert any("không đổi giá trị" in reason for reason in refused)


def test_a_text_predictor_is_refused_not_coerced() -> None:
    frame = confounded()
    frame["label"] = "x"
    values, refused = run(frame, regressions=(("score", ("hours", "label")),))
    assert values == {}
    assert any("không phải cột số" in reason for reason in refused)


def test_two_models_for_one_outcome_are_refused() -> None:
    # They would write to the same metric keys and the second would silently
    # replace the first.
    with pytest.raises(StatisticsError, match="hai mo hinh cung du doan"):
        StatisticsSpec.from_params(
            {
                "regressions": [
                    {"outcome": "score", "predictors": ["hours"]},
                    {"outcome": "score", "predictors": ["attendance"]},
                ]
            }
        )


def test_a_regression_without_predictors_is_refused() -> None:
    with pytest.raises(StatisticsError, match="khong rong"):
        StatisticsSpec.from_params({"regressions": [{"outcome": "score", "predictors": []}]})


# --- choosing what to test, when nobody said ---------------------------------------
#
# Requiring the pair to be named up front asks the person to name the
# relationship they already suspect, and the answer they were looking for is
# usually the one they did not think to ask about.


def mixed() -> pd.DataFrame:
    """A table shaped like one that arrives: numbers, groups, and an id."""
    rows = 60
    return pd.DataFrame(
        {
            "student_id": [f"{index}" for index in range(rows)],
            "gender": ["nam", "nu"] * (rows // 2),
            "grade": ["A", "B", "C"] * (rows // 3),
            "score": [round(50 + (index * 7) % 40 + 0.5, 1) for index in range(rows)],
            "hours": [float(index % 9) for index in range(rows)],
            "note": [f"ghi chu rieng {index}" for index in range(rows)],
        }
    )


def test_it_proposes_correlations_between_the_number_columns() -> None:
    spec, _ = suggest_spec(mixed())
    assert ("hours", "score") in spec.correlations or ("score", "hours") in spec.correlations


def test_it_proposes_comparing_a_measure_across_a_grouping() -> None:
    spec, _ = suggest_spec(mixed())
    measures = {pair[0] for pair in spec.group_differences}
    groupings = {pair[1] for pair in spec.group_differences}
    assert measures <= {"score", "hours"}
    assert groupings <= {"gender", "grade"}


def test_a_numeric_identifier_is_never_correlated_with_anything() -> None:
    # A student id against an exam score is a number with a p-value attached and
    # no meaning at all - and it would have sat at the top of the list.
    spec, _ = suggest_spec(mixed())
    named = {name for pair in spec.correlations for name in pair}
    assert "student_id" not in named


def test_a_column_of_distinct_sentences_is_not_a_grouping() -> None:
    spec, _ = suggest_spec(mixed())
    assert "note" not in {pair[1] for pair in spec.group_differences}


def test_a_column_that_never_changes_is_left_out() -> None:
    frame = mixed().assign(constant=1.0)
    spec, _ = suggest_spec(frame)
    assert "constant" not in {name for pair in spec.correlations for name in pair}


def test_the_cap_spreads_across_the_table_rather_than_one_column() -> None:
    # Sorting by name meant the cap took every pair beginning with the first
    # column: one column tested against everything, every other column tested
    # against nothing.
    # Values that are measurements rather than counters: a column of 0..39
    # really is indistinguishable from a row number, and is left out.
    frame = pd.DataFrame(
        {
            name: [round((index * 7 + offset * 13) % 97 + 0.5, 1) for index in range(40)]
            for offset, name in enumerate(["a", "b", "c", "d", "e", "f"])
        }
    )
    spec, notes = suggest_spec(frame)
    named = {name for pair in spec.correlations for name in pair}
    assert named == set(frame.columns)
    assert any("chỉ chạy" in note for note in notes)


def test_it_says_when_it_had_to_stop_short() -> None:
    # A truncated search that does not say it was truncated is worse than a
    # small one.
    frame = pd.DataFrame(
        {
            f"n{index}": [round((row * 3 + index * 11) % 89 + 0.5, 1) for row in range(40)]
            for index in range(8)
        }
    )
    _, notes = suggest_spec(frame)
    assert any("ngẫu nhiên" in note for note in notes)


def test_it_never_proposes_a_regression_unasked() -> None:
    # Choosing which variables explain an outcome is a claim about how the world
    # works, and making it because nobody said otherwise would be the system
    # deciding what the analysis is about.
    spec, notes = suggest_spec(mixed())
    assert spec.regressions == ()
    assert any("hồi quy" in note for note in notes)


def test_a_declared_measure_narrows_the_search() -> None:
    spec, _ = suggest_spec(mixed(), measures=["score"])
    assert all("hours" not in pair for pair in spec.correlations)


def test_a_table_with_nothing_to_test_says_so() -> None:
    frame = pd.DataFrame({"note": [f"cau {index}" for index in range(30)]})
    spec, notes = suggest_spec(frame)
    assert spec.correlations == ()
    assert spec.group_differences == ()
    assert any("tự đề xuất được" in note for note in notes)


def test_the_same_table_proposes_the_same_tests_twice() -> None:
    frame = mixed()
    assert suggest_spec(frame)[0] == suggest_spec(frame)[0]


def test_what_it_proposes_actually_runs() -> None:
    # A proposal that produces nothing measurable would be a list of intentions.
    spec, _ = suggest_spec(mixed())
    metrics, _ = compute_statistics(mixed(), spec)
    assert metrics
