"""Choosing what to analyse, and what changing that choice actually does.

The mechanism is built around *features* rather than columns because the next
data type will not have columns. So the tests are too: several of them use an
event log, where the things worth choosing between are activities and people,
and nothing in the selection machinery is allowed to notice the difference.

The test that matters most is the last one. It changes a selection on a finished
run and checks that exactly the affected tasks run again - which only works
because a task's parameters are part of its identity (L40). Without that fix this
whole feature would hand back the previous answer to the new question.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from analysis_system.contracts.agents import Plan, PlannedTask
from analysis_system.core.boundary import load_manifest
from analysis_system.manager.selection import affected_tasks, apply_selection
from analysis_system.services.features import (
    KIND_ACTIVITY,
    KIND_COLUMN,
    KIND_RESOURCE,
    ROLE_CATEGORICAL,
    ROLE_IDENTIFIER,
    ROLE_NUMERIC,
    ROLE_TEXT,
    Feature,
    FeatureCatalogue,
    FeatureError,
    Selection,
    catalogue_for,
    columns_of,
    describe,
    event_features_of,
    merge,
    parse_key,
)

MANIFEST_DIR = Path(__file__).resolve().parents[2] / "config" / "manifests"


def students() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "student_id": [f"s{index}" for index in range(10)],
            "gender": ["nam", "nu"] * 5,
            "exam_score": [float(50 + index) for index in range(10)],
            "note": [f"ghi chu rieng so {index}" for index in range(10)],
        }
    )


def log() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "case_id": ["c1", "c1", "c2", "c2"],
            "activity": ["SRM: Created", "Duyet", "SRM: Created", "Huy"],
            "resource": ["an", "binh", "an", "an"],
        }
    )


# --- what a column looks like, measured rather than judged -----------------------


def test_a_number_column_is_reported_as_a_number() -> None:
    found = {feature.name: feature.role for feature in columns_of(students())}
    assert found["exam_score"] == ROLE_NUMERIC


def test_a_column_with_a_few_repeated_values_is_a_grouping() -> None:
    found = {feature.name: feature.role for feature in columns_of(students())}
    assert found["gender"] == ROLE_CATEGORICAL


def test_a_column_with_one_value_per_row_is_an_identifier_not_a_grouping() -> None:
    # Breaking an analysis down by it produces one group per row, which is the
    # table again with more steps.
    found = {feature.name: feature.role for feature in columns_of(students())}
    assert found["student_id"] == ROLE_IDENTIFIER


def test_a_column_with_too_many_groups_to_group_by_is_text() -> None:
    # Many distinct values but not one per row: not an identifier, and not
    # something anybody can break an analysis down by either.
    values = [f"ghi chu {index % 70}" for index in range(200)]
    assert columns_of(pd.DataFrame({"note": values}))[0].role == ROLE_TEXT


def test_a_note_column_where_every_row_differs_is_called_an_identifier() -> None:
    # A known and accepted limitation. Telling prose apart from an id would mean
    # guessing from string length, which is an opinion about the data rather
    # than a measurement of it, and this module holds no opinions. Both roles
    # mean the same thing downstream - do not group by this - so the cost is one
    # slightly odd word in a listing.
    values = [f"cau ghi chu khac nhau {index}" for index in range(80)]
    assert columns_of(pd.DataFrame({"note": values}))[0].role == ROLE_IDENTIFIER


def test_an_empty_column_does_not_crash_the_catalogue() -> None:
    frame = pd.DataFrame({"trong": [None, None, None]})
    assert columns_of(frame)[0].role == ROLE_TEXT


# --- the abstraction holds for something that is not a column --------------------


def test_an_event_log_offers_activities_and_people_to_choose_between() -> None:
    # The whole reason this is not a list of columns. Nothing above the
    # extractors knows an activity is not a column.
    found = event_features_of(log(), "activity", "resource")
    kinds = {feature.kind for feature in found}
    assert kinds == {KIND_ACTIVITY, KIND_RESOURCE}
    assert "activity:SRM: Created" in {feature.key for feature in found}


def test_a_key_survives_a_name_that_contains_the_separator() -> None:
    # A real log has an activity called "SRM: Created". Splitting on every colon
    # would invent a kind nobody declared.
    kind, name = parse_key("activity:SRM: Created")
    assert kind == KIND_ACTIVITY
    assert name == "SRM: Created"


def test_a_key_with_no_kind_is_refused() -> None:
    with pytest.raises(FeatureError, match="loai:ten"):
        parse_key("exam_score")


def test_a_catalogue_carries_columns_and_activities_together() -> None:
    catalogue = catalogue_for(
        log(), "clean://log.parquet", activity="activity", resource="resource"
    )
    assert catalogue.of_kind(KIND_COLUMN)
    assert catalogue.of_kind(KIND_ACTIVITY)
    assert catalogue.get("activity:Huy") is not None


def test_merging_catalogues_keeps_the_first_description_of_a_key() -> None:
    # Adding a source must never change what an existing key means.
    first = FeatureCatalogue("a", (Feature(KIND_COLUMN, "x", ROLE_NUMERIC, "dau tien"),))
    second = FeatureCatalogue("b", (Feature(KIND_COLUMN, "x", ROLE_TEXT, "sau"),))
    merged = merge([first, second], "ca hai")
    assert merged.features[0].detail == "dau tien"


# --- a selection that names something absent is refused ---------------------------


def test_a_selection_naming_a_column_that_is_not_there_is_refused() -> None:
    # Analysing the four they spelled right and saying nothing is how somebody
    # reads an answer to a question they did not ask.
    catalogue = catalogue_for(students(), "mart://x.parquet")
    with pytest.raises(FeatureError, match="exam_scr"):
        Selection.from_params(["column:exam_scr"]).validate(catalogue)


def test_a_selection_naming_real_features_passes() -> None:
    catalogue = catalogue_for(students(), "mart://x.parquet")
    Selection.from_params(["column:exam_score", "column:gender"]).validate(catalogue)


def test_choosing_nothing_means_everything_not_an_empty_analysis() -> None:
    # The state before anybody has chosen. Not the same as choosing nothing.
    assert Selection.from_params(None).is_empty
    assert Selection.from_params([]).is_empty


def test_the_same_features_in_a_different_order_are_the_same_selection() -> None:
    # Otherwise the params fingerprint differs and the task re-runs for no
    # reason, which is L40 working correctly against a question nobody asked.
    first = Selection.from_params(["column:b", "column:a"])
    second = Selection.from_params(["column:a", "column:b", "column:a"])
    assert first.keys == second.keys


def test_a_selection_that_is_not_a_list_is_refused() -> None:
    with pytest.raises(FeatureError, match="danh sach"):
        Selection.from_params("column:exam_score")


def test_the_listing_marks_what_is_in_and_what_is_out() -> None:
    catalogue = catalogue_for(students(), "mart://x.parquet")
    lines = describe(catalogue, Selection.from_params(["column:gender"]))
    assert any(line.startswith("[x] column:gender") for line in lines)
    assert any(line.startswith("[ ] column:exam_score") for line in lines)


# --- turning a choice into a plan --------------------------------------------------


def small_plan() -> Plan:
    return Plan(
        tasks=(
            PlannedTask(task_id="t1_ingest", agent_id="a1_ingest"),
            PlannedTask(task_id="t5_validate", agent_id="a5_validator", depends_on=("t1_ingest",)),
            PlannedTask(
                task_id="t6_analyse",
                agent_id="a7_analyst",
                depends_on=("t5_validate",),
                params={"question": "diem so ra sao"},
            ),
        ),
        reason="ke hoach thu",
    )


def test_a_chosen_column_lands_in_the_parameter_its_role_belongs_to() -> None:
    # A person picks two columns. They should not also have to say which is the
    # thing being measured and which is the grouping - that is measurable.
    catalogue = catalogue_for(students(), "mart://x.parquet")
    selection = Selection.from_params(["column:exam_score", "column:gender"])
    changed = apply_selection(small_plan(), selection, catalogue, MANIFEST_DIR)
    params = next(task.params for task in changed.tasks if task.task_id == "t6_analyse")
    assert params["measures"] == ["exam_score"]
    assert params["dimensions"] == ["gender"]


def test_the_rest_of_the_plan_is_left_exactly_as_it_was() -> None:
    catalogue = catalogue_for(students(), "mart://x.parquet")
    changed = apply_selection(
        small_plan(), Selection.from_params(["column:gender"]), catalogue, MANIFEST_DIR
    )
    assert changed.tasks[0] == small_plan().tasks[0]
    assert changed.tasks[1] == small_plan().tasks[1]


def test_the_task_keeps_the_parameters_the_selection_says_nothing_about() -> None:
    catalogue = catalogue_for(students(), "mart://x.parquet")
    changed = apply_selection(
        small_plan(), Selection.from_params(["column:gender"]), catalogue, MANIFEST_DIR
    )
    params = next(task.params for task in changed.tasks if task.task_id == "t6_analyse")
    assert params["question"] == "diem so ra sao"


def test_a_parameter_with_nothing_chosen_for_it_is_written_empty_not_omitted() -> None:
    # Omitting it would let the task fall back to its old behaviour, and the
    # fallback for "which columns to measure" is all of them - so narrowing the
    # selection would silently widen the analysis.
    catalogue = catalogue_for(students(), "mart://x.parquet")
    changed = apply_selection(
        small_plan(), Selection.from_params(["column:gender"]), catalogue, MANIFEST_DIR
    )
    params = next(task.params for task in changed.tasks if task.task_id == "t6_analyse")
    assert params["measures"] == []


def test_choosing_nothing_returns_the_plan_untouched() -> None:
    catalogue = catalogue_for(students(), "mart://x.parquet")
    assert apply_selection(small_plan(), Selection(), catalogue, MANIFEST_DIR) == small_plan()


def test_a_selection_no_task_can_use_is_refused_rather_than_ignored() -> None:
    # It would change nothing, and a person would be waiting for a different
    # answer that was never going to come.
    catalogue = catalogue_for(log(), "clean://log.parquet", activity="activity")
    with pytest.raises(FeatureError, match="khong doi gi"):
        apply_selection(
            small_plan(), Selection.from_params(["activity:Duyet"]), catalogue, MANIFEST_DIR
        )


def test_it_says_which_tasks_a_choice_would_change_before_anything_runs() -> None:
    catalogue = catalogue_for(students(), "mart://x.parquet")
    touched = affected_tasks(
        small_plan(), Selection.from_params(["column:gender"]), catalogue, MANIFEST_DIR
    )
    assert touched == ("t6_analyse",)


def test_an_agent_declares_its_own_feature_parameters_in_its_manifest() -> None:
    # Not a table in the Manager. Gates used to name agents directly and adding
    # an agent meant editing the Manager; that is not worth repeating.
    def bindings(agent_id: str) -> tuple[str, ...]:
        manifest = load_manifest(agent_id, MANIFEST_DIR)
        return tuple(binding.param for binding in manifest.consumes_features)

    assert bindings("a7_analyst") == ("dimensions", "measures")
    assert bindings("a6_process_miner") == ("keep_activities",)
    assert bindings("a1_ingest") == ()


def test_choosing_activities_reaches_the_miner_and_not_the_analyst() -> None:
    # The abstraction earning its keep: the same mechanism routes a kind of
    # feature that is not a column at all.
    plan = Plan(
        tasks=(
            PlannedTask(task_id="t_mine", agent_id="a6_process_miner"),
            PlannedTask(task_id="t_analyse", agent_id="a7_analyst", depends_on=("t_mine",)),
        ),
        reason="ke hoach quy trinh",
    )
    catalogue = catalogue_for(log(), "clean://log.parquet", activity="activity")
    changed = apply_selection(
        plan, Selection.from_params(["activity:Duyet"]), catalogue, MANIFEST_DIR
    )
    mine = next(task for task in changed.tasks if task.task_id == "t_mine")
    analyse = next(task for task in changed.tasks if task.task_id == "t_analyse")
    assert mine.params["keep_activities"] == ["Duyet"]
    assert analyse.params == {}
