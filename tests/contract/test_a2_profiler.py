"""A2 tests: code measures, the model only comments, and facts always win."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from analysis_system.agents.a2_profiler import (
    ProfilerAgent,
    build_interpretation_request,
    count_outliers,
    guess_roles,
    looks_like_pii,
    merge_profile,
    numeric_view,
    profile_columns,
    profile_uri_for,
    top_values,
)
from analysis_system.core import storage
from analysis_system.core.settings import LAYER_NAMES, LayerPaths, Settings, load_settings, resolve
from analysis_system.domains.ai_planner.llm import CassetteProvider, LlmClient, LlmResponse
from analysis_system.domains.ai_planner.prompts import PromptError, load_prompt
from analysis_system.models.agents import (
    EventLogCandidates,
    ProfileInterpretation,
    ProposedRule,
)
from analysis_system.models.base import DataRef, ScopeToken, TaskRequest

NOW = datetime(2026, 8, 31, 10, 0, tzinfo=UTC)
MANIFEST_DIR = Path(__file__).resolve().parents[2] / "config" / "manifests"
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "bpi19_slice.csv"


def frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "case_id": ["c1", "c1", "c2", "c2"],
            "activity": ["Create", "Approve", "Create", "Pay"],
            "timestamp": ["2018-01-01T00:00:00Z"] * 4,
            "resource": ["user_1", "user_2", "user_1", None],
            "vendor_email": ["a@x.com", "b@x.com", "c@x.com", "d@x.com"],
            "amount": ["10", "20", "30", "40"],
        }
    )


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings with every layer under a throwaway directory."""
    roots = {name: tmp_path / name for name in LAYER_NAMES}
    for root in roots.values():
        root.mkdir(parents=True, exist_ok=True)
    return load_settings().model_copy(update={"layers": LayerPaths(**roots)})


def token() -> ScopeToken:
    """A token matching the shipped a2_profiler manifest."""
    return ScopeToken(
        run_id="r_1",
        task_id="t_02",
        agent_id="a2_profiler",
        allow_read=("staging://**",),
        allow_write=("profile://**",),
        allow_tools=("pandas", "profiling.describe"),
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )


# --- measurement --------------------------------------------------------------


def test_columns_are_measured_and_sorted_by_name() -> None:
    columns = profile_columns(frame())
    assert [column.name for column in columns] == [
        "activity",
        "amount",
        "case_id",
        "resource",
        "timestamp",
        "vendor_email",
    ]
    resource = next(column for column in columns if column.name == "resource")
    assert resource.non_null == 3
    assert resource.null_pct == 25.0
    assert resource.distinct == 2


def test_min_and_max_are_measured_on_numbers_not_on_text() -> None:
    # "9" sorts after "10" as text. A price column has to report 10 and 300.
    numbers = pd.Series(["300", "10", "9"])
    profile = profile_columns(pd.DataFrame({"price": numbers}))[0]
    assert profile.numeric_share == 1.0
    assert float(profile.min_value or 0) == 9.0
    assert float(profile.max_value or 0) == 300.0


def test_a_text_column_reports_text_bounds() -> None:
    profile = profile_columns(pd.DataFrame({"city": ["Seattle", "Bellevue", "Renton"]}))[0]
    assert profile.numeric_share == 0.0
    assert profile.min_value == "Bellevue"
    assert profile.max_value == "Seattle"


def test_the_most_common_values_are_reported() -> None:
    # This is what makes a sentinel like 0 visible directly, instead of leaving
    # somebody to deduce it from average text length.
    years = pd.Series(["0"] * 30 + ["2005"] * 5 + ["1998"] * 2)
    profile = profile_columns(pd.DataFrame({"yr_renovated": years}))[0]
    assert profile.top_values[0].value == "0"
    assert profile.top_values[0].count == 30
    assert len(profile.top_values) <= 5


def test_top_values_break_ties_by_value_so_two_runs_agree() -> None:
    tied = pd.Series(["b", "a", "c"])
    assert [item.value for item in top_values(tied)] == ["a", "b", "c"]


def test_outliers_are_counted_by_the_interquartile_fence() -> None:
    values = pd.Series([str(number) for number in range(1, 21)] + ["10000"])
    profile = profile_columns(pd.DataFrame({"price": values}))[0]
    assert profile.outlier_count == 1


def test_a_column_of_category_codes_gets_no_outlier_count() -> None:
    # waterfront holds 0/1: an interquartile fence on it means nothing.
    codes = pd.Series(["0"] * 90 + ["1"] * 10)
    profile = profile_columns(pd.DataFrame({"waterfront": codes}))[0]
    assert profile.outlier_count == 0


def test_numeric_share_separates_a_measure_from_a_label() -> None:
    _, measure = numeric_view(pd.Series(["1", "2.5", "3"]))
    _, label = numeric_view(pd.Series(["WA 98133", "WA 98119"]))
    assert measure == 1.0
    assert label == 0.0


def test_outlier_counting_needs_enough_values() -> None:
    assert count_outliers(pd.Series([1.0, 100.0])) == 0


def test_duplicate_rows_are_counted_so_deduplication_can_be_judged() -> None:
    frame = pd.DataFrame({"a": ["1", "1", "2"], "b": ["x", "x", "y"]})
    columns = profile_columns(frame)
    report = merge_profile(frame, columns, guess_roles(columns), None)
    assert report.duplicate_rows == 1
    assert report.duplicate_rows_pct == pytest.approx(33.33, abs=0.01)


def test_a_column_full_of_emails_is_flagged_as_personal() -> None:
    assert looks_like_pii(frame()["vendor_email"])


def test_an_ordinary_column_is_not_flagged() -> None:
    assert not looks_like_pii(frame()["case_id"])
    assert not looks_like_pii(frame()["activity"])


def test_one_stray_email_does_not_lock_a_whole_column() -> None:
    # A single match in free text must not condemn the column.
    mostly_text = pd.Series(["ghi chu binh thuong"] * 19 + ["lien he a@x.com"])
    assert not looks_like_pii(mostly_text)


def test_a_document_number_is_not_mistaken_for_a_bank_account() -> None:
    # Found on the real BPI log: purchase document numbers match the bank
    # account pattern, and flagging case_id would withhold the single most
    # important column for process mining.
    documents = pd.Series(["2000000000", "2000000001", "2000000002"] * 10)
    assert not looks_like_pii(documents, "case_purchasing_document")
    assert not looks_like_pii(pd.Series(["2000000000_00001"] * 30), "case_id")


def test_the_same_digits_are_flagged_when_the_column_name_agrees() -> None:
    accounts = pd.Series(["19001234561", "19001234562", "19001234563"] * 10)
    assert looks_like_pii(accounts, "bank_account")
    assert looks_like_pii(accounts, "so_tai_khoan")


def test_an_email_column_is_flagged_whatever_it_is_called() -> None:
    # A strong pattern speaks for itself and needs no help from the name.
    emails = pd.Series([f"nguoi{index}@example.com" for index in range(30)])
    assert looks_like_pii(emails, "cot_khong_ten_goi_gi")


def test_the_event_log_roles_are_guessed_from_column_names() -> None:
    roles = guess_roles(profile_columns(frame()))
    assert roles.case_id == "case_id"
    assert roles.activity == "activity"
    assert roles.timestamp == "timestamp"
    assert roles.resource == "resource"
    assert roles.is_complete


def test_roles_stay_empty_when_nothing_matches() -> None:
    plain = pd.DataFrame({"alpha": [1], "beta": [2]})
    assert not guess_roles(profile_columns(plain)).is_complete


# --- the model may comment, never count ---------------------------------------


def test_the_model_cannot_change_a_measured_number() -> None:
    data = frame()
    columns = profile_columns(data)
    lying = ProfileInterpretation(
        column_meanings={"amount": "so tien"},
        observations=["bang nay co 999999 dong"],
    )
    report = merge_profile(data, columns, guess_roles(columns), lying)
    # The commentary is kept, but row_count comes from the frame.
    assert report.row_count == 4
    assert "bang nay co 999999 dong" in report.observations


def test_the_model_can_add_a_meaning_and_a_pii_flag() -> None:
    data = frame()
    columns = profile_columns(data)
    interpretation = ProfileInterpretation(
        column_meanings={"resource": "nguoi thuc hien buoc nay"},
        pii_columns=["resource"],
    )
    report = merge_profile(data, columns, guess_roles(columns), interpretation)
    resource = next(column for column in report.columns if column.name == "resource")
    assert resource.meaning == "nguoi thuc hien buoc nay"
    assert "resource" in report.pii_flags
    # The regex detector had already found the email column on its own.
    assert "vendor_email" in report.pii_flags


def test_a_profile_without_a_model_is_still_a_profile() -> None:
    data = frame()
    columns = profile_columns(data)
    report = merge_profile(data, columns, guess_roles(columns), None)
    assert report.row_count == 4
    assert report.observations == ()
    assert "vendor_email" in report.pii_flags


# --- what actually leaves the process -----------------------------------------


def test_the_prompt_payload_carries_no_personal_values() -> None:
    data = frame()
    request = build_interpretation_request(data, profile_columns(data))
    assert "a@x.com" not in request.prompt
    payload = json.loads(request.prompt)
    assert "vendor_email" in payload["pii_columns"]
    assert len(payload["sample_rows"]) <= 20


def test_the_prompt_comes_from_a_versioned_file() -> None:
    assert "JSON" in load_prompt("a2_profiler_interpret")


def test_a_missing_prompt_is_an_error_not_an_improvised_default(tmp_path: Path) -> None:
    with pytest.raises(PromptError):
        load_prompt("khong_co_prompt_nay", tmp_path)


# --- the agent ----------------------------------------------------------------


def stage(settings: Settings, data: pd.DataFrame) -> DataRef:
    """Write a frame into the staging layer and return a reference to it."""
    storage.write_parquet(data, resolve("staging://events.parquet", settings))
    return DataRef(path="staging://events.parquet", format="parquet", content_hash="a" * 64)


def test_the_agent_writes_its_report_into_the_profile_layer(settings: Settings) -> None:
    agent = ProfilerAgent(settings, MANIFEST_DIR)
    request = TaskRequest(
        scope=token(), input_refs=(stage(settings, frame()),), instruction="mo ta"
    )
    result = agent.run(request, now=NOW)

    assert result.is_ok, result.error
    # Named after the run: a fixed name let a second run destroy the first
    # one's evidence with nothing noticing.
    assert result.output_refs[0].path == "profile://r_1_profile.json"
    assert (settings.layers.profile / "r_1_profile.json").is_file()
    assert result.payload["row_count"] == 4
    assert "vendor_email" in result.payload["pii_flags"]


def test_the_agent_reports_a_missing_input_instead_of_guessing(settings: Settings) -> None:
    agent = ProfilerAgent(settings, MANIFEST_DIR)
    result = agent.run(TaskRequest(scope=token(), instruction="mo ta"), now=NOW)
    assert result.status == "FAILED"
    assert result.error is not None
    assert result.error.code == "NO_INPUT"


def test_the_agent_uses_a_recorded_answer_when_one_exists(
    settings: Settings, tmp_path: Path
) -> None:
    data = frame()
    cassettes = tmp_path / "cassettes"
    cassettes.mkdir()
    provider = CassetteProvider(cassettes)
    request = build_interpretation_request(data, profile_columns(data))
    provider.record(
        request,
        LlmResponse(
            data=ProfileInterpretation(
                column_meanings={"amount": "gia tri don hang"},
                eventlog_candidates=EventLogCandidates(
                    case_id="case_id",
                    activity="activity",
                    timestamp="timestamp",
                    resource="resource",
                ),
                observations=["cot resource thieu 25 phan tram"],
            ),
            provider="cassette",
            model="recorded",
        ),
    )

    agent = ProfilerAgent(settings, MANIFEST_DIR, llm=LlmClient(provider))
    result = agent.run(
        TaskRequest(scope=token(), input_refs=(stage(settings, data),), instruction="mo ta"),
        now=NOW,
    )
    assert result.is_ok, result.error
    amount = next(c for c in result.payload["columns"] if c["name"] == "amount")
    assert amount["meaning"] == "gia tri don hang"
    assert result.payload["observations"] == ["cot resource thieu 25 phan tram"]


def test_the_agent_is_refused_when_it_is_handed_a_write_it_may_not_have(
    settings: Settings,
) -> None:
    # A2 is read-only over data; granting it clean:// contradicts its manifest.
    wider = token().model_copy(update={"allow_write": ("clean://**",)})
    result = ProfilerAgent(settings, MANIFEST_DIR).run(
        TaskRequest(scope=wider, input_refs=(stage(settings, frame()),), instruction="mo ta"),
        now=NOW,
    )
    assert result.status == "BOUNDARY_VIOLATION"


# --- the rulebook guard on proposals ------------------------------------------


def test_a_rule_outside_the_rulebook_is_rejected_at_the_contract() -> None:
    # This is what stops an invented rule ever reaching the executor.
    with pytest.raises(ValueError, match="rulebook"):
        ProposedRule(rule_id="xoa_het_dong_xau")


def test_a_real_rule_is_accepted() -> None:
    assert ProposedRule(rule_id="trim_whitespace", columns=("vendor",)).rule_id == "trim_whitespace"


@pytest.mark.skipif(not FIXTURE.is_file(), reason="chua co fixture")
def test_the_real_fixture_profiles_as_a_complete_event_log() -> None:
    data = pd.read_csv(FIXTURE, dtype=str)
    roles = guess_roles(profile_columns(data))
    assert roles.is_complete
    assert roles.case_id == "case_id"
    assert roles.activity == "activity"


def test_the_profile_is_named_after_the_run() -> None:
    # A fixed name let a second run destroy the first one's evidence with
    # nothing in the system noticing.
    assert profile_uri_for("r_alpha") == "profile://r_alpha_profile.json"
    assert profile_uri_for("r_alpha") != profile_uri_for("r_beta")
