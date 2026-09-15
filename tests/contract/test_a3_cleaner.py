"""A3 tests: it proposes, a human approves, and only then does it clean."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from analysis_system.agents.a3_cleaner import (
    APPROVED_RULES_PARAM,
    CleanerAgent,
    build_proposal_request,
    clean_uri_for,
    rule_scope,
    summarise_diff,
    without_duplicates,
    without_unrunnable,
)
from analysis_system.contracts.agents import ProposedRule, RuleProposal
from analysis_system.contracts.base import DataRef, ScopeToken, TaskRequest
from analysis_system.core import storage
from analysis_system.core.settings import LAYER_NAMES, LayerPaths, Settings, load_settings, resolve
from analysis_system.manager.gates import rule_options
from analysis_system.services.llm import CassetteProvider, LlmClient, LlmResponse
from analysis_system.services.rulebook import DiffEntry

NOW = datetime(2026, 8, 31, 11, 0, tzinfo=UTC)
MANIFEST_DIR = Path(__file__).resolve().parents[2] / "config" / "manifests"


def dirty() -> pd.DataFrame:
    """Forty rows: whitespace to trim, plus exactly one duplicate pair.

    The size matters. With only four rows, removing a single duplicate is a 25
    percent loss and trips the 5 percent ceiling - the guard would fire on a
    perfectly ordinary de-duplication. One duplicate in forty rows is 2.5
    percent, which is what a realistic clean looks like.
    """
    rows = [
        {"case_id": f"c{index}", "activity": "Create", "amount": str(index)}
        for index in range(1, 40)
    ]
    rows[0]["case_id"] = "  c1  "
    rows.append(dict(rows[-1]))
    return pd.DataFrame(rows)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    roots = {name: tmp_path / name for name in LAYER_NAMES}
    for root in roots.values():
        root.mkdir(parents=True, exist_ok=True)
    return load_settings().model_copy(update={"layers": LayerPaths(**roots)})


def token(params: dict[str, Any] | None = None, *, max_dropped: float | None = 5.0) -> ScopeToken:
    """A token matching the shipped a3_cleaner manifest."""
    return ScopeToken(
        run_id="r_1",
        task_id="t_03",
        agent_id="a3_cleaner",
        allow_read=("staging://**", "profile://**"),
        allow_write=("clean://**",),
        allow_tools=("pandas", "rulebook.apply"),
        params=params or {},
        limits={"max_rows_dropped_pct": max_dropped, "max_retries": 3},  # type: ignore[arg-type]
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )


def stage(settings: Settings, frame: pd.DataFrame) -> DataRef:
    storage.write_parquet(frame, resolve("staging://events.parquet", settings))
    return DataRef(path="staging://events.parquet", format="parquet", content_hash="a" * 64)


def request_for(scope: ScopeToken, ref: DataRef) -> TaskRequest:
    return TaskRequest(scope=scope, input_refs=(ref,), instruction="lam sach")


# --- mode one: propose only ---------------------------------------------------


def test_without_approved_rules_it_proposes_and_writes_nothing(settings: Settings) -> None:
    agent = CleanerAgent(settings, MANIFEST_DIR)
    result = agent.run(request_for(token(), stage(settings, dirty())), now=NOW)

    assert result.status == "NEEDS_REVIEW"
    assert result.payload["mode"] == "propose"
    # The whole point: nothing has been cleaned yet.
    assert not (settings.layers.clean / "events.parquet").exists()
    assert result.output_refs == ()


def test_a_proposal_from_the_model_is_carried_to_the_gate(
    settings: Settings, tmp_path: Path
) -> None:
    frame = dirty()
    cassettes = tmp_path / "cassettes"
    cassettes.mkdir()
    provider = CassetteProvider(cassettes)
    provider.record(
        build_proposal_request(frame, None),
        LlmResponse(
            data=RuleProposal(
                rules=[
                    ProposedRule(
                        rule_id="trim_whitespace",
                        columns=("case_id",),
                        reason="case_id co khoang trang thua",
                    ),
                    ProposedRule(rule_id="drop_exact_duplicates", reason="co dong trung"),
                ],
                summary="hai rule",
            ),
            provider="cassette",
            model="recorded",
        ),
    )

    agent = CleanerAgent(settings, MANIFEST_DIR, llm=LlmClient(provider))
    result = agent.run(request_for(token(), stage(settings, frame)), now=NOW)

    assert result.status == "NEEDS_REVIEW"
    assert result.payload["rule_ids"] == ["trim_whitespace", "drop_exact_duplicates"]
    assert not (settings.layers.clean / "events.parquet").exists()


# --- mode two: execute only what was approved ---------------------------------


def test_with_approved_rules_it_cleans_and_writes(settings: Settings) -> None:
    approved = [
        {"rule_id": "trim_whitespace", "columns": ["case_id"], "reason": "duyet"},
        {"rule_id": "drop_exact_duplicates", "reason": "duyet"},
    ]
    agent = CleanerAgent(settings, MANIFEST_DIR)
    result = agent.run(
        request_for(token({APPROVED_RULES_PARAM: approved}), stage(settings, dirty())), now=NOW
    )

    assert result.is_ok, result.error
    # Named after the data. The run id is deliberately absent: A4 derives
    # its SQL table name from this filename, so a run-dependent name would
    # break every statement written against it.
    assert result.output_refs[0].path == "clean://events.parquet"
    assert (settings.layers.clean / "events.parquet").is_file()
    assert result.payload["rows_in"] == 40
    assert result.payload["rows_out"] == 39
    assert result.payload["rules_applied"] == ["trim_whitespace", "drop_exact_duplicates"]
    assert result.payload["content_hash"]


def test_it_runs_only_the_approved_rules_not_every_rule(settings: Settings) -> None:
    approved = [{"rule_id": "trim_whitespace", "columns": ["case_id"], "reason": "duyet"}]
    result = CleanerAgent(settings, MANIFEST_DIR).run(
        request_for(token({APPROVED_RULES_PARAM: approved}), stage(settings, dirty())), now=NOW
    )
    assert result.payload["rules_applied"] == ["trim_whitespace"]
    # Duplicates survive because de-duplication was never approved.
    assert result.payload["rows_out"] == 40


def test_two_column_groups_approved_together_actually_clean(settings: Settings) -> None:
    frame = pd.DataFrame({"a": ["1", "2"], "b": ["3.5", "4.5"], "c": ["x", "y"]})
    approved = [
        {"rule_id": "cast_numeric_safe", "columns": ["a"], "reason": "duyet"},
        {"rule_id": "cast_numeric_safe", "columns": ["b"], "reason": "duyet"},
    ]
    result = CleanerAgent(settings, MANIFEST_DIR).run(
        request_for(token({APPROVED_RULES_PARAM: approved}), stage(settings, frame)), now=NOW
    )
    assert result.is_ok, result.error
    assert result.payload["rules_applied"] == ["cast_numeric_safe", "cast_numeric_safe"]


def test_an_invented_parameter_stops_the_run_instead_of_being_ignored(
    settings: Settings,
) -> None:
    # Exactly what a real proposal did: it asked for target_type, which no rule
    # reads. Silently ignoring it would make the approved plan a lie.
    approved = [
        {
            "rule_id": "cast_numeric_safe",
            "columns": ["a"],
            "params": {"target_type": "int64"},
            "reason": "duyet",
        }
    ]
    frame = pd.DataFrame({"a": ["1", "2"]})
    result = CleanerAgent(settings, MANIFEST_DIR).run(
        request_for(token({APPROVED_RULES_PARAM: approved}), stage(settings, frame)), now=NOW
    )
    assert result.status == "FAILED"
    assert result.error is not None
    assert "target_type" in result.error.message
    assert not (settings.layers.clean / "events.parquet").exists()


def test_the_proposal_prompt_lists_the_parameters_each_rule_reads() -> None:
    # The model invented parameters because it was only shown rule names.
    request = build_proposal_request(dirty(), None)
    assert "assume_timezone" in request.prompt


def test_an_invented_rule_is_refused_even_if_it_reaches_the_agent(settings: Settings) -> None:
    approved = [{"rule_id": "xoa_het_dong_xau", "reason": "ai do tu che"}]
    result = CleanerAgent(settings, MANIFEST_DIR).run(
        request_for(token({APPROVED_RULES_PARAM: approved}), stage(settings, dirty())), now=NOW
    )
    assert result.status == "FAILED"
    assert result.error is not None
    assert result.error.code == "RULE_OUTSIDE_RULEBOOK"
    assert not (settings.layers.clean / "events.parquet").exists()


def test_dropping_more_than_the_ceiling_halts_and_writes_nothing(settings: Settings) -> None:
    # Four rows collapsing to one is a 75 percent loss, far past the 5 percent ceiling.
    frame = pd.DataFrame({"case_id": ["c1"] * 4, "activity": ["Create"] * 4})
    approved = [{"rule_id": "drop_exact_duplicates", "reason": "duyet"}]
    result = CleanerAgent(settings, MANIFEST_DIR).run(
        request_for(token({APPROVED_RULES_PARAM: approved}), stage(settings, frame)), now=NOW
    )

    assert result.status == "FAILED"
    assert result.error is not None
    assert result.error.code == "ROWS_DROPPED_EXCEEDED"
    assert result.metrics["rows_dropped_pct"] == pytest.approx(75.0)
    # Nothing half-cleaned is left behind for someone to pick up by mistake.
    assert not (settings.layers.clean / "events.parquet").exists()


def test_standardize_datetime_still_refuses_to_guess_a_timezone(settings: Settings) -> None:
    # The refusal is reported as a failed task, not raised as a crash: the
    # Manager has to be able to record it and decide what happens next.
    frame = pd.DataFrame({"timestamp": ["2018-01-01T00:00:00Z", "2018-01-02T00:00:00Z"]})
    approved = [{"rule_id": "standardize_datetime", "columns": ["timestamp"], "reason": "duyet"}]
    result = CleanerAgent(settings, MANIFEST_DIR).run(
        request_for(token({APPROVED_RULES_PARAM: approved}), stage(settings, frame)), now=NOW
    )
    assert result.status == "FAILED"
    assert result.error is not None
    assert "assume_timezone" in result.error.message
    assert not (settings.layers.clean / "events.parquet").exists()


def test_the_approved_params_are_what_make_the_datetime_rule_run(settings: Settings) -> None:
    frame = pd.DataFrame({"timestamp": ["2018-01-01T00:00:00Z", "2018-01-02T00:00:00Z"]})
    approved = [
        {
            "rule_id": "standardize_datetime",
            "columns": ["timestamp"],
            "params": {"assume_timezone": "UTC"},
            "reason": "duyet",
        }
    ]
    result = CleanerAgent(settings, MANIFEST_DIR).run(
        request_for(token({APPROVED_RULES_PARAM: approved}), stage(settings, frame)), now=NOW
    )
    assert result.is_ok, result.error


def test_bad_params_are_reported_rather_than_ignored(settings: Settings) -> None:
    result = CleanerAgent(settings, MANIFEST_DIR).run(
        request_for(token({APPROVED_RULES_PARAM: "khong phai list"}), stage(settings, dirty())),
        now=NOW,
    )
    assert result.status == "FAILED"
    assert result.error is not None
    assert result.error.code == "BAD_PARAMS"


# --- helpers ------------------------------------------------------------------


def test_the_diff_log_is_grouped_with_a_few_examples() -> None:
    diff = tuple(
        DiffEntry("trim_whitespace", "case_id", index, "  x  ", "x", "cat khoang trang thua")
        for index in range(10)
    )
    summary = summarise_diff(diff)
    assert len(summary) == 1
    assert summary[0].count == 10
    assert len(summary[0].examples) == 3


def test_the_proposal_prompt_carries_the_rulebook_and_no_raw_table() -> None:
    request = build_proposal_request(dirty(), None)
    assert "trim_whitespace" in request.prompt
    assert "drop_exact_duplicates" in request.prompt
    assert request.purpose == "a3_cleaner_propose"


# --- where the cleaned table goes ----------------------------------------------


def test_the_cleaned_table_is_named_after_the_data() -> None:
    # It used to be clean://events.parquet for everything - a leftover from the
    # event log this was built around, which left every later dataset both
    # mislabelled and liable to overwrite the one before it.
    assert clean_uri_for("staging://r1_students.parquet", "r1") == "clean://students.parquet"
    assert clean_uri_for("staging://houses.parquet", "r9") == "clean://houses.parquet"


def test_the_run_id_is_deliberately_not_in_the_name() -> None:
    # A4 derives its SQL table name from this filename. A run-dependent name
    # would break every statement written against it.
    first = clean_uri_for("staging://r1_students.parquet", "r1")
    second = clean_uri_for("staging://r2_students.parquet", "r2")
    assert first == second == "clean://students.parquet"


def test_two_datasets_do_not_collide() -> None:
    assert clean_uri_for("staging://r1_students.parquet", "r1") != clean_uri_for(
        "staging://r1_houses.parquet", "r1"
    )


# --- pham vi that di canh de xuat, khong nam trong no ------------------------------


def test_a_rule_naming_no_columns_resolves_to_every_column() -> None:
    """What the gate needs in order to ask an answerable question."""
    frame = pd.DataFrame({"ngay": ["2026-01-01"], "kenh": ["ban le"], "doanh_thu": ["100"]})
    proposal = RuleProposal(rules=[ProposedRule(rule_id="cast_numeric_safe")])
    assert rule_scope(proposal, frame) == [["ngay", "kenh", "doanh_thu"]]


def test_named_columns_are_kept_as_named() -> None:
    frame = pd.DataFrame({"a": [1], "b": [2]})
    proposal = RuleProposal(rules=[ProposedRule(rule_id="trim_whitespace", columns=("a",))])
    assert rule_scope(proposal, frame) == [["a"]]


def test_a_column_that_does_not_exist_is_still_shown() -> None:
    """The rulebook refuses it by name later.

    Hiding it here would turn a clear refusal into a silent surprise: the person
    would approve a rule naming a column, and the run would stop for a reason
    that never appeared on the screen they answered.
    """
    frame = pd.DataFrame({"a": [1]})
    proposal = RuleProposal(rules=[ProposedRule(rule_id="trim_whitespace", columns=("khong_co",))])
    assert rule_scope(proposal, frame) == [["khong_co"]]


def test_the_scope_travels_beside_the_proposal_not_inside_it(settings: Settings) -> None:
    """Inside, the model would see the field in its schema and could write it.

    A scope the proposer states is not a check on the proposer. Putting it
    inside also broke the round trip: ProposedRule forbids extra fields, so the
    saved proposal became unreadable and every approval quietly stopped
    matching.
    """
    agent = CleanerAgent(settings, MANIFEST_DIR)
    result = agent.run(request_for(token(), stage(settings, dirty())), now=NOW)

    assert "rule_scope" in result.payload
    for rule in result.payload["proposal"]["rules"]:
        assert "applies_to" not in rule
    # The saved proposal still parses, which is what an approval depends on.
    RuleProposal.model_validate(result.payload["proposal"])


# --- cong duyet phai noi ra HAU QUA, khong phai Y DINH -----------------------------


def test_a_rule_naming_no_columns_says_it_touches_every_one() -> None:
    """The silence that emptied two columns of a real table.

    A rule naming no columns applies to all of them - a convention the prompt
    states and the rulebook knows, and which the gate used to leave unsaid.
    Approving `cast_numeric_safe` on a sales table cast the date column and the
    channel column to numbers and left `NaN` behind, and nothing on the screen
    had suggested it would.
    """
    options = rule_options(
        [{"rule_id": "cast_numeric_safe", "columns": [], "reason": "doanh_thu la chuoi"}],
        [["ngay_ban", "kenh", "doanh_thu", "so_don"]],
    )
    assert "MOI COT" in options[0].label
    assert "ngay_ban" in options[0].label, "phai goi ten, vi 4 cot va 50 cot la hai quyet dinh"


def test_a_rule_naming_columns_shows_exactly_those() -> None:
    options = rule_options(
        [{"rule_id": "trim_whitespace", "columns": ["kenh"], "reason": "co khoang trang"}],
        [["kenh"]],
    )
    assert "(kenh)" in options[0].label
    assert "MOI COT" not in options[0].label


def test_without_a_resolved_scope_silence_still_says_every_column() -> None:
    """An older payload has no scope beside it, and must not read as "no columns"."""
    options = rule_options([{"rule_id": "cast_numeric_safe", "columns": []}])
    assert options[0].label.endswith("(MOI COT)")


def test_the_reason_still_travels_with_the_option() -> None:
    """Seeing the contradiction needs both halves: the intention and the scope."""
    options = rule_options(
        [{"rule_id": "cast_numeric_safe", "columns": [], "reason": "chi doanh_thu la chuoi"}],
        [["ngay_ban", "doanh_thu"]],
    )
    assert "chi doanh_thu la chuoi" in options[0].detail
    assert "ngay_ban" in options[0].label, "nguoi duyet phai thay duoc mau thuan"


# --- de xuat trung nhau, va de xuat khong ly do -----------------------------------


def test_three_copies_of_one_rule_become_one_question() -> None:
    """What a fresh dataset really produced on its first run.

    Three identical `trim_whitespace` over every column. They are one decision,
    not three: approving the first and refusing the third would mean nothing,
    and a list that asks the same question repeatedly teaches people to stop
    reading it.
    """
    proposal = RuleProposal(rules=[ProposedRule(rule_id="trim_whitespace")] * 3)
    kept, notes = without_duplicates(proposal)

    assert len(kept.rules) == 1
    assert len(notes) == 2
    assert "trùng" in notes[0]


def test_the_same_rule_for_different_columns_is_kept() -> None:
    """A different intention, which is what the prompt asks proposers to do.

    Casting one column to a whole number and another to a decimal are two
    decisions that happen to share a rule id.
    """
    proposal = RuleProposal(
        rules=[
            ProposedRule(rule_id="trim_whitespace", columns=("kenh",)),
            ProposedRule(rule_id="trim_whitespace", columns=("nhom_van_de",)),
        ]
    )
    kept, notes = without_duplicates(proposal)
    assert len(kept.rules) == 2
    assert notes == []


def test_the_same_rule_with_different_parameters_is_kept() -> None:
    proposal = RuleProposal(
        rules=[
            ProposedRule(rule_id="standardize_datetime", params={"assume_timezone": "UTC"}),
            ProposedRule(
                rule_id="standardize_datetime", params={"assume_timezone": "Asia/Bangkok"}
            ),
        ]
    )
    kept, _ = without_duplicates(proposal)
    assert len(kept.rules) == 2


def test_removing_a_duplicate_is_said_out_loud(settings: Settings) -> None:
    """A duplicate dropped in silence looks like a model that never proposed it."""
    proposal = RuleProposal(rules=[ProposedRule(rule_id="trim_whitespace")] * 2)
    _, notes = without_duplicates(proposal)
    assert notes and "trim_whitespace" in notes[0]
    assert settings is not None


def test_a_rule_with_no_reason_says_so_at_the_gate() -> None:
    """Approving a change because a model suggested it and said nothing is not approving.

    The prompt requires a reason - "bang chung nao trong ho so dan toi de xuat
    do" - and a real run produced five rules with none at all. Nothing checked,
    so a person was asked to approve five unjustified changes to their data.
    """
    options = rule_options([{"rule_id": "cast_numeric_safe", "columns": [], "reason": ""}])
    assert "KHONG CO LY DO" in options[0].detail


def test_a_rule_with_a_reason_shows_the_reason() -> None:
    """The other direction, so the flag cannot be the answer to everything."""
    options = rule_options(
        [{"rule_id": "trim_whitespace", "columns": ["kenh"], "reason": "kenh co khoang trang"}]
    )
    assert "kenh co khoang trang" in options[0].detail


# --- cai gi dem duoc thi phai duyet duoc ------------------------------------------


def test_what_the_examination_counted_is_something_a_person_can_approve(
    settings: Settings,
) -> None:
    # A real run on 1,000 rows: the examination found five columns needing work
    # and the gate offered nothing to agree to. Being shown a problem you cannot
    # consent to fixing is not being consulted - and consulting is the whole of
    # what was asked for: say where and how, then do what the person says.
    frame = pd.DataFrame(
        {
            "ten": ["An ", " Binh", "Chi", "Chi"],
            "diem": ["8.5", "7.0", "9.25", "9.25"],
        }
    )
    agent = CleanerAgent(settings, MANIFEST_DIR)

    result = agent.run(request_for(token(), stage(settings, frame)), now=NOW)

    offered = {rule["rule_id"] for rule in result.payload["proposal"]["rules"]}
    assert "trim_whitespace" in offered
    assert "cast_numeric_safe" in offered
    assert result.payload["rule_ids"], "gate phai co muc de duyet"


def test_a_seeded_rule_says_it_was_measured_not_guessed(settings: Settings) -> None:
    result = CleanerAgent(settings, MANIFEST_DIR).run(
        request_for(token(), stage(settings, pd.DataFrame({"ten": ["An ", " Binh", "Chi"]}))),
        now=NOW,
    )

    reasons = [rule["reason"] for rule in result.payload["proposal"]["rules"]]
    assert any("[đo từ dữ liệu]" in reason for reason in reasons)
    # Counted, so it carries numbers: a reason without them is an impression.
    assert any("dòng," in reason for reason in reasons)


def test_a_whole_table_finding_is_not_scoped_to_a_column_of_that_name(
    settings: Settings,
) -> None:
    # "(moi cot)" is how a whole-table finding prints. Seeded as a column name it
    # would scope drop_exact_duplicates to a column that does not exist.
    frame = pd.DataFrame({"a": [1, 1, 2], "b": ["x", "x", "y"]})

    result = CleanerAgent(settings, MANIFEST_DIR).run(
        request_for(token(), stage(settings, frame)), now=NOW
    )

    duplicates = [
        rule
        for rule in result.payload["proposal"]["rules"]
        if rule["rule_id"] == "drop_exact_duplicates"
    ]
    assert duplicates, "dong trung lap phai duoc de nghi"
    assert duplicates[0]["columns"] == []


# --- khong bay ra rule khong the chay ---------------------------------------------


def test_a_rule_that_cannot_run_is_never_offered() -> None:
    # A real run offered replace_sentinel_with_null with no sentinels list. The
    # rule requires one and refuses to guess, so the option was approved in good
    # faith and the run died on it - after the approval, with nothing left for
    # the person to do. A gate must only offer what approving would actually do.
    proposal = RuleProposal(
        rules=[
            ProposedRule(
                rule_id="replace_sentinel_with_null",
                columns=("ghi_chu",),
                reason="co gia tri thay the",
            ),
            ProposedRule(rule_id="trim_whitespace", columns=("ten",), reason="thua khoang trang"),
        ]
    )

    kept, notes = without_unrunnable(proposal)

    assert [rule.rule_id for rule in kept.rules] == ["trim_whitespace"]
    assert any("sentinels" in note for note in notes)


def test_a_dropped_rule_is_dropped_out_loud() -> None:
    # A rule that vanishes without a word looks like a proposer that never
    # proposed it, and afterwards nobody can tell the two apart.
    proposal = RuleProposal(
        rules=[
            ProposedRule(rule_id="standardize_datetime", columns=("ngay",), reason="la ngay thang")
        ]
    )

    _, notes = without_unrunnable(proposal)

    assert len(notes) == 1
    assert "assume_timezone" in notes[0]


def test_a_rule_that_carries_its_parameters_is_kept() -> None:
    proposal = RuleProposal(
        rules=[
            ProposedRule(
                rule_id="replace_sentinel_with_null",
                columns=("ghi_chu",),
                reason="co gia tri thay the",
                params={"sentinels": ["N/A", "-"]},
            )
        ]
    )

    kept, notes = without_unrunnable(proposal)

    assert len(kept.rules) == 1
    assert notes == []


# --- ten luat viet bang tieng nguoi -------------------------------------------


def test_a_rule_is_named_in_words_a_new_user_can_read() -> None:
    """`cast_numeric_safe` khong noi gi voi nguoi vua tai tep len lan dau.

    Ho dang duoc hoi co cho no SUA DU LIEU CUA HO khong. Doc khong hieu thi ho
    khong duyet - ho doan.
    """
    options = rule_options(
        [{"rule_id": "cast_numeric_safe", "columns": ["tuoi"], "reason": "dang luu dang chu"}],
        [["tuoi"]],
    )
    assert "cast_numeric_safe" not in options[0].label
    assert "số" in options[0].label


def test_the_column_names_are_left_exactly_as_the_file_has_them() -> None:
    """Ten cot la thu nguoi duyet nhan ra trong tep cua chinh ho. Khong dich."""
    options = rule_options(
        [{"rule_id": "cast_numeric_safe", "columns": ["Objective"], "reason": "x"}],
        [["Objective"]],
    )
    assert "Objective" in options[0].label


def test_the_detail_shows_a_real_before_and_after() -> None:
    """Mot cau mo ta van de nguoi ta phai tuong tuong. `"34"` thanh `34` thi khong."""
    options = rule_options(
        [{"rule_id": "cast_numeric_safe", "columns": ["tuoi"], "reason": "dang luu dang chu"}],
        [["tuoi"]],
    )
    assert '"34"' in options[0].detail


def test_the_rule_code_is_still_there_for_whoever_runs_the_system() -> None:
    """Ma luat khop voi nhat ky chay. Nguoi van hanh can no, chi la khong can truoc."""
    options = rule_options(
        [{"rule_id": "cast_numeric_safe", "columns": ["tuoi"], "reason": "x"}],
        [["tuoi"]],
    )
    assert "[cast_numeric_safe]" in options[0].detail


def test_the_reason_the_model_gave_is_not_lost() -> None:
    options = rule_options(
        [{"rule_id": "cast_numeric_safe", "columns": ["tuoi"], "reason": "dang luu dang chu"}],
        [["tuoi"]],
    )
    assert "dang luu dang chu" in options[0].detail


def test_a_rule_with_no_vietnamese_name_shows_its_code_rather_than_a_guess() -> None:
    """Doan bua mot cai ten con te hon mot cai ma kho doc.

    Ma kho doc thi nguoi ta hoi lai. Ten sai thi nguoi ta duyet.
    """
    options = rule_options([{"rule_id": "luat_la_hoac", "reason": "x"}], None)
    assert options[0].label.startswith("luat_la_hoac")


def test_a_sideways_table_is_unpivoted_without_being_asked(settings: Settings) -> None:
    """Chu he thong chon: bang nam ngang tu xoay doc, va noi ra ca truoc lan sau (2026-09-15)."""
    frame = pd.DataFrame(
        {
            "Chỉ tiêu": ["Doanh thu", "Chi phí", "Lợi nhuận"],
            "Q1-2026": ["1,200.5", "300", "900.5"],
            "Q2-2026": ["1,500", "400", "1,100"],
        }
    )
    agent = CleanerAgent(settings, MANIFEST_DIR)
    proposed = agent.run(request_for(token(), stage(settings, frame)), now=NOW)
    assert any("Tự động khi làm sạch" in note for note in proposed.declined)
    assert "unpivot_periods" not in proposed.payload["rule_ids"]

    approved = [{"rule_id": "trim_whitespace", "columns": ["Chỉ tiêu"], "reason": "duyet"}]
    result = agent.run(
        request_for(token({APPROVED_RULES_PARAM: approved}), stage(settings, frame)), now=NOW
    )
    assert result.is_ok, result.error
    clean = storage.read_parquet(settings.layers.clean / "events.parquet")
    assert list(clean.columns) == ["Chỉ tiêu", "Kỳ báo cáo", "Giá trị"]
    assert len(clean.index) == 6
    assert clean["Giá trị"].tolist()[:2] == [1200.5, 1500.0]
    assert "unpivot_periods" in result.payload["rules_applied"]
    assert result.metrics["rows_dropped_pct"] == 0.0
    assert any("Tự động" in note for note in result.declined)
