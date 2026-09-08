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
