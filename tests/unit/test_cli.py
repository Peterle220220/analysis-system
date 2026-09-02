"""Tests for the command line surface, including how it fails."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest
import yaml
from typer.testing import CliRunner

from analysis_system.cli import (
    BPI_DOWNLOAD_URL,
    CONFIG_ENV_VAR,
    _build_budget,
    app,
)
from analysis_system.services import storage
from analysis_system.services.budget import BudgetExceeded
from analysis_system.settings import LAYER_NAMES, Settings, load_settings

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "bpi19_slice.csv"

runner = CliRunner()


@pytest.fixture
def config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Write a settings file whose layers live in a throwaway directory."""
    layers: dict[str, str] = {}
    for name in LAYER_NAMES:
        directory = tmp_path / name
        directory.mkdir(parents=True)
        layers[name] = str(directory)
    config = {
        "layers": layers,
        "cleaning": {
            "assume_timezone": "UTC",
            "datetime_columns": ["timestamp"],
            "numeric_columns": ["event_seq", "cumulative_net_worth_eur"],
            "required_columns": ["case_id", "activity", "timestamp"],
        },
        "validation": {
            "max_rows_dropped_pct": 5.0,
            "not_null_columns": ["case_id", "event_seq", "activity", "timestamp"],
            "unique_together": [["case_id", "event_seq"]],
        },
    }
    path = tmp_path / "settings.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    monkeypatch.setenv(CONFIG_ENV_VAR, str(path))
    return path


@pytest.mark.usefixtures("config_file")
def test_check_config_accepts_a_valid_configuration() -> None:
    result = runner.invoke(app, ["check-config"])
    assert result.exit_code == 0, result.output
    assert "hop le" in result.output


def test_check_config_refuses_a_missing_layer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = {
        "layers": dict.fromkeys(LAYER_NAMES, str(tmp_path / "khong-ton-tai")),
        "cleaning": {"assume_timezone": "UTC"},
        "validation": {"max_rows_dropped_pct": 5.0},
    }
    path = tmp_path / "settings.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    monkeypatch.setenv(CONFIG_ENV_VAR, str(path))

    result = runner.invoke(app, ["check-config"])
    assert result.exit_code == 1
    assert "khong ton tai" in result.output
    # A missing layer is a configuration error, never something to repair quietly.
    assert not (tmp_path / "khong-ton-tai").exists()


@pytest.mark.usefixtures("config_file")
def test_setup_refuses_to_download_and_prints_the_link() -> None:
    result = runner.invoke(app, ["setup"])
    assert result.exit_code == 1
    assert "khong tu tai" in result.output.lower()
    assert BPI_DOWNLOAD_URL.split("//")[1][:20] in result.output.replace("\n", "")


@pytest.mark.usefixtures("config_file")
def test_run_reports_a_missing_input_file(tmp_path: Path) -> None:
    result = runner.invoke(app, ["run", "--input", str(tmp_path / "khong-co.csv")])
    assert result.exit_code == 1
    assert "Khong tim thay file dau vao" in result.output


@pytest.mark.usefixtures("config_file")
def test_run_processes_the_fixture_end_to_end(tmp_path: Path) -> None:
    result = runner.invoke(app, ["run", "--input", str(FIXTURE), "--run-id", "r_cli"])
    assert result.exit_code == 0, result.output
    assert "PASS" in result.output
    assert (tmp_path / "artifacts" / "pipeline_report.md").is_file()
    assert (tmp_path / "staging" / "events.parquet").is_file()
    assert (tmp_path / "clean" / "events.parquet").is_file()


# --- Phase 2 commands ----------------------------------------------------------


@pytest.fixture
def no_model(config_file: Path) -> Path:
    """The same configuration, with no model behind it.

    These tests are about the command surface. A run that stops to hand a prompt
    to a person is the handoff provider working correctly, and it would tell us
    nothing about the commands.
    """
    config = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    config["llm"] = {"provider": "none"}
    config_file.write_text(yaml.safe_dump(config), encoding="utf-8")
    return config_file


GOOD_PLAN = """{
  "tasks": [
    {"task_id": "t1", "agent_id": "a1_ingest",
     "params": {"target": "staging://x.parquet"}},
    {"task_id": "t2", "agent_id": "a2_profiler", "depends_on": ["t1"]}
  ],
  "reason": "ke hoach thu"
}"""

BAD_PLAN = """{"tasks": [{"task_id": "t1", "agent_id": "a99_khong_co"}]}"""


@pytest.mark.usefixtures("no_model")
def test_plan_prints_the_default_pipeline_when_there_is_no_model(tmp_path: Path) -> None:
    out = tmp_path / "plan.json"
    result = runner.invoke(
        app, ["plan", "gia nha the nao", "--source", "raw://x.csv", "--out", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert "t1_ingest" in result.output
    assert "khong dung model" in result.output
    assert out.is_file()


@pytest.mark.usefixtures("config_file")
def test_run_dag_refuses_a_plan_naming_an_agent_that_does_not_exist(tmp_path: Path) -> None:
    # A plan written by hand gets no more trust than one written by a model.
    plan = tmp_path / "bad.json"
    plan.write_text(BAD_PLAN, encoding="utf-8")
    source = tmp_path / "x.csv"
    source.write_text("a,b\n1,2\n", encoding="utf-8")

    result = runner.invoke(
        app, ["run-dag", "--input", str(source), "--plan", str(plan), "--run-id", "r_bad"]
    )
    assert result.exit_code == 1
    assert "khong ton tai" in result.output


@pytest.mark.usefixtures("config_file")
def test_run_dag_refuses_a_missing_input(tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    plan.write_text(GOOD_PLAN, encoding="utf-8")
    result = runner.invoke(
        app, ["run-dag", "--input", str(tmp_path / "khong-co.csv"), "--plan", str(plan)]
    )
    assert result.exit_code == 1
    assert "Khong tim thay file dau vao" in result.output


@pytest.mark.usefixtures("config_file")
def test_run_dag_refuses_an_unreadable_plan(tmp_path: Path) -> None:
    source = tmp_path / "x.csv"
    source.write_text("a,b\n1,2\n", encoding="utf-8")
    plan = tmp_path / "plan.json"
    plan.write_text("khong phai json", encoding="utf-8")

    result = runner.invoke(app, ["run-dag", "--input", str(source), "--plan", str(plan)])
    assert result.exit_code == 1
    assert "Khong doc duoc ke hoach" in result.output


@pytest.mark.usefixtures("no_model")
def test_run_dag_records_the_plan_it_is_executing(tmp_path: Path) -> None:
    # The plan is written into the run directory, which is what lets resume-dag
    # pick the run up later without being told again.
    plan = tmp_path / "plan.json"
    plan.write_text(GOOD_PLAN, encoding="utf-8")
    source = tmp_path / "x.csv"
    source.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")

    result = runner.invoke(
        app, ["run-dag", "--input", str(source), "--plan", str(plan), "--run-id", "r_cli"]
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "runs" / "r_cli" / "plan.json").is_file()
    assert "Hoan tat" in result.output


@pytest.mark.usefixtures("config_file")
def test_resume_dag_without_a_previous_run_says_what_to_do_instead() -> None:
    result = runner.invoke(app, ["resume-dag", "r_chua_co"])
    assert result.exit_code == 1
    assert "run-dag" in result.output


@pytest.mark.usefixtures("no_model")
def test_resume_dag_continues_a_run_it_already_started(tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    plan.write_text(GOOD_PLAN, encoding="utf-8")
    source = tmp_path / "x.csv"
    source.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    runner.invoke(
        app, ["run-dag", "--input", str(source), "--plan", str(plan), "--run-id", "r_again"]
    )

    result = runner.invoke(app, ["resume-dag", "r_again"])
    assert result.exit_code == 0, result.output
    assert "Hoan tat" in result.output


# --- cleaning and asking are two different acts ------------------------------------
#
# One run that loads, cleans, analyses and reports assumes the question is known
# before the data has been seen, which is backwards. A person cleans the data,
# looks at it, and only then knows what to ask - and then asks several things.


def csv_at(tmp_path: Path) -> Path:
    source = tmp_path / "diem.csv"
    source.write_text(
        "hoc_sinh,gioi_tinh,diem\n"
        + "".join(f"s{i},{'nam' if i % 2 else 'nu'},{50 + i}\n" for i in range(12)),
        encoding="utf-8",
    )
    return source


@pytest.mark.usefixtures("no_model")
def test_clean_stops_after_cleaning_and_does_not_analyse(tmp_path: Path) -> None:
    result = runner.invoke(app, ["clean", "--input", str(csv_at(tmp_path)), "--run-id", "r_c"])
    assert result.exit_code == 0, result.output
    plan = json.loads((tmp_path / "runs" / "r_c" / "plan.json").read_text(encoding="utf-8"))
    agents = {task["agent_id"] for task in plan["tasks"]}
    assert agents == {"a1_ingest", "a2_profiler", "a3_cleaner"}


@pytest.mark.usefixtures("config_file")
def test_clean_says_when_the_file_is_not_there(tmp_path: Path) -> None:
    result = runner.invoke(app, ["clean", "--input", str(tmp_path / "khong-co.csv")])
    assert result.exit_code == 1
    assert "Khong tim thay file" in result.output


@pytest.mark.usefixtures("no_model")
def test_asking_before_cleaning_says_what_to_do_first(tmp_path: Path) -> None:
    csv_at(tmp_path)
    result = runner.invoke(app, ["ask", "r_chua_sach", "diem the nao"])
    assert result.exit_code == 1
    assert "asys clean" in result.output


@pytest.mark.usefixtures("no_model")
def test_asking_without_a_model_says_so_rather_than_guessing(tmp_path: Path) -> None:
    # Planning from a question is the one thing here that needs a model. Falling
    # back to the fixed pipeline would answer a different question silently.
    runner.invoke(app, ["clean", "--input", str(csv_at(tmp_path)), "--run-id", "r_nm"])
    approve_clean(tmp_path, "r_nm")
    result = runner.invoke(app, ["ask", "r_nm", "diem the nao"])
    assert result.exit_code == 1
    assert "model" in result.output.lower()


def approve_clean(tmp_path: Path, run_id: str) -> None:
    """Answer the cleaning gate and let the run finish, as a person would."""
    gates = (tmp_path / "runs" / run_id / "gates").glob("*.json")
    for gate in gates:
        request = json.loads(gate.read_text(encoding="utf-8"))
        options = [option["option_id"] for option in request["options"]]
        args = ["approve", run_id, "--gate", request["gate_id"]]
        for option in options:
            args += ["--select", option]
        runner.invoke(app, args)
    runner.invoke(app, ["resume-dag", run_id])


@pytest.mark.usefixtures("no_model")
def test_the_clean_table_is_handed_back_with_what_to_do_next(tmp_path: Path) -> None:
    # The whole reason for stopping here is that somebody looks at the data. A
    # command that stops and says nothing has stopped for no reason - and this
    # summary was unreachable at first, because the gate always interrupts.
    runner.invoke(app, ["clean", "--input", str(csv_at(tmp_path)), "--run-id", "r_hand"])
    gate = next((tmp_path / "runs" / "r_hand" / "gates").glob("*.json"))
    request = json.loads(gate.read_text(encoding="utf-8"))
    args = ["approve", "r_hand", "--gate", request["gate_id"]]
    for option in request["options"]:
        args += ["--select", option["option_id"]]
    runner.invoke(app, args)

    result = runner.invoke(app, ["resume-dag", "r_hand"])
    assert result.exit_code == 0, result.output
    assert "Du lieu sach" in result.output
    assert "asys ask r_hand" in result.output


@pytest.mark.usefixtures("no_model")
def test_a_run_that_went_on_to_analyse_does_not_hand_back_a_table(tmp_path: Path) -> None:
    # There the clean table is a step along the way, not the thing being given.
    plan = tmp_path / "plan.json"
    plan.write_text(GOOD_PLAN, encoding="utf-8")
    source = tmp_path / "x.csv"
    source.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    result = runner.invoke(
        app, ["run-dag", "--input", str(source), "--plan", str(plan), "--run-id", "r_full"]
    )
    assert "Du lieu sach" not in result.output


# --- choosing what to analyse ----------------------------------------------------

SELECT_PLAN = """{
  "tasks": [
    {"task_id": "t1", "agent_id": "a1_ingest",
     "params": {"target": "staging://x.parquet"}},
    {"task_id": "t2", "agent_id": "a2_profiler", "depends_on": ["t1"]},
    {"task_id": "t6", "agent_id": "a7_analyst", "depends_on": ["t2"],
     "inputs_from": ["t1"], "params": {"question": "cau hoi"}}
  ],
  "reason": "ke hoach de chon dac trung"
}"""


def started_run(tmp_path: Path, run_id: str) -> Path:
    """A run that has produced at least one table, so there is something to choose."""
    plan = tmp_path / "plan.json"
    plan.write_text(SELECT_PLAN, encoding="utf-8")
    source = tmp_path / "diem.csv"
    source.write_text(
        "hoc_sinh,gioi_tinh,diem\n"
        + "".join(f"s{i},{'nam' if i % 2 else 'nu'},{50 + i}\n" for i in range(10)),
        encoding="utf-8",
    )
    runner.invoke(app, ["run-dag", "--input", str(source), "--plan", str(plan), "--run-id", run_id])
    return tmp_path / "runs" / run_id


@pytest.mark.usefixtures("no_model")
def test_features_lists_what_can_be_chosen(tmp_path: Path) -> None:
    started_run(tmp_path, "r_feat")
    result = runner.invoke(app, ["features", "r_feat"])
    assert result.exit_code == 0, result.output
    assert "column:diem" in result.output
    assert "column:gioi_tinh" in result.output


@pytest.mark.usefixtures("no_model")
def test_features_says_when_nothing_has_been_chosen_yet(tmp_path: Path) -> None:
    # "Everything" and "nothing" are different states and a person needs to know
    # which one they are in before they start narrowing.
    started_run(tmp_path, "r_feat2")
    result = runner.invoke(app, ["features", "r_feat2"])
    assert "Chua chon gi" in result.output


@pytest.mark.usefixtures("no_model")
def test_features_can_show_one_kind_at_a_time(tmp_path: Path) -> None:
    started_run(tmp_path, "r_feat3")
    result = runner.invoke(app, ["features", "r_feat3", "--kind", "activity"])
    assert result.exit_code == 0, result.output
    assert "Khong co dac trung" in result.output


@pytest.mark.usefixtures("config_file")
def test_features_on_a_run_that_does_not_exist_says_what_to_do() -> None:
    result = runner.invoke(app, ["features", "r_chua_co"])
    assert result.exit_code == 1
    assert "run-dag" in result.output


@pytest.mark.usefixtures("no_model")
def test_select_records_the_choice_and_names_what_will_be_redone(tmp_path: Path) -> None:
    run_dir = started_run(tmp_path, "r_sel")
    result = runner.invoke(
        app, ["select", "r_sel", "--feature", "column:diem", "--feature", "column:gioi_tinh"]
    )
    assert result.exit_code == 0, result.output
    assert "t6" in result.output
    assert (run_dir / "selection.json").is_file()


@pytest.mark.usefixtures("no_model")
def test_select_writes_the_choice_into_the_plan(tmp_path: Path) -> None:
    run_dir = started_run(tmp_path, "r_sel2")
    runner.invoke(app, ["select", "r_sel2", "--feature", "column:diem"])
    plan = (run_dir / "plan.json").read_text(encoding="utf-8")
    assert "measures" in plan
    assert "diem" in plan


@pytest.mark.usefixtures("no_model")
def test_select_runs_nothing_by_itself(tmp_path: Path) -> None:
    # Look, then act - the same two steps as a human gate, and for the same
    # reason: the choice is a file rather than a moment.
    started_run(tmp_path, "r_sel3")
    result = runner.invoke(app, ["select", "r_sel3", "--feature", "column:diem"])
    assert "resume-dag" in result.output
    assert "Hoan tat" not in result.output


@pytest.mark.usefixtures("no_model")
def test_select_refuses_a_feature_the_data_does_not_have(tmp_path: Path) -> None:
    started_run(tmp_path, "r_sel4")
    result = runner.invoke(app, ["select", "r_sel4", "--feature", "column:diem_sai_ten"])
    assert result.exit_code == 1
    assert "diem_sai_ten" in result.output


@pytest.mark.usefixtures("no_model")
def test_clearing_a_choice_goes_back_to_analysing_everything(tmp_path: Path) -> None:
    # L43, found by running the command rather than by a test: clearing used to
    # empty the selection file and leave the plan narrowed, so "analyse
    # everything" quietly went on analysing what it had before - and the state
    # agreed that nothing was selected.
    run_dir = started_run(tmp_path, "r_sel5")
    before = (run_dir / "plan.json").read_text(encoding="utf-8")

    runner.invoke(app, ["select", "r_sel5", "--feature", "column:diem"])
    assert "measures" in (run_dir / "plan.json").read_text(encoding="utf-8")

    result = runner.invoke(app, ["select", "r_sel5", "--clear"])
    assert result.exit_code == 0, result.output
    assert (run_dir / "selection.json").read_text(encoding="utf-8").strip() == "[]"
    assert (run_dir / "plan.json").read_text(encoding="utf-8") == before


@pytest.mark.usefixtures("no_model")
def test_a_second_choice_replaces_the_first_rather_than_adding_to_it(tmp_path: Path) -> None:
    # Otherwise narrowing twice would widen: the columns from the first choice
    # would still be sitting in the plan when the second was applied.
    run_dir = started_run(tmp_path, "r_sel7")
    runner.invoke(app, ["select", "r_sel7", "--feature", "column:diem"])
    runner.invoke(app, ["select", "r_sel7", "--feature", "column:gioi_tinh"])
    plan = (run_dir / "plan.json").read_text(encoding="utf-8")
    assert "gioi_tinh" in plan
    assert '"measures": []' in plan


@pytest.mark.usefixtures("no_model")
def test_the_plan_before_any_choosing_is_kept(tmp_path: Path) -> None:
    # Working out afterwards which parameters came from a selection and which
    # the planner set itself would be a guess, wrong whenever the planner had
    # opinions about columns - and wrong invisibly.
    run_dir = started_run(tmp_path, "r_sel8")
    assert not (run_dir / "plan.base.json").is_file()
    runner.invoke(app, ["select", "r_sel8", "--feature", "column:diem"])
    assert (run_dir / "plan.base.json").is_file()


@pytest.mark.usefixtures("no_model")
def test_features_marks_the_choice_after_it_was_made(tmp_path: Path) -> None:
    started_run(tmp_path, "r_sel6")
    runner.invoke(app, ["select", "r_sel6", "--feature", "column:diem"])
    result = runner.invoke(app, ["features", "r_sel6"])
    assert "[x] column:diem" in result.output
    assert "[ ] column:gioi_tinh" in result.output


# --- the ceiling a paid run must not cross -------------------------------------


def settings_of(config_path: Path, provider: str) -> Settings:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["llm"] = {**config.get("llm", {}), "provider": provider}
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return load_settings(config_path)


@pytest.mark.parametrize("provider", ["none", "cassette", "handoff"])
def test_a_provider_that_reaches_no_endpoint_needs_no_ceiling(
    config_file: Path, provider: str
) -> None:
    assert _build_budget(settings_of(config_file, provider), NOW) is None


@pytest.mark.parametrize("provider", ["gemini", "anthropic"])
def test_every_provider_that_calls_out_gets_a_ceiling(config_file: Path, provider: str) -> None:
    # Not only the billed one: token and wall-clock ceilings are worth having
    # whatever the price, and a free tier can still run away with an afternoon.
    budget = _build_budget(settings_of(config_file, provider), NOW)
    assert budget is not None
    assert budget.tokens_total == 0


def test_the_ceiling_comes_from_beside_the_settings_file_when_there_is_one(
    config_file: Path, tmp_path: Path
) -> None:
    # So pointing the CLI at a second environment moves its ceilings with it.
    (tmp_path / "budget.yaml").write_text(
        yaml.safe_dump(
            {
                "per_job": {"max_tokens": 10, "max_cost_usd": 0.01, "max_wallclock_min": 1},
                "per_agent_call": {"max_tokens": 5, "max_retries": 1},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "pricing.yaml").write_text(
        yaml.safe_dump({"last_verified": "2026-08-30", "models": {"m": {"input": 1, "output": 1}}}),
        encoding="utf-8",
    )
    budget = _build_budget(settings_of(config_file, "gemini"), NOW)
    assert budget is not None
    with pytest.raises(BudgetExceeded, match="vuot tran moi lan goi"):
        budget.record_call("m", tokens_in=9, tokens_out=9)


def test_a_stale_price_table_is_called_out(
    config_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Reporting a cost from prices nobody has checked in years is worse than
    # reporting none, so the run says so before it starts counting.
    (tmp_path / "budget.yaml").write_text(
        yaml.safe_dump(
            {
                "per_job": {"max_tokens": 100, "max_cost_usd": 1.0, "max_wallclock_min": 1},
                "per_agent_call": {"max_tokens": 50, "max_retries": 1},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "pricing.yaml").write_text(
        yaml.safe_dump({"last_verified": "2020-01-01", "models": {"m": {"input": 1, "output": 1}}}),
        encoding="utf-8",
    )
    _build_budget(settings_of(config_file, "gemini"), NOW)
    assert "qua han kiem chung" in capsys.readouterr().out


@pytest.mark.usefixtures("no_model")
def test_a_run_with_no_model_reports_no_spend(tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    plan.write_text(GOOD_PLAN, encoding="utf-8")
    source = tmp_path / "x.csv"
    source.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")

    result = runner.invoke(
        app, ["run-dag", "--input", str(source), "--plan", str(plan), "--run-id", "r_free"]
    )
    assert result.exit_code == 0, result.output
    assert "token" not in result.output  # nothing was counted, so nothing is claimed


# --- looking at what a run produced --------------------------------------------


@pytest.mark.usefixtures("config_file")
def test_export_writes_a_csv_a_person_can_open(tmp_path: Path) -> None:
    # Every layer holds Parquet, which is right for the pipeline and useless to
    # a spreadsheet.
    frame = pd.DataFrame({"a": ["1", "2"], "b": ["x", "y"]})
    storage.write_parquet(frame, tmp_path / "clean" / "events.parquet")
    out = tmp_path / "ra.csv"

    result = runner.invoke(app, ["export", "clean://events.parquet", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert out.read_text(encoding="utf-8").splitlines()[0] == "a,b"
    assert "2 dong x 2 cot" in result.output


@pytest.mark.usefixtures("config_file")
def test_export_without_a_destination_just_shows_it(tmp_path: Path) -> None:
    storage.write_parquet(pd.DataFrame({"a": ["1"]}), tmp_path / "mart" / "t.parquet")
    result = runner.invoke(app, ["export", "mart://t.parquet"])
    assert result.exit_code == 0, result.output
    assert "1 dong x 1 cot" in result.output


@pytest.mark.usefixtures("config_file")
def test_export_refuses_a_uri_that_names_nothing() -> None:
    result = runner.invoke(app, ["export", "clean://khong-co.parquet"])
    assert result.exit_code == 1
    assert "Khong tim thay" in result.output


@pytest.mark.usefixtures("config_file")
def test_export_cannot_reach_outside_a_layer() -> None:
    # The layer scheme is the boundary here too, not only for agents.
    result = runner.invoke(app, ["export", "clean://../../etc/passwd"])
    assert result.exit_code == 1


# --- the raw layer is the one thing nothing writes to --------------------------


@pytest.mark.usefixtures("no_model")
def test_a_source_already_in_the_raw_layer_is_used_where_it_lies(tmp_path: Path) -> None:
    # Under Docker the raw layer is mounted read-only, and every run used to
    # begin by copying its own input into it.
    plan = tmp_path / "plan.json"
    plan.write_text(GOOD_PLAN, encoding="utf-8")
    source = tmp_path / "raw" / "students.csv"
    source.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")

    result = runner.invoke(
        app, ["run-dag", "--input", str(source), "--plan", str(plan), "--run-id", "r_inplace"]
    )
    assert result.exit_code == 0, result.output
    assert "raw://students.csv" in result.output
    assert list((tmp_path / "raw").iterdir()) == [source]  # nothing was added


@pytest.mark.usefixtures("no_model")
def test_a_source_outside_the_layer_is_brought_in(tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    plan.write_text(GOOD_PLAN, encoding="utf-8")
    outside = tmp_path / "somewhere" / "students.csv"
    outside.parent.mkdir()
    outside.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")

    result = runner.invoke(
        app, ["run-dag", "--input", str(outside), "--plan", str(plan), "--run-id", "r_copy"]
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "raw" / "r_copy_students.csv").is_file()


@pytest.mark.usefixtures("no_model")
def test_a_read_only_raw_layer_says_what_to_do_about_it(tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    plan.write_text(GOOD_PLAN, encoding="utf-8")
    outside = tmp_path / "somewhere" / "students.csv"
    outside.parent.mkdir()
    outside.write_text("a,b\n1,2\n", encoding="utf-8")
    (tmp_path / "raw").chmod(0o555)
    try:
        result = runner.invoke(
            app, ["run-dag", "--input", str(outside), "--plan", str(plan), "--run-id", "r_ro"]
        )
        assert result.exit_code == 1
        assert "chi doc" in result.output
    finally:
        (tmp_path / "raw").chmod(0o755)


@pytest.mark.usefixtures("config_file")
def test_export_into_a_place_it_cannot_write_says_so_plainly(tmp_path: Path) -> None:
    # Inside the container the raw layer is mounted read-only, and pointing an
    # export at it produced forty lines of pandas internals ending in Errno 30.
    storage.write_parquet(pd.DataFrame({"a": ["1"]}), tmp_path / "mart" / "t.parquet")
    locked = tmp_path / "khoa"
    locked.mkdir()
    locked.chmod(0o555)
    try:
        result = runner.invoke(app, ["export", "mart://t.parquet", "--out", str(locked / "ra.csv")])
        assert result.exit_code == 1
        assert "Khong ghi duoc ra" in result.output
        assert "CHI DOC theo thiet ke" in result.output
    finally:
        locked.chmod(0o755)
