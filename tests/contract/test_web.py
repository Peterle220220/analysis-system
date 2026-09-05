"""Dashboard: khong dang nhap thi khong thay gi, va khong quyet dinh gi o day."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from analysis_system.api import Workspace
from analysis_system.services import storage
from analysis_system.settings import LAYER_NAMES, LayerPaths, Settings, load_settings, resolve
from analysis_system.web.app import (
    SESSION_COOKIE,
    Guard,
    added_rules,
    build,
    dataset_name,
)
from analysis_system.web.auth import AuthError, hash_password, stored_credential
from analysis_system.web.render import safe

NOW = datetime.now(UTC)
PASSWORD = "mot mat khau du dai"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    roots = {name: tmp_path / name for name in LAYER_NAMES}
    for root in roots.values():
        root.mkdir(parents=True, exist_ok=True)
    return load_settings().model_copy(update={"layers": LayerPaths(**roots)})


@pytest.fixture
def client(settings: Settings) -> TestClient:
    run_dir = Path(settings.layers.runs) / "r_web"
    run_dir.mkdir(parents=True, exist_ok=True)
    # A state a RunState can actually be built from. Written short at first,
    # and the page under test rendered a pydantic error instead of itself.
    moment = NOW.isoformat()
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": "r_web",
                "phase": "COMPLETED",
                "tasks": {},
                "created_at": moment,
                "updated_at": moment,
            }
        ),
        encoding="utf-8",
    )
    storage.write_parquet(
        pd.DataFrame({"a": [1]}), resolve("mart://r_web_t1_out.parquet", settings)
    )
    space = Workspace(settings=settings)
    guard = Guard(credential=hash_password(PASSWORD), secret="test-secret")
    return TestClient(build(space, guard), follow_redirects=False)


def sign_in(client: TestClient, password: str = PASSWORD) -> None:
    answer = client.post("/dang-nhap", data={"password": password})
    assert answer.status_code == 303, answer.text


# --- nothing is visible without signing in ----------------------------------------


@pytest.mark.parametrize("path", ["/", "/bo/r_web", "/anh/bat_ky.png"])
def test_every_page_sends_a_stranger_to_the_sign_in(client: TestClient, path: str) -> None:
    # The property the whole thing rests on. A dashboard opens every run, every
    # finding and every table to whoever reaches the port.
    answer = client.get(path)
    assert answer.status_code == 303
    assert answer.headers["location"] == "/dang-nhap"


def test_approving_without_signing_in_changes_nothing(client: TestClient) -> None:
    # Reading is one thing; a stranger who can approve a gate can make the
    # system act.
    answer = client.post("/bo/r_web/duyet", data={"gate_id": "g", "chon": "x"})
    assert answer.status_code == 303
    assert answer.headers["location"] == "/dang-nhap"


def test_a_wrong_password_gets_in_nowhere(client: TestClient) -> None:
    answer = client.post("/dang-nhap", data={"password": "sai roi"})
    assert answer.status_code == 401
    assert SESSION_COOKIE not in answer.cookies


def test_the_right_password_gets_a_session(client: TestClient) -> None:
    sign_in(client)
    assert client.get("/").status_code == 200


def test_signing_out_ends_the_session(client: TestClient) -> None:
    sign_in(client)
    assert client.post("/dang-xuat").status_code == 303
    assert client.get("/").headers["location"] == "/dang-nhap"


# --- the password itself -----------------------------------------------------------


def test_no_password_configured_means_no_dashboard() -> None:
    # Refusing to start is the point. One that comes up without a password
    # would expose everything, and nobody would be told.
    with pytest.raises(AuthError) as refused:
        stored_credential({})
    assert "asys set-password" in str(refused.value)


def test_a_plaintext_password_in_the_env_is_refused() -> None:
    # The likely mistake, and it must not quietly become a password nobody can
    # use rather than an error somebody can read.
    with pytest.raises(AuthError) as refused:
        stored_credential({"ASYS_PASSWORD_HASH": "mat khau cua toi"})
    assert "khong dung dinh dang" in str(refused.value)


def test_a_short_password_is_refused() -> None:
    with pytest.raises(AuthError):
        hash_password("ngan")


def test_the_stored_form_round_trips() -> None:
    # The bug this caught on the way in: a fresh salt for the stored field and
    # another for the digest, so no password on earth would have matched.
    credential = hash_password(PASSWORD)
    reread = stored_credential({"ASYS_PASSWORD_HASH": credential.encoded()})
    assert reread.matches(PASSWORD)
    assert not reread.matches(PASSWORD + "x")


# --- what the pages show ------------------------------------------------------------


def test_the_home_page_lists_the_runs(client: TestClient) -> None:
    sign_in(client)
    body = client.get("/").text
    assert "r_web" in body


def test_a_run_that_does_not_exist_says_so(client: TestClient) -> None:
    sign_in(client)
    assert client.get("/bo/khong_co").status_code == 404


def test_a_chart_name_cannot_walk_out_of_the_artifacts_layer(client: TestClient) -> None:
    # A name arriving from a URL must never address a file outside the one
    # directory it is allowed to.
    sign_in(client)
    assert client.get("/anh/..%2F..%2Fetc%2Fpasswd").status_code == 404


def test_data_is_escaped_before_it_reaches_the_page() -> None:
    # Run ids, column names and findings all originate outside this system.
    assert safe("<script>alert(1)</script>") == "&lt;script&gt;alert(1)&lt;/script&gt;"


def test_the_stored_form_survives_being_read_by_a_shell() -> None:
    """`.env` is loaded with `. ./.env`, so the value passes through a shell.

    Written with a dollar sign between salt and hash first. The shell read
    `abc$def` as a variable reference, expanded it to nothing, and the
    dashboard refused a password that was correct. Found by using it, not by
    reading it.
    """
    encoded = hash_password(PASSWORD).encoded()
    assert "$" not in encoded
    assert encoded.count(":") == 1


# --- luong lam viec: tai len, duyet, hoi ------------------------------------------


@pytest.mark.parametrize("path", ["/tai-len", "/bo/r_web/duyet", "/bo/r_web/hoi"])
def test_no_stranger_can_make_the_system_act(client: TestClient, path: str) -> None:
    # Reading is one thing. Uploading a file, approving cleaning or asking a
    # question all make the system DO something, and each has its own route.
    answer = client.post(path, data={"cau_hoi": "x"})
    assert answer.status_code == 303
    assert answer.headers["location"] == "/dang-nhap"


def test_downloading_the_clean_table_needs_signing_in(client: TestClient) -> None:
    answer = client.get("/tai-ve/r_web")
    assert answer.status_code == 303


def test_the_home_page_offers_somewhere_to_put_a_file(client: TestClient) -> None:
    # The thing the boss asked for and the old dashboard had no room for.
    sign_in(client)
    body = client.get("/").text
    assert "Đưa dữ liệu vào" in body
    assert "type=file" in body


def test_a_dataset_page_has_a_box_to_type_a_question(client: TestClient) -> None:
    # The old dashboard could only show what the terminal had already done.
    sign_in(client)
    body = client.get("/bo/r_web").text
    assert "Hỏi" in body
    assert "name=cau_hoi" in body


def test_an_empty_question_changes_nothing(client: TestClient) -> None:
    sign_in(client)
    answer = client.post("/bo/r_web/hoi", data={"cau_hoi": "   "})
    assert answer.status_code == 303
    assert answer.headers["location"] == "/bo/r_web"


# --- ten do nguoi dung dat -------------------------------------------------------


def test_a_dataset_name_cannot_walk_out_of_its_folder() -> None:
    # The name becomes a run id and part of a file path, so a name with a slash
    # in it is a name pointing outside the directory it belongs to.
    assert "/" not in dataset_name("../../etc/passwd", "x.csv")
    assert dataset_name("../../etc/passwd", "x.csv") == "etc_passwd"


def test_a_blank_name_falls_back_to_the_file_name() -> None:
    assert dataset_name("", "Ban Hang Quy 3.csv") == "ban_hang_quy_3"


def test_a_name_of_nothing_usable_still_produces_one() -> None:
    assert dataset_name("!!!", "###.csv") == "du_lieu"


# --- yeu cau lam sach them -------------------------------------------------------


def test_each_line_becomes_one_cleaning_request() -> None:
    rules = added_rules("trim_whitespace:ten,dia_chi\nnormalize_unicode_nfc:ten")
    assert [rule["rule_id"] for rule in rules] == ["trim_whitespace", "normalize_unicode_nfc"]
    assert rules[0]["columns"] == ("ten", "dia_chi")


def test_a_request_with_no_columns_means_every_column() -> None:
    rules = added_rules("drop_exact_duplicates")
    assert rules[0]["columns"] == ()


def test_blank_lines_are_ignored() -> None:
    assert len(added_rules("\n\n  \ntrim_whitespace:a\n\n")) == 1


def test_nothing_typed_asks_for_nothing() -> None:
    assert added_rules("") == ()
