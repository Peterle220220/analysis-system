"""Tests for the command line surface, including how it fails."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from analysis_system.cli import (
    BPI_DOWNLOAD_URL,
    CONFIG_ENV_VAR,
    _build_budget,
    app,
)
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
