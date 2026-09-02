"""Prompt regression: a prompt is code, and changing it must not break the rules.

Prompts live in their own files so a change shows up in review as a diff. That
only helps if something also checks that the diff did not remove a rule the rest
of the system depends on.

Nothing here judges whether a prompt reads well - that is a matter of taste and
would make this suite noise. What is pinned down is narrower and harder to argue
with: every prompt still states the constraints that other code enforces, and
every prompt an agent asks for still exists.

Two failure modes this catches, both of which have already happened once:

* a rule quietly dropped while rewording - and the model then does the thing the
  rule existed to prevent, which surfaces as "the model ignored the instruction"
* a prompt renamed or removed while an agent still asks for it by name
"""

from __future__ import annotations

import pandas as pd
import pytest

from analysis_system.agents.a2_profiler import build_interpretation_request
from analysis_system.agents.a3_cleaner import build_proposal_request
from analysis_system.agents.a4_transformer import build_sql_request
from analysis_system.agents.a7_analyst import MAX_FINDINGS, build_analysis_request
from analysis_system.contracts.agents import ColumnProfile
from analysis_system.manager.planner import (
    available_agents,
    build_plan_request,
    build_replan_request,
    default_plan,
)
from analysis_system.services.prompts import available_prompts, load_prompt
from analysis_system.services.rulebook import RULE_ORDER
from tests.criteria.harness import MANIFEST_DIR

# Every prompt an agent asks for by name. A prompt missing from disk is not a
# bad answer, it is a crash.
REQUIRED_PROMPTS = (
    "a2_profiler_interpret",
    "a3_cleaner_propose",
    "a4_transformer_sql",
    "a7_analyst_findings",
    "a8_reporter_summary",
    "manager_plan",
)


def frame() -> pd.DataFrame:
    return pd.DataFrame({"city": ["Seattle", "Renton"], "price": ["100", "200"]})


# --- the prompts exist and are reachable ---------------------------------------


@pytest.mark.parametrize("name", REQUIRED_PROMPTS)
def test_every_prompt_an_agent_asks_for_exists(name: str) -> None:
    assert load_prompt(name).strip()


def test_no_prompt_file_is_orphaned() -> None:
    # A prompt nobody loads is either dead weight or a wiring mistake. Either
    # way it should be noticed rather than accumulate.
    assert set(available_prompts()) == set(REQUIRED_PROMPTS)


# --- the rules other code enforces are still stated -----------------------------


def test_the_analyst_prompt_still_forbids_typed_digits() -> None:
    # findings.check_finding rejects a claim carrying a digit the model typed.
    # If the prompt stops saying so, every answer gets rejected and the failure
    # reads as the model being useless.
    request = build_analysis_request([], "cau hoi", MAX_FINDINGS)
    assert "placeholder" in request.prompt
    assert "khong go con so truc tiep" in request.prompt.lower()


def test_the_analyst_prompt_still_names_the_table_to_cite() -> None:
    # Demanding a citation while withholding what to cite is how three runs
    # ended up citing a file that never existed.
    request = build_analysis_request([], "cau hoi", MAX_FINDINGS, source="mart://x.parquet")
    assert "source_table" in request.prompt
    assert "mart://x.parquet" in request.prompt


def test_the_analyst_prompt_still_forbids_causal_wording() -> None:
    request = build_analysis_request([], "cau hoi", MAX_FINDINGS)
    assert "MOI LIEN HE" in request.prompt
    assert "tuong quan voi" in request.prompt


def test_the_sql_prompt_still_states_every_safety_rule() -> None:
    # The guard refuses these anyway; the prompt saying so is what stops a run
    # being spent on a statement that was never going to be allowed.
    request = build_sql_request({"events": frame()}, "cau hoi", 1000)
    for rule in ("SELECT", "CROSS JOIN", "mot cau lenh", "sinh ra tu cot nao"):
        assert rule.lower() in request.prompt.lower()


def test_the_sql_prompt_still_passes_the_task_instruction_through() -> None:
    request = build_sql_request({"events": frame()}, "cau hoi", 1000, "dat ten cot la spend_area")
    assert "spend_area" in request.prompt


def test_the_cleaner_prompt_still_lists_the_rulebook_it_may_use() -> None:
    # A rule the model invents is refused by name, so the prompt has to say what
    # exists. A rule added to the book and not to the prompt is never proposed.
    request = build_proposal_request(frame(), None)
    for rule_id in RULE_ORDER:
        assert rule_id in request.prompt


def test_the_planner_prompt_still_states_what_makes_a_plan_runnable() -> None:
    request = build_plan_request("cau hoi", available_agents(MANIFEST_DIR), "raw://x.csv")
    for rule in ("depends_on", "chu trinh", "inputs_from"):
        assert rule in request.prompt


def test_the_replan_prompt_still_names_what_may_not_change() -> None:
    plan = default_plan("raw://x.csv")
    request = build_replan_request(
        "cau hoi", available_agents(MANIFEST_DIR), "raw://x.csv", plan, "hong", ("t1_ingest",)
    )
    assert "frozen" in request.prompt
    assert "DA CHAY XONG" in request.prompt


def test_the_profiler_prompt_shows_the_model_what_code_measured() -> None:
    # A2 interprets measurements; it never measures. The prompt has to carry
    # what was measured, or the model is left inventing it.
    columns = (
        ColumnProfile(name="city", dtype="str", non_null=2, null_pct=0.0, distinct=2),
        ColumnProfile(name="price", dtype="str", non_null=2, null_pct=0.0, distinct=2),
    )
    request = build_interpretation_request(frame(), columns)
    assert request.system.strip()
    assert "city" in request.prompt and "price" in request.prompt


# --- what a prompt must never do ------------------------------------------------


@pytest.mark.parametrize("name", REQUIRED_PROMPTS)
def test_no_prompt_carries_a_credential(name: str) -> None:
    # A prompt is a file in git. Anything secret in one is published.
    text = load_prompt(name).lower()
    for marker in ("sk-ant-", "aiza", "api_key=", "password"):
        assert marker not in text


@pytest.mark.parametrize("name", REQUIRED_PROMPTS)
def test_no_prompt_hard_codes_a_path_from_one_machine(name: str) -> None:
    text = load_prompt(name)
    assert "/home/" not in text
    assert "C:\\" not in text


def test_changing_a_prompt_changes_the_request_fingerprint() -> None:
    # Cassettes are keyed by it. If a reworded prompt kept its fingerprint, a
    # replay would answer the old question with the old answer and nobody would
    # see it happen.
    first = build_analysis_request([], "cau hoi mot", MAX_FINDINGS)
    second = build_analysis_request([], "cau hoi hai", MAX_FINDINGS)
    assert first.fingerprint() != second.fingerprint()


def test_a_retry_asks_a_genuinely_different_question() -> None:
    from analysis_system.contracts.base import RetryFeedback

    plain = build_analysis_request([], "cau hoi", MAX_FINDINGS)
    retried = build_analysis_request(
        [],
        "cau hoi",
        MAX_FINDINGS,
        RetryFeedback(attempt=1, max_attempts=3, rejected_because=("cau co chu so",)),
    )
    assert plain.fingerprint() != retried.fingerprint()
    assert "cau co chu so" in retried.prompt


# --- what each prompt FILE must still say --------------------------------------
#
# Every phrase below is a rule that code enforces somewhere. If a prompt stops
# saying it, the model stops obeying it, and the failure arrives disguised: the
# answers get rejected and it reads as the model having become unreliable.
#
# Short distinctive phrases rather than whole sentences, so rewording for clarity
# does not fail the test but removing the rule does.

PROMPT_INVARIANTS: dict[str, tuple[str, ...]] = {
    "a2_profiler_interpret": (
        # A2 interprets what code measured; it never produces a figure itself.
        "KHÔNG được đưa ra bất kỳ con số nào",
        "column_meanings",
        "eventlog_candidates",
        "pii_columns",
    ),
    "a3_cleaner_propose": (
        # rulebook.apply_rules refuses a rule it does not have, by name.
        "Chỉ được chọn rule trong danh sách",
        "Không bịa rule mới",
        # standardize_datetime refuses to guess a timezone.
        "assume_timezone",
        # The manifest caps rows dropped at five per cent.
        "5%",
    ),
    "a4_transformer_sql": (
        # Each of these is refused by sql_guard before anything runs.
        "CREATE VIEW",
        "Chỉ một câu lệnh",
        "Chỉ đọc các bảng được liệt kê",
        "CROSS JOIN",
    ),
    "a7_analyst_findings": (
        # check_finding drops a claim carrying a digit the model typed.
        "không được gõ bất kỳ con số nào",
        "placeholder",
        "bị loại bỏ hoàn toàn",
    ),
    "a8_reporter_summary": (
        # render_narrative holds the summary to the same rule.
        "không được gõ bất kỳ con số nào",
        "placeholder",
        "bị loại bỏ hoàn toàn",
    ),
    "manager_plan": (
        # validate_plan refuses a plan breaking any of these.
        "Chỉ gọi agent có trong danh sách",
        "depends_on",
        "chu trình",
        "task_id",
    ),
}


@pytest.mark.parametrize(
    ("name", "phrase"),
    [(name, phrase) for name, phrases in PROMPT_INVARIANTS.items() for phrase in phrases],
    ids=lambda value: value if isinstance(value, str) else str(value),
)
def test_the_prompt_file_still_states_the_rule(name: str, phrase: str) -> None:
    # Deleting this line from the .md file must turn this test red. If it does
    # not, the suite is decoration.
    text = load_prompt(name)
    assert phrase in text, (
        f"prompt {name!r} khong con noi {phrase!r}. "
        "Luat nay duoc code cuong che - bo khoi prompt thi model se vi pham no, "
        "va loi se hien ra duoi dang 'model tra loi sai' chu khong phai 'thieu luat'."
    )


def test_every_prompt_file_is_covered_by_at_least_one_invariant() -> None:
    # A prompt added without invariants can lose anything without a test noticing.
    assert set(PROMPT_INVARIANTS) == set(REQUIRED_PROMPTS)
