"""Measuring what carries an outcome, and which rows resemble each other.

Nothing here predicts, and that is the design rather than a gap: a prediction
traces back to a model, a split and a seed, and the whole system rests on every
claim tracing back to rows somebody can go and look at.

**The refusals carry more weight here than anywhere else in the suite.** Both
techniques produce confident output on data that cannot support them - a forest
will rank variables on thirty rows and k-means will return five tidy clusters
from one formless cloud, and neither says so. Half these tests exist to check
that this one does.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analysis_system.services.modelling import (
    MIN_ROWS,
    MIN_SILHOUETTE,
    ModellingError,
    find_clusters,
    measure_importance,
)

FEATURES = ["gio_hoc", "chuyen_can", "gio_ngu"]


def carried(rows: int = 400, noise: float = 3.0) -> pd.DataFrame:
    """A table where the outcome really is carried by two of three columns."""
    rng = np.random.default_rng(7)
    hours = rng.uniform(0, 10, rows)
    attendance = rng.uniform(50, 100, rows)
    sleep = rng.uniform(4, 10, rows)
    score = 30 + 4.0 * hours + 0.3 * attendance + rng.normal(0, noise, rows)
    return pd.DataFrame(
        {"gio_hoc": hours, "chuyen_can": attendance, "gio_ngu": sleep, "diem": score}
    )


def clustered(per_group: int = 80) -> pd.DataFrame:
    """Three groups that really are apart from each other."""
    rng = np.random.default_rng(0)
    parts = [
        pd.DataFrame({"x": rng.normal(cx, 1.0, per_group), "y": rng.normal(cy, 1.0, per_group)})
        for cx, cy in ((0.0, 0.0), (12.0, 12.0), (0.0, 14.0))
    ]
    return pd.concat(parts, ignore_index=True)


def noise(rows: int = 300) -> pd.DataFrame:
    """Columns with nothing between them at all."""
    rng = np.random.default_rng(1)
    return pd.DataFrame({name: rng.normal(0, 1, rows) for name in [*FEATURES, "diem"]})


# --- what carries the outcome ------------------------------------------------------


def test_it_finds_the_variable_that_actually_carries_the_outcome() -> None:
    found = measure_importance(carried(), "diem", FEATURES)
    assert found.ranking
    assert found.ranking[0].feature == "gio_hoc"


def test_a_variable_with_nothing_to_do_with_it_ranks_last() -> None:
    found = measure_importance(carried(), "diem", FEATURES)
    assert found.ranking[-1].feature == "gio_ngu"


def test_the_model_is_scored_on_rows_it_never_saw() -> None:
    # A model asked how well it fits what it memorised will always say
    # "perfectly", and that number would then be quoted.
    found = measure_importance(carried(), "diem", FEATURES)
    assert found.metrics["diem.model.r2_holdout"].value > 0.5


def test_the_shares_are_reported_as_named_metrics() -> None:
    # Nothing downstream needs changing: an importance is a number code
    # computed with a name, exactly like a correlation.
    found = measure_importance(carried(), "diem", FEATURES)
    assert "diem.importance.gio_hoc" in found.metrics
    assert found.metrics["diem.importance.gio_hoc"].unit == "%"


def test_it_says_out_loud_that_importance_is_not_effect() -> None:
    # "Knowing this helps predict that" is read as "changing this changes that"
    # constantly, and it is not that.
    found = measure_importance(carried(), "diem", FEATURES)
    assert any("khong do tac dong" in note for note in found.refused)


def test_the_same_table_ranks_the_same_way_twice() -> None:
    first = measure_importance(carried(), "diem", FEATURES)
    second = measure_importance(carried(), "diem", FEATURES)
    assert [item.feature for item in first.ranking] == [item.feature for item in second.ranking]


# --- and when it will not say ------------------------------------------------------


def test_too_few_rows_for_the_number_of_variables_is_refused() -> None:
    # Below this a model fits the rows in front of it rather than whatever
    # produced them.
    found = measure_importance(carried(rows=25), "diem", FEATURES)
    assert found.ranking == ()
    assert any("dong dung duoc" in note for note in found.refused)


def test_a_model_that_does_not_fit_ranks_nothing() -> None:
    # Ranking the variables of a model that explains nothing is ranking noise -
    # and it comes out looking exactly like a finding.
    found = measure_importance(noise(), "diem", FEATURES)
    assert found.ranking == ()
    assert any("KHONG duoc hoc" in note for note in found.refused)


def test_a_ranking_that_moves_with_the_seed_is_thrown_away() -> None:
    # Tree importances shift with the random draw. A ranking that changes with
    # the seed is a ranking of nothing, and this is the check most tools skip.
    rng = np.random.default_rng(3)
    rows = 120
    shared = rng.normal(0, 1, rows)
    # Three near-identical columns: which one "matters" is then arbitrary.
    frame = pd.DataFrame(
        {
            "gio_hoc": shared + rng.normal(0, 0.01, rows),
            "chuyen_can": shared + rng.normal(0, 0.01, rows),
            "gio_ngu": shared + rng.normal(0, 0.01, rows),
            "diem": 5.0 * shared + rng.normal(0, 0.4, rows),
        }
    )
    found = measure_importance(frame, "diem", FEATURES)
    assert found.ranking == ()
    assert any("hat giong" in note for note in found.refused)


def test_an_outcome_that_never_changes_has_nothing_to_explain() -> None:
    frame = carried().assign(diem=5.0)
    found = measure_importance(frame, "diem", FEATURES)
    assert found.ranking == ()
    assert any("khong doi gia tri" in note for note in found.refused)


def test_a_column_that_is_not_there_is_an_error_not_a_refusal() -> None:
    # Guessing which column was meant is how a model ends up fitted on
    # something nobody asked about.
    with pytest.raises(ModellingError, match="khong co cot"):
        measure_importance(carried(), "diem", ["khong_ton_tai"])


def test_explaining_an_outcome_with_itself_is_refused() -> None:
    with pytest.raises(ModellingError, match="it nhat mot bien"):
        measure_importance(carried(), "diem", ["diem"])


# --- which rows resemble each other --------------------------------------------------


def test_groups_that_are_really_there_are_found() -> None:
    found = find_clusters(clustered(), ["x", "y"])
    assert len(found.clusters) == 3
    assert found.quality > MIN_SILHOUETTE


def test_each_group_says_how_much_of_the_data_it_holds() -> None:
    found = find_clusters(clustered(), ["x", "y"])
    assert round(sum(cluster.share_pct for cluster in found.clusters)) == 100
    assert "cluster.0.share_pct" in found.metrics


def test_each_group_says_what_sets_it_apart() -> None:
    # "There are three groups" is not actionable; "this one differs on x" is.
    found = find_clusters(clustered(), ["x", "y"])
    assert all(cluster.distinguishing for cluster in found.clusters)


def test_a_single_cloud_is_refused_rather_than_divided() -> None:
    # Any number of clusters can be imposed on any cloud of points. The question
    # is whether the divisions were there already, and almost nothing asks it.
    rng = np.random.default_rng(5)
    blob = pd.DataFrame({"x": rng.normal(0, 1, 300), "y": rng.normal(0, 1, 300)})
    found = find_clusters(blob, ["x", "y"])
    assert found.clusters == ()
    assert any("MOT dam" in note for note in found.refused)


def test_the_alternatives_it_weighed_are_reported() -> None:
    # A number of groups chosen without saying what else was tried is a number
    # somebody has to take on trust.
    found = find_clusters(clustered(), ["x", "y"])
    assert any("da thu cac cach chia" in note for note in found.refused)


def test_too_few_rows_to_group_is_refused() -> None:
    found = find_clusters(clustered(per_group=5), ["x", "y"])
    assert found.clusters == ()
    assert any(str(MIN_ROWS) in note for note in found.refused)


def test_one_column_is_not_enough_to_group_by() -> None:
    found = find_clusters(clustered(), ["x"])
    assert found.clusters == ()
    assert any("hai cot" in note for note in found.refused)


def test_the_scale_of_a_column_does_not_decide_the_grouping() -> None:
    # Without standardising, the column with the largest numbers decides - and
    # "largest numbers" is a property of the units somebody chose.
    frame = clustered()
    stretched = frame.assign(y=frame["y"] * 1000.0)
    assert len(find_clusters(stretched, ["x", "y"]).clusters) == len(
        find_clusters(frame, ["x", "y"]).clusters
    )


def test_the_same_table_groups_the_same_way_twice() -> None:
    first = find_clusters(clustered(), ["x", "y"])
    second = find_clusters(clustered(), ["x", "y"])
    assert first.labels == second.labels


def test_nothing_here_predicts_anything() -> None:
    # The design, not a gap. A prediction traces to a model, a split and a seed;
    # everything reported here traces to rows.
    found = find_clusters(clustered(), ["x", "y"])
    assert len(found.labels) == len(clustered().index)
    ranked = measure_importance(carried(), "diem", FEATURES)
    assert all("forecast" not in key and "predict" not in key for key in ranked.metrics)
