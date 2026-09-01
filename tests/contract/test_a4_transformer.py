"""A4 tests: the model may write SQL, but only code decides whether it runs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from analysis_system.agents.a4_transformer import (
    TransformerAgent,
    build_sql_request,
    verify_lineage,
)
from analysis_system.contracts.agents import ColumnLineage, SqlProposal
from analysis_system.contracts.base import DataRef, ScopeToken, TaskRequest, TaskResult
from analysis_system.services import storage
from analysis_system.services.llm import LlmClient, LlmRequest, LlmResponse
from analysis_system.services.sql_guard import SqlGuardError
from analysis_system.services.sql_runner import (
    SqlRunError,
    describe_tables,
    run_query,
    table_name_for,
)
from analysis_system.settings import LAYER_NAMES, LayerPaths, Settings, load_settings, resolve

NOW = datetime(2026, 8, 31, 18, 0, tzinfo=UTC)
MANIFEST_DIR = Path(__file__).resolve().parents[2] / "config" / "manifests"


def events() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "case_id": ["c1", "c1", "c2", "c2"],
            "activity": ["Create", "Pay", "Create", "Pay"],
            "amount": [10.0, 20.0, 30.0, 40.0],
        }
    )


class FixedSql:
    """Answers with one prepared proposal, so the test is about the controls."""

    name = "test"

    def __init__(self, proposal: SqlProposal) -> None:
        self._proposal = proposal
        self.calls = 0

    def complete(self, request: LlmRequest) -> LlmResponse:
        self.calls += 1
        self.last = request
        return LlmResponse(data=self._proposal, provider=self.name, model="test")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    roots = {name: tmp_path / name for name in LAYER_NAMES}
    for root in roots.values():
        root.mkdir(parents=True, exist_ok=True)
    return load_settings().model_copy(update={"layers": LayerPaths(**roots)})


def token(params: dict[str, Any] | None = None) -> ScopeToken:
    return ScopeToken(
        run_id="r_tf",
        task_id="t_mart",
        agent_id="a4_transformer",
        allow_read=("clean://**", "profile://**"),
        allow_write=("mart://**",),
        allow_tools=("duckdb_readonly_query", "pandas"),
        params=params or {},
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
    )


def clean_table(settings: Settings, frame: pd.DataFrame, name: str = "events") -> DataRef:
    storage.write_parquet(frame, resolve(f"clean://{name}.parquet", settings))
    return DataRef(path=f"clean://{name}.parquet", format="parquet", content_hash="a" * 64)


def transform(
    settings: Settings,
    proposal: SqlProposal | None = None,
    *,
    params: dict[str, Any] | None = None,
    frame: pd.DataFrame | None = None,
) -> TaskResult:
    llm = LlmClient(FixedSql(proposal)) if proposal else None
    agent = TransformerAgent(settings, MANIFEST_DIR, llm=llm)
    ref = clean_table(settings, frame if frame is not None else events())
    request = TaskRequest(scope=token(params), input_refs=(ref,), instruction="tong hop theo case")
    return agent.run(request, now=NOW)


GOOD = SqlProposal(
    sql="SELECT case_id, sum(amount) AS total FROM events GROUP BY case_id",
    target_table="case_total",
    lineage=[
        ColumnLineage(output="case_id", sources=("events.case_id",), transform="giu nguyen"),
        ColumnLineage(output="total", sources=("events.amount",), transform="tong theo case"),
    ],
)


# --- running SQL --------------------------------------------------------------


def test_a_query_runs_and_returns_a_frame() -> None:
    outcome = run_query(
        "SELECT case_id, sum(amount) AS total FROM events GROUP BY case_id", {"events": events()}
    )
    assert outcome.rows_out == 2
    assert set(outcome.frame.columns) == {"case_id", "total"}
    assert outcome.rows_in == {"events": 4}


def test_the_guard_runs_before_the_database_sees_anything() -> None:
    with pytest.raises(SqlGuardError):
        run_query("DROP TABLE events", {"events": events()})


def test_a_result_larger_than_the_ceiling_is_refused() -> None:
    with pytest.raises(SqlRunError, match="vuot tran"):
        run_query("SELECT * FROM events", {"events": events()}, max_rows=2)


def test_a_join_that_explodes_is_reported_even_when_it_fits() -> None:
    # Under the hard ceiling, but far larger than any input: worth saying so.
    # Twenty rows joined to themselves give four hundred, twenty times the input.
    wide = pd.DataFrame({"case_id": [f"c{index}" for index in range(20)]})
    outcome = run_query(
        "SELECT a.case_id, b.case_id AS other FROM wide a JOIN wide b ON 1 = 1",
        {"wide": wide},
        max_rows=10_000,
    )
    assert outcome.rows_out == 400
    assert outcome.exploded
    assert "kiem lai dieu kien join" in outcome.note


def test_a_normal_aggregate_is_not_reported_as_an_explosion() -> None:
    outcome = run_query("SELECT case_id FROM events GROUP BY case_id", {"events": events()})
    assert not outcome.exploded
    assert outcome.note == ""


def test_a_broken_statement_reports_what_duckdb_said() -> None:
    with pytest.raises(SqlRunError, match="DuckDB tu choi"):
        run_query("SELECT khong_co_cot FROM events", {"events": events()})


def test_nothing_a_query_creates_survives_it(tmp_path: Path) -> None:
    # Each query gets its own in-memory database. A view made by one is gone by
    # the next, and the guard refuses to name it anyway - the two defences
    # overlap here on purpose.
    before = set(tmp_path.iterdir())
    run_query("CREATE VIEW v AS SELECT * FROM events", {"events": events()})
    with pytest.raises(SqlGuardError, match="khong duoc cap"):
        run_query("SELECT * FROM v", {"events": events()})
    assert set(tmp_path.iterdir()) == before, "khong duoc tao file nao tren dia"


def test_a_table_name_comes_from_the_reference() -> None:
    assert table_name_for("clean://events.parquet") == "events"
    assert table_name_for("mart://r1_case_total.parquet") == "r1_case_total"


def test_the_prompt_carries_schema_and_no_rows() -> None:
    described = describe_tables({"events": events()})
    events_shape: Any = described["events"]
    assert events_shape["rows"] == 4
    names = [column["name"] for column in events_shape["columns"]]
    assert names == ["case_id", "activity", "amount"]
    request = build_sql_request({"events": events()}, "tong theo case", 1000)
    assert "Create" not in request.prompt  # no data value reaches the model


# --- lineage ------------------------------------------------------------------


def test_a_lineage_naming_a_column_that_does_not_exist_is_caught() -> None:
    bad = SqlProposal(
        sql="SELECT case_id FROM events",
        target_table="x",
        lineage=[ColumnLineage(output="case_id", sources=("events.khong_co",))],
    )
    produced = pd.DataFrame({"case_id": ["c1"]})
    problems = verify_lineage(bad, {"events": events()}, produced)
    assert any("khong co trong bang dau vao" in problem for problem in problems)


def test_an_undeclared_output_column_is_caught() -> None:
    partial = SqlProposal(
        sql="SELECT case_id, activity FROM events",
        target_table="x",
        lineage=[ColumnLineage(output="case_id", sources=("events.case_id",))],
    )
    produced = pd.DataFrame({"case_id": ["c1"], "activity": ["Create"]})
    problems = verify_lineage(partial, {"events": events()}, produced)
    assert any("chua khai bao nguon goc" in problem for problem in problems)


def test_a_correct_lineage_produces_no_complaint() -> None:
    produced = pd.DataFrame({"case_id": ["c1"], "total": [30.0]})
    assert verify_lineage(GOOD, {"events": events()}, produced) == []


# --- the agent ----------------------------------------------------------------


def test_a_good_proposal_builds_the_mart(settings: Settings) -> None:
    result = transform(settings, GOOD)
    assert result.is_ok, result.error
    assert result.output_refs[0].path.startswith("mart://")
    assert result.payload["rows_out"] == 2
    assert len(result.payload["lineage"]) == 2
    assert result.payload["content_hash"]


def test_a_destructive_statement_never_reaches_the_database(settings: Settings) -> None:
    evil = SqlProposal(sql="DROP TABLE events", target_table="x", lineage=[])
    result = transform(settings, evil)
    assert result.status == "FAILED"
    assert result.error is not None
    assert result.error.code == "SQL_REFUSED"
    assert not list(settings.layers.mart.iterdir())


def test_a_statement_reading_an_ungranted_table_is_refused(settings: Settings) -> None:
    nosy = SqlProposal(sql="SELECT * FROM secrets", target_table="x", lineage=[])
    result = transform(settings, nosy)
    assert result.status == "FAILED"
    assert result.error.code == "SQL_REFUSED"  # type: ignore[union-attr]


def test_a_wrong_lineage_stops_the_write(settings: Settings) -> None:
    lying = SqlProposal(
        sql="SELECT case_id, sum(amount) AS total FROM events GROUP BY case_id",
        target_table="x",
        lineage=[ColumnLineage(output="case_id", sources=("events.bia_ra",))],
    )
    result = transform(settings, lying)
    assert result.status == "FAILED"
    assert result.error.code == "LINEAGE_INVALID"  # type: ignore[union-attr]
    assert not list(settings.layers.mart.iterdir())


def test_sql_can_be_supplied_by_the_task_instead_of_a_model(settings: Settings) -> None:
    # An approved statement needs no model at all.
    result = transform(
        settings,
        None,
        params={
            "sql": {
                "sql": "SELECT case_id FROM events",
                "target_table": "ids",
                "lineage": [{"output": "case_id", "sources": ["events.case_id"]}],
            }
        },
    )
    assert result.is_ok, result.error


def test_without_sql_or_a_model_it_says_so(settings: Settings) -> None:
    result = transform(settings, None)
    assert result.status == "FAILED"
    assert result.error.code == "NO_SQL"  # type: ignore[union-attr]


def test_it_cannot_write_back_into_clean(settings: Settings) -> None:
    result = transform(settings, GOOD, params={"target": "clean://ghi_de.parquet"})
    assert result.status == "BOUNDARY_VIOLATION"


def test_the_manifest_shows_the_model_no_rows(settings: Settings) -> None:
    agent = TransformerAgent(settings, MANIFEST_DIR)
    assert agent.manifest.allow.llm.max_sample_rows == 0
    assert "destructive_ddl" in agent.manifest.deny


# --- what the model is actually asked -------------------------------------------


def test_the_task_instruction_reaches_the_model() -> None:
    # It did not, and three times I read the result as the model ignoring an
    # instruction to name its output columns. The instruction was never sent;
    # the model answered the question it was actually asked, and answered it
    # sensibly.
    request = build_sql_request(
        {"events": events()},
        "gia theo thanh pho",
        1000,
        "Dat ten cot dau ra CHINH XAC la spend_area va net_worth.",
    )
    assert "spend_area" in request.prompt
    assert "net_worth" in request.prompt
    assert "Neu 'instruction' yeu cau ten cot cu the" in request.prompt


def test_a_first_attempt_carries_no_feedback_fields() -> None:
    plain = build_sql_request({"events": events()}, "cau hoi", 1000, "lam gi do")
    assert "rejected_because" not in plain.prompt


def test_the_statement_that_built_the_table_is_kept_beside_it(settings: Settings) -> None:
    # Without this nobody can answer "how was this table built?" once the run is
    # over - and it was the absence of exactly this record that let a dropped
    # instruction go unnoticed through three runs.
    result = transform(settings, GOOD)
    assert result.is_ok, result.error
    target = Path(result.payload["target"].split("://", 1)[1])
    recipe = settings.layers.mart / target.with_suffix(".sql")
    assert recipe.is_file()
    text = recipe.read_text(encoding="utf-8")
    assert "SELECT" in text
    assert "-- run: r_tf" in text
    assert "-- nguon: events" in text
