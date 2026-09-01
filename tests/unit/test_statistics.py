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
    MIN_SAMPLE,
    StatisticsError,
    StatisticsSpec,
    compute_statistics,
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
    assert any("can it nhat" in reason for reason in refused)


def test_a_column_that_never_changes_has_nothing_to_correlate() -> None:
    frame = linked()
    frame["flat"] = 7.0
    values, refused = run(frame, correlations=(("flat", "score"),))
    assert values == {}
    assert any("khong doi" in reason for reason in refused)


def test_a_text_column_is_refused_not_coerced() -> None:
    values, refused = run(linked(), correlations=(("job", "score"),))
    assert values == {}
    assert any("khong phai ca hai deu la cot so" in reason for reason in refused)


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
    assert any(f"duoi {MIN_GROUP} dong" in reason for reason in refused)


def test_an_identifier_column_is_refused_as_a_grouping() -> None:
    # A thousand groups of one row each is not a categorisation, and this is
    # exactly what a naive tool would happily run an ANOVA over.
    frame = linked()
    frame["student_id"] = range(len(frame))
    values, refused = run(frame, group_differences=(("score", "student_id"),))
    assert values == {}
    assert any("duoi hai nhom du lon" in reason for reason in refused)


def test_a_dimension_that_is_not_there_is_refused() -> None:
    values, refused = run(linked(), group_differences=(("score", "khong_co"),))
    assert values == {}
    assert any("khong co cot" in reason for reason in refused)


def test_too_many_groups_is_refused() -> None:
    frame = linked(rows=(MAX_GROUPS + 2) * MIN_GROUP * 2)
    frame["many"] = [f"g{index % (MAX_GROUPS + 2)}" for index in range(len(frame))]
    values, refused = run(frame, group_differences=(("score", "many"),))
    assert values == {}
    assert any("dinh danh" in reason for reason in refused)


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
