"""A6: code measures the process, the model is only allowed to name it.

The measurements themselves are covered in test_process_mining.py. What is
tested here is the boundary A6 adds on top: the model gets no figures, and every
name it sends back is checked before it is kept.

The digit rule needs both directions, and the second one is the one that bites.
Banning every digit is easy and wrong: a real process has a step called
"SRM: 5 Cho duyet", and a model that may not write that cannot name the step at
all. That exact over-correction already happened once in this project, on the
study dataset, and it made an analysis avoid the dimension it was asked about.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from analysis_system.agents.a6_process_miner import (
    MAX_LABEL_CHARS,
    MAX_NOTE_CHARS,
    ProcessMinerAgent,
    build_naming_request,
    check_labels,
)
from analysis_system.contracts.agents import ProcessInterpretation, ProcessMap
from analysis_system.contracts.base import DataRef, ScopeToken, TaskRequest, TaskResult
from analysis_system.core import storage
from analysis_system.core.boundary import BoundaryViolation, load_manifest
from analysis_system.core.hashing import canonical_hash
from analysis_system.core.scoped_storage import ScopedStorage
from analysis_system.core.settings import (
    LAYER_NAMES,
    LayerPaths,
    Settings,
    load_settings,
    resolve,
)
from analysis_system.services.process_mining import MIN_CASES, EventLogSpec, mine_process

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
MANIFEST_DIR = Path(__file__).resolve().parents[2] / "config" / "manifests"

# One of these carries a digit in its own name, which is the point.
ACTIVITIES = ("Tao don", "SRM: 5 Cho duyet", "Duyet don")

EVENT_LOG_PARAMS: dict[str, Any] = {
    "event_log": {
        "case_id": "case_id",
        "activity": "activity",
        "timestamp": "timestamp",
        "resource": "resource",
    }
}

SPEC = EventLogSpec(
    case_id="case_id", activity="activity", timestamp="timestamp", resource="resource"
)


def settings_in(root: Path) -> Settings:
    """Every layer under a throwaway directory."""
    roots = {name: root / name for name in LAYER_NAMES}
    for path in roots.values():
        path.mkdir(parents=True, exist_ok=True)
    return load_settings().model_copy(update={"layers": LayerPaths(**roots)})


def token(params: dict[str, Any] | None = None) -> ScopeToken:
    """A token matching the shipped a6_process_miner manifest.

    Written out rather than cut from the manifest on purpose: a token cut from
    the manifest agrees with it even when the manifest is the thing that is
    wrong, and some of these tests are about the manifest.
    """
    return ScopeToken(
        run_id="r_mine",
        task_id="t_mine",
        agent_id="a6_process_miner",
        allow_read=("clean://**", "mart://**", "staging://**"),
        allow_write=("artifacts://**",),
        allow_tools=("pandas",),
        params=params or {},
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
    )


def stage(settings: Settings, frame: pd.DataFrame) -> DataRef:
    """Put a log where A6 can read it, without borrowing A6's permissions.

    The fixture is not an agent. Writing the input through the agent's own scope
    would need A6 to be allowed to write into clean://, which is the one thing
    its manifest is there to prevent.
    """
    storage.write_parquet(frame, resolve("clean://log.parquet", settings))
    return DataRef(path="clean://log.parquet", format="parquet", content_hash=canonical_hash(frame))


def event_log(cases: int = 8) -> pd.DataFrame:
    """A log with enough cases to be measured, a day between steps."""
    return pd.DataFrame(
        [
            {
                "case_id": f"c{index}",
                "activity": step,
                "timestamp": f"2026-01-0{position + 1}T00:00:00Z",
                "resource": f"u{index % 3}",
            }
            for index in range(cases)
            for position, step in enumerate(ACTIVITIES)
        ]
    )


# --- the digit rule, both ways ---------------------------------------------------


def test_a_label_that_states_a_figure_is_dropped() -> None:
    kept, rejected = check_labels({"1": "Luong chiem 62% so case"}, ACTIVITIES)
    assert kept == {}
    assert rejected and "62" in rejected[0]


def test_a_label_quoting_the_logs_own_step_name_survives_its_digits() -> None:
    # The over-correction this guards against has happened here before: ban the
    # digits inside the data's own labels and the model stops discussing that
    # dimension at all, which reads as the model being useless.
    kept, _ = check_labels({"1": "Dung o SRM: 5 Cho duyet"}, ACTIVITIES)
    assert kept == {"1": "Dung o SRM: 5 Cho duyet"}


def test_a_name_long_enough_to_be_a_conclusion_is_dropped() -> None:
    kept, rejected = check_labels({"1": "x" * (MAX_LABEL_CHARS + 1)}, ACTIVITIES)
    assert kept == {}
    assert "ket luan" in rejected[0]


def test_an_observation_is_allowed_the_room_a_sentence_needs() -> None:
    # Found on a real log: three of every four observations the model wrote were
    # thrown away for being longer than a *name* may be. A name is short or it
    # is not a name; a note about what was measured is a sentence.
    note = "x" * (MAX_LABEL_CHARS + 20)
    assert check_labels({"0": note}, ACTIVITIES)[0] == {}
    assert check_labels({"0": note}, ACTIVITIES, limit=MAX_NOTE_CHARS)[0] == {"0": note}


def test_an_observation_still_may_not_state_a_figure() -> None:
    # The longer limit relaxes length, not the rule that matters.
    kept, rejected = check_labels(
        {"0": "Co 62 phan tram so case di theo luong nay"}, ACTIVITIES, limit=MAX_NOTE_CHARS
    )
    assert kept == {}
    assert rejected


def test_observations_from_the_model_survive_into_the_map(tmp_path: Path) -> None:
    note = "Mot so case dung lai ngay sau buoc dau tien ma khong di tiep den cac buoc sau do."
    llm = Naming(ProcessInterpretation(concerns=(note,)))
    found = written_map(*run_agent(tmp_path, llm))
    assert note in found.concerns


def test_an_empty_label_is_ignored_rather_than_reported() -> None:
    # Nothing was claimed, so there is nothing to reject and nothing to keep.
    kept, rejected = check_labels({"1": "   "}, ACTIVITIES)
    assert kept == {}
    assert rejected == []


def test_a_plain_name_is_kept_untouched() -> None:
    kept, rejected = check_labels({"1": "Luong chuan"}, ACTIVITIES)
    assert kept == {"1": "Luong chuan"}
    assert rejected == []


# --- what the model is shown ------------------------------------------------------


def test_the_model_is_shown_paths_and_no_numbers_at_all() -> None:
    # A number in front of the model is a number it can copy into a label. The
    # figures stay behind keys; only the names travel.
    outcome = mine_process(event_log(), SPEC)
    payload = json.loads(build_naming_request(outcome, "quy trinh chay the nao").prompt)

    assert set(payload) == {"question", "paths", "declined", "rules"}
    for entry in payload["paths"]:
        for name, value in entry.items():
            if name.endswith("_key"):
                assert value in outcome.metrics
            else:
                assert not isinstance(value, float)


def test_every_key_the_model_is_given_resolves_to_a_real_metric() -> None:
    # Handing over a key with nothing behind it would make a placeholder that
    # can never be substituted, and the claim would be thrown out for it.
    outcome = mine_process(event_log(), SPEC)
    payload = json.loads(build_naming_request(outcome, "cau hoi").prompt)
    keys = [
        value
        for entry in payload["paths"]
        for name, value in entry.items()
        if name.endswith("_key")
    ]
    assert keys
    assert all(key in outcome.metrics for key in keys)


def test_what_mining_declined_is_shown_to_the_model_too() -> None:
    # Otherwise it names a process it believes was fully measured.
    frame = event_log().drop(columns=["resource"])
    outcome = mine_process(
        frame, EventLogSpec(case_id="case_id", activity="activity", timestamp="timestamp")
    )
    payload = json.loads(build_naming_request(outcome, "cau hoi").prompt)
    assert payload["declined"]


# --- the agent end to end ----------------------------------------------------------


class Naming:
    """A model that answers with whatever it was told to answer."""

    def __init__(self, answer: ProcessInterpretation) -> None:
        self._answer = answer
        self.asked = 0

    def complete(self, _request: object) -> object:
        self.asked += 1
        return type("Reply", (), {"data": self._answer})()


def run_agent(
    tmp_path: Path, llm: object | None, frame: pd.DataFrame | None = None
) -> tuple[TaskResult, Settings]:
    """Mine one log through the real agent and hand back what it wrote."""
    settings = settings_in(tmp_path)
    scope = token(EVENT_LOG_PARAMS)
    files = ScopedStorage(scope, settings)
    source = stage(settings, frame if frame is not None else event_log())
    agent = ProcessMinerAgent(settings, MANIFEST_DIR, llm=llm)  # type: ignore[arg-type]
    result = agent.execute(
        TaskRequest(scope=scope, input_refs=(source,), instruction="Khai thac quy trinh."), files
    )
    return result, settings


def written_map(result: TaskResult, settings: Settings) -> ProcessMap:
    """The map the agent wrote, read straight off disk.

    Not through A6's scope: A6 may write artifacts:// and may not read it, which
    is correct - it has no reason to read its own output back. The fixture is
    not an agent and should not borrow an agent's permissions to look.
    """
    return ProcessMap.model_validate_json(
        resolve(result.output_refs[0].path, settings).read_text(encoding="utf-8")
    )


def test_it_writes_a_map_without_any_model_at_all(tmp_path: Path) -> None:
    # Names are the only optional part, which is what makes it safe to ask a
    # model for them. Every measurement is already made without one.
    result, settings = run_agent(tmp_path, None)
    assert result.status == "OK"
    found = written_map(result, settings)
    assert found.metrics
    assert found.variants
    assert all(variant.label == "" for variant in found.variants)


def test_a_label_the_model_supplied_lands_on_its_variant(tmp_path: Path) -> None:
    llm = Naming(ProcessInterpretation(variant_labels={"1": "Luong chuan"}))
    result, settings = run_agent(tmp_path, llm)
    assert written_map(result, settings).variants[0].label == "Luong chuan"


def test_a_label_with_an_invented_figure_never_reaches_the_map(tmp_path: Path) -> None:
    llm = Naming(ProcessInterpretation(variant_labels={"1": "Luong chiem 87% so case"}))
    found = written_map(*run_agent(tmp_path, llm))
    assert found.variants[0].label == ""
    assert any("87" in reason for reason in found.refused)


def test_a_name_for_a_path_that_was_never_measured_is_refused(tmp_path: Path) -> None:
    # There is nothing behind it, so keeping it would put a name in the report
    # that corresponds to no measurement.
    llm = Naming(ProcessInterpretation(variant_labels={"99": "Luong ma"}))
    found = written_map(*run_agent(tmp_path, llm))
    assert all(variant.label == "" for variant in found.variants)
    assert any("khong co trong ket qua" in reason for reason in found.refused)


def test_every_metric_key_in_the_map_is_backed_by_a_metric(tmp_path: Path) -> None:
    found = written_map(*run_agent(tmp_path, None))
    keys = {metric.key for metric in found.metrics}
    for variant in found.variants:
        assert variant.share_key in keys
        assert variant.cases_key in keys
    for handover in found.handovers:
        assert handover.total_hours_key in keys
        assert handover.observations_key in keys
        # Empty when too few handovers were seen to claim a typical wait. Not a
        # missing key - the absence of a measurement, said out loud.
        if handover.median_hours_key:
            assert handover.median_hours_key in keys


def test_what_mining_declined_is_carried_into_the_map(tmp_path: Path) -> None:
    found = written_map(*run_agent(tmp_path, None, event_log(cases=3)))
    assert found.refused
    assert not found.variants  # too few cases to claim a share


def test_a_task_with_no_event_log_parameter_fails_rather_than_guessing(tmp_path: Path) -> None:
    settings = settings_in(tmp_path)
    scope = token()
    files = ScopedStorage(scope, settings)
    source = stage(settings, event_log())
    result = ProcessMinerAgent(settings, MANIFEST_DIR).execute(
        TaskRequest(scope=scope, input_refs=(source,), instruction=""), files
    )
    assert result.status == "FAILED"
    assert result.error is not None
    # Being handed the wrong columns is exactly what a different plan could fix.
    assert result.error.replannable


def test_no_input_is_a_failure_a_different_plan_could_fix(tmp_path: Path) -> None:
    settings = settings_in(tmp_path)
    scope = token()
    result = ProcessMinerAgent(settings, MANIFEST_DIR).execute(
        TaskRequest(scope=scope, input_refs=(), instruction=""), ScopedStorage(scope, settings)
    )
    assert result.status == "FAILED"
    assert result.error is not None
    assert result.error.code == "NO_INPUT"


def test_the_same_log_produces_the_same_map_twice(tmp_path: Path) -> None:
    # Criterion S1 reaches here too: a map that differed between runs would make
    # every process finding downstream irreproducible.
    first, settings_a = run_agent(tmp_path / "a", None)
    second, settings_b = run_agent(tmp_path / "b", None)
    assert resolve(first.output_refs[0].path, settings_a).read_text(encoding="utf-8") == resolve(
        second.output_refs[0].path, settings_b
    ).read_text(encoding="utf-8")


# --- only the activities somebody chose --------------------------------------------


def run_with_activities(tmp_path: Path, keep: list[str]) -> tuple[TaskResult, Settings]:
    """Mine the log with a chosen set of activities."""
    settings = settings_in(tmp_path)
    scope = token({**EVENT_LOG_PARAMS, "keep_activities": keep})
    files = ScopedStorage(scope, settings)
    source = stage(settings, event_log())
    result = ProcessMinerAgent(settings, MANIFEST_DIR).execute(
        TaskRequest(scope=scope, input_refs=(source,), instruction="Khai thac quy trinh."), files
    )
    return result, settings


def test_only_the_chosen_activities_are_mined(tmp_path: Path) -> None:
    found = written_map(*run_with_activities(tmp_path, ["Tao don", "Duyet don"]))
    assert found.metrics
    distinct = next(
        metric.value for metric in found.metrics if metric.key == "process.activities.distinct"
    )
    assert distinct == 2


def test_a_filtered_process_says_loudly_that_it_is_filtered(tmp_path: Path) -> None:
    # Every variant and waiting time afterwards describes a process nobody ran:
    # two cases differing only in a filtered step become the same variant. The
    # note travels with the numbers so a reader cannot see one without the other.
    found = written_map(*run_with_activities(tmp_path, ["Tao don", "Duyet don"]))
    assert any("CHI KHAI THAC" in reason for reason in found.refused)
    assert any("DA LOC" in reason for reason in found.refused)


def test_choosing_every_activity_is_the_same_as_choosing_none(tmp_path: Path) -> None:
    # Nothing was dropped, so there is nothing to warn about.
    found = written_map(*run_with_activities(tmp_path, list(ACTIVITIES)))
    assert not any("CHI KHAI THAC" in reason for reason in found.refused)


def test_choosing_activities_that_are_not_in_the_log_fails_rather_than_mining_nothing(
    tmp_path: Path,
) -> None:
    result, _ = run_with_activities(tmp_path, ["Hoat dong khong ton tai"])
    assert result.status == "FAILED"
    assert result.error is not None
    assert result.error.code == "EMPTY_AFTER_FILTER"


def test_a_different_choice_of_activities_gives_a_different_map(tmp_path: Path) -> None:
    # If it did not, the choice would be decoration.
    first = written_map(*run_with_activities(tmp_path / "a", ["Tao don", "Duyet don"]))
    second = written_map(*run_with_activities(tmp_path / "b", list(ACTIVITIES)))
    assert first.metrics != second.metrics


# --- comparing one part of the process against another -----------------------------


def channelled(cases: int = 40) -> pd.DataFrame:
    """A log where half the cases arrive by post and wait far longer at one step."""
    rows = []
    for index in range(cases):
        slow = index % 2 == 0
        start = pd.Timestamp("2026-01-01T00:00:00Z")
        channel = "Post" if slow else "Internet"
        rows.extend(
            [
                {
                    "case_id": f"c{index}",
                    "activity": "Tao don",
                    "timestamp": str(start),
                    "resource": "u1",
                    "channel": channel,
                },
                {
                    "case_id": f"c{index}",
                    "activity": "Duyet don",
                    "timestamp": str(start + pd.Timedelta(hours=1)),
                    "resource": "u2",
                    "channel": channel,
                },
                # Only the postal cases wait a long time before the last step.
                {
                    "case_id": f"c{index}",
                    "activity": "Gui ket qua",
                    "timestamp": str(start + pd.Timedelta(hours=101 if slow else 2)),
                    "resource": "u3",
                    "channel": channel,
                },
            ]
        )
    return pd.DataFrame(rows)


def mine_with(tmp_path: Path, params: dict[str, Any], frame: pd.DataFrame) -> ProcessMap:
    """Run A6 with extra parameters and hand back the map it wrote."""
    settings = settings_in(tmp_path)
    scope = token({**EVENT_LOG_PARAMS, **params})
    files = ScopedStorage(scope, settings)
    source = stage(settings, frame)
    result = ProcessMinerAgent(settings, MANIFEST_DIR).execute(
        TaskRequest(scope=scope, input_refs=(source,), instruction="Khai thac."), files
    )
    assert result.status == "OK", result.error
    return written_map(result, settings)


def test_it_reports_what_the_process_could_be_compared_by(tmp_path: Path) -> None:
    # Reported whether or not a comparison was asked for. A Manager that has to
    # guess which columns describe a case will delegate comparisons that cannot
    # be made; one that is told will ask for the ones that can.
    found = mine_with(tmp_path, {}, channelled())
    assert "channel" in {attribute.name for attribute in found.attributes}


def test_it_does_not_compare_anything_unasked(tmp_path: Path) -> None:
    # Choosing which groups to set against each other is a question about what
    # somebody wants to know. Picking one for them puts an answer in front of
    # them to a question they did not ask.
    assert mine_with(tmp_path, {}, channelled()).gap is None


def test_asked_to_compare_it_says_which_handover_holds_the_difference(
    tmp_path: Path,
) -> None:
    found = mine_with(
        tmp_path,
        {"compare": {"attribute": "channel", "focus": "Post", "against": "Internet"}},
        channelled(),
    )
    assert found.gap is not None
    assert found.gap.focus == "Post"
    assert found.gap.steps
    assert found.gap.steps[0].source_activity == "Duyet don"
    assert found.gap.steps[0].target_activity == "Gui ket qua"


def test_every_key_the_comparison_names_is_backed_by_a_metric(tmp_path: Path) -> None:
    found = mine_with(
        tmp_path,
        {"compare": {"attribute": "channel", "focus": "Post", "against": "Internet"}},
        channelled(),
    )
    keys = {metric.key for metric in found.metrics}
    assert found.gap is not None
    assert found.gap.total_key in keys
    for step in found.gap.steps:
        assert step.gap_key in keys
        assert step.share_key in keys


def test_comparing_by_a_column_that_is_not_there_is_declined_not_crashed(
    tmp_path: Path,
) -> None:
    found = mine_with(
        tmp_path,
        {"compare": {"attribute": "khong_ton_tai", "focus": "x"}},
        channelled(),
    )
    assert found.gap is None
    assert any("khong so sanh duoc" in reason for reason in found.refused)


def test_a_malformed_compare_instruction_is_ignored_rather_than_guessed(
    tmp_path: Path,
) -> None:
    # Half an instruction is not an instruction. Filling in the missing half
    # would be choosing the comparison on the asker's behalf.
    assert mine_with(tmp_path, {"compare": {"attribute": "channel"}}, channelled()).gap is None


# --- what a skill would not claim reaches whoever asked -----------------------------


def test_what_mining_declined_is_handed_up_with_the_result(tmp_path: Path) -> None:
    # Every skill knew its own refusals and kept them somewhere different, so
    # nothing above them could ask what had *not* been established.
    settings = settings_in(tmp_path)
    scope = token(EVENT_LOG_PARAMS)
    files = ScopedStorage(scope, settings)
    source = stage(settings, event_log(cases=3))
    result = ProcessMinerAgent(settings, MANIFEST_DIR).execute(
        TaskRequest(scope=scope, input_refs=(source,), instruction=""), files
    )
    assert result.declined
    assert any(str(MIN_CASES) in note for note in result.declined)


# --- the manifest says what the agent does -----------------------------------------


def test_the_manifest_forbids_a6_from_writing_anywhere_but_artifacts() -> None:
    manifest = load_manifest("a6_process_miner", MANIFEST_DIR)
    assert manifest.allow.write == ("artifacts://**",)
    assert "raw://**" not in manifest.allow.read


def test_the_manifest_asks_for_no_human_gate() -> None:
    # A6 concludes nothing. A gate here would be pressed by reflex, and a gate
    # pressed by reflex is not a gate.
    assert not load_manifest("a6_process_miner", MANIFEST_DIR).human_gate.required


@pytest.mark.parametrize("layer", ["raw://x.csv", "clean://x.parquet"])
def test_a6_cannot_write_into_a_layer_it_does_not_own(tmp_path: Path, layer: str) -> None:
    files = ScopedStorage(token(), settings_in(tmp_path))
    with pytest.raises(BoundaryViolation):
        files.save_text("{}", layer)
