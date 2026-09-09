"""JSON session API: same cookie, same guard, JSON channel for the Next.js UI.

test_web.py covers the HTML channel. This file covers the JSON twin that a
Next.js front end calls — the two must agree about who is signed in, because
the old and the new interface share one session.
"""

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
from analysis_system.web.app import SESSION_COOKIE, Guard, build
from analysis_system.web.auth import hash_password

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
    moment = datetime.now(UTC).isoformat()
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


def test_a_stranger_is_not_signed_in(client: TestClient) -> None:
    answer = client.get("/api/session")
    assert answer.status_code == 200
    assert answer.json() == {"signed_in": False}


def test_a_wrong_password_is_refused_as_json(client: TestClient) -> None:
    answer = client.post("/api/session", json={"password": "sai roi"})
    assert answer.status_code == 401
    assert answer.json() == {"signed_in": False, "error": "Sai mật khẩu."}


def test_a_right_password_opens_a_session(client: TestClient) -> None:
    answer = client.post("/api/session", json={"password": PASSWORD})
    assert answer.status_code == 200
    assert answer.json() == {"signed_in": True}
    # The cookie is the same one the HTML interface uses, so the two channels
    # share a session.
    assert SESSION_COOKIE in answer.headers["set-cookie"]
    assert client.get("/api/session").json() == {"signed_in": True}
    # And the HTML channel sees the same session.
    home = client.get("/")
    assert home.status_code == 200


def test_signing_out_ends_the_session(client: TestClient) -> None:
    client.post("/api/session", json={"password": PASSWORD})
    answer = client.delete("/api/session")
    assert answer.status_code == 200
    assert answer.json() == {"signed_in": False}
    assert client.get("/api/session").json() == {"signed_in": False}
    # The HTML channel is signed out too.
    assert client.get("/").status_code == 303


def test_a_missing_password_is_a_wrong_password(client: TestClient) -> None:
    answer = client.post("/api/session", json={})
    assert answer.status_code == 401


def test_the_json_and_html_channels_share_one_guard(
    client: TestClient,
) -> None:
    # Sign in through the HTML form, then read the state through JSON.
    answer = client.post("/dang-nhap", data={"password": PASSWORD})
    assert answer.status_code == 303
    assert client.get("/api/session").json() == {"signed_in": True}


def test_health_is_available_without_a_session(client: TestClient) -> None:
    answer = client.get("/api/health")
    assert answer.status_code == 200
    assert answer.json() == {"ok": True, "service": "analysis-system"}


def test_read_api_requires_a_session(client: TestClient) -> None:
    answer = client.get("/api/home")
    assert answer.status_code == 401
    assert answer.json()["error"]["code"] == "unauthorized"


def test_read_api_exposes_the_four_main_payloads(client: TestClient) -> None:
    client.post("/api/session", json={"password": PASSWORD})

    home = client.get("/api/home")
    assert home.status_code == 200
    assert home.json()["count"] == 1
    assert home.json()["runs"][0]["run_id"] == "r_web"

    data = client.get("/api/data")
    assert data.status_code == 200
    assert data.json()["datasets"][0]["state"]["key"] == "unclean"

    dashboard = client.get("/api/dashboard")
    assert dashboard.status_code == 200
    assert dashboard.json() == {"material": []}

    system = client.get("/api/system")
    assert system.status_code == 200
    assert {"version", "update", "note", "ok"} <= system.json().keys()


def test_dataset_read_api_exposes_status_and_clean_contract(client: TestClient) -> None:
    client.post("/api/session", json={"password": PASSWORD})

    dataset = client.get("/api/datasets/r_web")
    assert dataset.status_code == 200
    assert dataset.json()["dataset_id"] == "r_web"
    assert dataset.json()["state"]["key"] == "unclean"
    assert dataset.json()["gates"] == []

    clean = client.get("/api/datasets/r_web/clean")
    assert clean.status_code == 200
    assert clean.json()["table"] is None

    status = client.get("/api/datasets/r_web/status")
    assert status.status_code == 200
    assert status.json()["running"] is False
    assert status.json()["state"]["key"] == "unclean"


def test_mutation_api_rejects_empty_question_without_creating_a_round(
    client: TestClient,
    settings: Settings,
) -> None:
    client.post("/api/session", json={"password": PASSWORD})
    answer = client.post("/api/datasets/r_web/ask", json={"question": "   "})
    assert answer.status_code == 400
    assert answer.json()["error"]["code"] == "empty_question"
    assert not any(path.name.startswith("r_web__q") for path in settings.layers.runs.iterdir())


def test_upload_returns_a_running_job_and_persists_the_raw_file(
    client: TestClient,
    settings: Settings,
) -> None:
    client.post("/api/session", json={"password": PASSWORD})
    answer = client.post(
        "/api/datasets",
        files={"tep": ("sales.csv", b"a\n1\n", "text/csv")},
        data={"ten": "sales"},
    )
    assert answer.status_code == 202
    assert answer.json() == {"dataset_id": "sales", "status": "running", "running": True}
    assert (settings.layers.raw / "sales.csv").read_bytes() == b"a\n1\n"


def test_dataset_api_rejects_path_syntax_after_authentication(client: TestClient) -> None:
    client.post("/api/session", json={"password": PASSWORD})
    answer = client.get("/api/datasets/%2e%2e/status")
    assert answer.status_code == 400
    assert answer.json()["error"]["code"] == "invalid_id"


def test_dataset_api_does_not_turn_an_unknown_id_into_an_empty_dataset(
    client: TestClient,
) -> None:
    client.post("/api/session", json={"password": PASSWORD})
    answer = client.get("/api/datasets/no_such_dataset")
    assert answer.status_code == 404
    assert answer.json()["error"]["code"] == "dataset_not_found"


def test_status_reports_a_raw_upload_that_has_not_written_state_yet(
    client: TestClient,
    settings: Settings,
) -> None:
    (settings.layers.raw / "new_dataset.csv").write_text("a\n1\n", encoding="utf-8")
    client.post("/api/session", json={"password": PASSWORD})
    answer = client.get("/api/datasets/new_dataset/status")
    assert answer.status_code == 200
    assert answer.json()["running"] is True
    assert answer.json()["state"]["key"] == "running"


def test_round_approval_has_its_own_dataset_scoped_route(client: TestClient) -> None:
    client.post("/api/session", json={"password": PASSWORD})
    answer = client.post(
        "/api/datasets/r_web/rounds/r_web__q1/approve",
        json={"gate_id": "gate_missing", "chosen": []},
    )
    assert answer.status_code == 404
    assert answer.json()["error"]["code"] == "round_not_found"
