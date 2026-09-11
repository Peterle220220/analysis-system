"""JSON session API: same cookie, same guard, JSON channel for the Next.js UI.

test_web.py covers the HTML channel. This file covers the JSON twin that a
Next.js front end calls — the two must agree about who is signed in, because
the old and the new interface share one session.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from analysis_system.api import AskReport, PlannedStep, RunReport, Workspace
from analysis_system.services import storage
from analysis_system.settings import LAYER_NAMES, LayerPaths, Settings, load_settings, resolve
from analysis_system.web import app as web_app
from analysis_system.web.app import SESSION_COOKIE, Guard, build
from analysis_system.web.auth import hash_password

PASSWORD = "mot mat khau du dai"


def write_clean_table(settings: Settings) -> None:
    """Put a real cleaner output behind the JSON download contract."""
    run_dir = Path(settings.layers.runs) / "r_web"
    state_path = run_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    moment = datetime.now(UTC).isoformat()
    state["tasks"]["t3_clean"] = {
        "task_id": "t3_clean",
        "agent_id": "a3_cleaner",
        "phase": "OK",
        "attempts": 1,
        "input_hashes": [],
        "params_hash": "0" * 64,
        "output_refs": [
            {
                "path": "clean://r_web.parquet",
                "format": "parquet",
                "content_hash": "c" * 64,
                "schema_version": "1",
            }
        ],
        "metrics": {},
        "error": None,
        "updated_at": moment,
    }
    state["updated_at"] = moment
    state_path.write_text(json.dumps(state), encoding="utf-8")
    storage.write_parquet(
        pd.DataFrame({"name": ["An", "Bình"], "score": [8, 9]}),
        resolve("clean://r_web.parquet", settings),
    )


def write_answered_round(settings: Settings, dataset: str = "r_web") -> str:
    """Put an answer with its citation and chart behind the JSON read path."""
    run_id = f"{dataset}__q1"
    round_dir = Path(settings.layers.runs) / run_id
    round_dir.mkdir(parents=True, exist_ok=True)
    moment = datetime.now(UTC).isoformat()
    answer_ref = f"artifacts://{run_id}_answer.json"
    chart_ref = f"artifacts://{run_id}_claim1.png"
    findings_ref = f"artifacts://{run_id}_t2_findings.json"
    (round_dir / "plan.json").write_text(
        json.dumps({"tasks": [{"task_id": "t", "params": {"question": "Điểm thế nào?"}}]}),
        encoding="utf-8",
    )
    (round_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "phase": "COMPLETED",
                "tasks": {
                    "t_answer": {
                        "task_id": "t_answer",
                        "agent_id": "a9_manager",
                        "phase": "OK",
                        "attempts": 1,
                        "input_hashes": [],
                        "params_hash": "0" * 64,
                        "output_refs": [
                            {
                                "path": answer_ref,
                                "format": "json",
                                "content_hash": "a" * 64,
                                "schema_version": "1",
                            }
                        ],
                        "metrics": {},
                        "error": None,
                        "updated_at": moment,
                    },
                    "t_findings": {
                        "task_id": "t_findings",
                        "agent_id": "a7_analyst",
                        "phase": "OK",
                        "attempts": 1,
                        "input_hashes": [],
                        "params_hash": "0" * 64,
                        "output_refs": [
                            {
                                "path": findings_ref,
                                "format": "json",
                                "content_hash": "b" * 64,
                                "schema_version": "1",
                            }
                        ],
                        "metrics": {},
                        "error": None,
                        "updated_at": moment,
                    },
                },
                "created_at": moment,
                "updated_at": moment,
            }
        ),
        encoding="utf-8",
    )
    artifacts = Path(settings.layers.artifacts)
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / f"{run_id}_answer.json").write_text(
        json.dumps(
            {
                "question": "Điểm thế nào?",
                "summary": "Điểm trung bình là 8,5.",
                "warnings": ["Mẫu nhỏ, cần thận trọng."],
                "unanswered": ["Chưa đủ dữ liệu để kết luận nguyên nhân."],
                "rejected": [
                    "finding[0]: da bo don vi go tay",
                    "finding[1]: con so go truc tiep",
                ],
                "needs": [
                    {
                        "blocked_by": "Chưa có nhóm đủ lớn.",
                        "ask": "Cần thêm dữ liệu theo nhóm.",
                    }
                ],
                "claims": [
                    {
                        "claim": "Điểm trung bình là 8,5.",
                        "metric_keys": ["score.mean"],
                        "evidence_ref": "mart://r_web_t1_out.parquet",
                        "chart_ref": chart_ref,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (artifacts / f"{run_id}_t2_findings.json").write_text(
        json.dumps(
            {
                "source": "mart://r_web_t1_out.parquet",
                "question": "Điểm thế nào?",
                "metrics": [
                    {
                        "key": f"sales.mean.by.month.2026-{month:02d}",
                        "value": float(month * 10),
                        "source": "measured",
                    }
                    for month in range(1, 13)
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (artifacts / f"{run_id}_claim1.png").write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    return run_id


def write_pending_gate(settings: Settings) -> None:
    directory = Path(settings.layers.runs) / "r_web" / "gates"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "gate_t3_clean.json").write_text(
        json.dumps(
            {
                "gate_id": "gate_t3_clean",
                "run_id": "r_web",
                "task_id": "t3_clean",
                "agent_id": "a3_cleaner",
                "title": "Duyệt làm sạch",
                "question": "Chọn quy tắc được phép chạy.",
                "options": [{"option_id": "trim_whitespace", "label": "Cắt khoảng trắng"}],
                "payload": {"da_xem": ["Đã xem 1 dòng."]},
                "result_hash": "abc",
                "created_at": datetime.now(UTC).isoformat(),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


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
    assert dataset.json()["actions"] == {
        "can_ask": False,
        "can_download_clean": False,
        "can_approve": False,
    }

    clean = client.get("/api/datasets/r_web/clean")
    assert clean.status_code == 200
    assert clean.json()["context"] == ""
    assert clean.json()["table"] is None
    assert clean.json()["actions"] == {
        "can_download_clean": False,
        "can_generate_glossary": False,
    }

    status = client.get("/api/datasets/r_web/status")
    assert status.status_code == 200
    assert status.json()["phase"] == "COMPLETED"
    assert status.json()["running"] is False
    assert status.json()["state"]["key"] == "unclean"


def test_round_status_api_is_small_and_dataset_scoped(
    client: TestClient, settings: Settings
) -> None:
    run_id = write_answered_round(settings)
    client.post("/api/session", json={"password": PASSWORD})

    answer = client.get(f"/api/datasets/r_web/rounds/{run_id}/status")

    assert answer.status_code == 200
    assert answer.json() == {
        "dataset_id": "r_web",
        "round_id": run_id,
        "state": {"key": "answered", "label": "1 kết luận."},
        "running": False,
        "gates": [],
    }


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


def test_repeating_an_upload_with_the_same_request_id_replays_the_same_job(
    client: TestClient,
) -> None:
    client.post("/api/session", json={"password": PASSWORD})
    file = {"tep": ("repeat.csv", b"a\n1\n", "text/csv")}
    first = client.post("/api/datasets", files=file, data={"client_request_id": "upload-repeat-1"})
    second = client.post("/api/datasets", files=file, data={"client_request_id": "upload-repeat-1"})
    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json() == first.json()


def test_empty_question_releases_its_request_id(client: TestClient) -> None:
    client.post("/api/session", json={"password": PASSWORD})
    first = client.post(
        "/api/datasets/r_web/ask",
        json={"question": "", "client_request_id": "ask-repeat-1"},
    )
    second = client.post(
        "/api/datasets/r_web/ask",
        json={"question": "", "client_request_id": "ask-repeat-1"},
    )
    assert first.status_code == 400
    assert second.status_code == 400
    assert first.json()["error"]["code"] == "empty_question"
    assert second.json()["error"]["code"] == "empty_question"


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
    assert answer.json()["phase"] == "RUNNING"
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


def test_json_round_keeps_answer_warnings_sources_and_chart_download(
    client: TestClient, settings: Settings
) -> None:
    run_id = write_answered_round(settings)
    client.post("/api/session", json={"password": PASSWORD})

    answer = client.get(f"/api/datasets/r_web/rounds/{run_id}")
    assert answer.status_code == 200
    payload = answer.json()
    assert payload["answer"]["summary"] == "Điểm trung bình là 8,5."
    assert payload["answer"]["warnings"] == ["Mẫu nhỏ, cần thận trọng."]
    assert payload["answer"]["unanswered"] == ["Chưa đủ dữ liệu để kết luận nguyên nhân."]
    assert payload["answer"]["blocked"] == ["finding[1]: con so go truc tiep"]
    assert payload["answer"]["repaired"] == ["finding[0]: da bo don vi go tay"]
    assert payload["answer"]["needs"][0]["ask"] == "Cần thêm dữ liệu theo nhóm."
    assert payload["actions"] == {
        "can_export": True,
        "can_follow_up": True,
        "can_approve": False,
    }
    assert payload["answer"]["claims"][0]["evidence_ref"] == "mart://r_web_t1_out.parquet"
    assert payload["forecast"][0]["name"] == "sales.mean theo month"
    assert payload["forecast"][0]["periods"] == 12

    chart = client.get(f"/api/charts/{quote('r_web__q1_claim1.png', safe='')}")
    assert chart.status_code == 200
    assert chart.headers["content-type"].startswith("image/png")
    assert chart.content.startswith(b"\x89PNG")


def test_json_round_exports_both_supported_formats(client: TestClient, settings: Settings) -> None:
    run_id = write_answered_round(settings)
    client.post("/api/session", json={"password": PASSWORD})

    excel = client.get(f"/api/datasets/r_web/rounds/{run_id}/export/excel")
    word = client.get(f"/api/datasets/r_web/rounds/{run_id}/export/word")
    assert excel.status_code == 200
    assert excel.headers["content-disposition"].endswith(f'filename="{run_id}.xlsx"')
    assert excel.content[:2] == b"PK"
    assert word.status_code == 200
    assert word.headers["content-disposition"].endswith(f'filename="{run_id}.docx"')
    assert word.content[:2] == b"PK"


def test_json_clean_download_and_round_delete_update_disk_state(
    client: TestClient, settings: Settings
) -> None:
    run_id = write_answered_round(settings)
    write_clean_table(settings)
    client.post("/api/session", json={"password": PASSWORD})

    clean = client.get("/api/datasets/r_web/clean.csv")
    assert clean.status_code == 200
    assert "name,score" in clean.content.decode("utf-8-sig")

    deleted = client.post("/api/datasets/r_web/rounds/delete", json={"round_ids": [run_id]})
    assert deleted.status_code == 200
    assert deleted.json() == {"dataset_id": "r_web", "deleted": 1}
    assert not (Path(settings.layers.runs) / run_id).exists()


def test_repeating_approval_replays_without_resuming_twice(
    client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_pending_gate(settings)
    resumed: list[str] = []

    def resume(_space: Workspace, run_id: str) -> RunReport:
        resumed.append(run_id)
        return RunReport(run_id=run_id, status="completed")

    monkeypatch.setattr(Workspace, "resume", resume)
    client.post("/api/session", json={"password": PASSWORD})
    body = {
        "gate_id": "gate_t3_clean",
        "chosen": ["trim_whitespace"],
        "client_request_id": "approve-repeat-1",
    }

    first = client.post("/api/datasets/r_web/approve", json=body)
    second = client.post("/api/datasets/r_web/approve", json=body)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()
    assert resumed == ["r_web"]
    state = json.loads(
        (Path(settings.layers.runs) / "r_web" / "state.json").read_text(encoding="utf-8")
    )
    assert state["gates"]["gate_t3_clean"]["approved"] == ["trim_whitespace"]


def test_json_upload_checks_authentication_before_reading_the_file(client: TestClient) -> None:
    answer = client.post(
        "/api/datasets",
        files={"tep": ("private.csv", b"name\nAn\n", "text/csv")},
        data={"ten": "private"},
    )
    assert answer.status_code == 401
    assert answer.json()["error"]["code"] == "unauthorized"


def test_json_export_rejects_a_round_from_another_dataset(
    client: TestClient, settings: Settings
) -> None:
    run_id = write_answered_round(settings, dataset="r_other")
    client.post("/api/session", json={"password": PASSWORD})

    answer = client.get(f"/api/datasets/r_web/rounds/{run_id}/export/excel")
    assert answer.status_code == 404
    assert answer.json()["error"]["code"] == "export_not_found"


def test_json_chart_rejects_path_traversal_and_non_png(client: TestClient) -> None:
    client.post("/api/session", json={"password": PASSWORD})

    traversal = client.get("/api/charts/..%2Fsecret.png")
    wrong_suffix = client.get("/api/charts/secret.txt")
    assert traversal.status_code == 404
    assert wrong_suffix.status_code == 404
    assert traversal.json()["error"]["code"] == "chart_not_found"


def test_json_delete_refuses_a_round_that_is_still_running(
    client: TestClient, settings: Settings
) -> None:
    run_id = write_answered_round(settings)
    state_path = Path(settings.layers.runs) / run_id / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["phase"] = "RUNNING"
    state["updated_at"] = datetime.now(UTC).isoformat()
    state_path.write_text(json.dumps(state), encoding="utf-8")
    client.post("/api/session", json={"password": PASSWORD})

    answer = client.post("/api/datasets/r_web/rounds/delete", json={"round_ids": [run_id]})
    assert answer.status_code == 409
    assert answer.json()["error"]["code"] == "round_running"
    assert state_path.is_file()


def test_successful_json_ask_writes_lineage_and_replays_retry(
    client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def ask(space: Workspace, dataset: str, question: str) -> AskReport:
        calls.append(question)
        run_id = f"{dataset}__q1"
        round_dir = Path(space.settings.layers.runs) / run_id
        round_dir.mkdir(parents=True, exist_ok=True)
        moment = datetime.now(UTC).isoformat()
        (round_dir / "plan.json").write_text(
            json.dumps({"tasks": [{"task_id": "t", "params": {"question": question}}]}),
            encoding="utf-8",
        )
        (round_dir / "state.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "phase": "HALTED",
                    "tasks": {},
                    "created_at": moment,
                    "updated_at": moment,
                }
            ),
            encoding="utf-8",
        )
        return AskReport(
            round_id=run_id,
            question=question,
            reason="fixture",
            steps=(PlannedStep(task_id="t", agent_id="a9_manager"),),
            run=RunReport(run_id=run_id, status="halted"),
        )

    monkeypatch.setattr(Workspace, "ask", ask)
    client.post("/api/session", json={"password": PASSWORD})
    body = {
        "question": "chia theo nhóm",
        "from": "r_web__q0",
        "claim": "Điểm trung bình",
        "client_request_id": "ask-success-repeat",
    }

    first = client.post("/api/datasets/r_web/ask", json=body)
    second = client.post("/api/datasets/r_web/ask", json=body)
    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json() == first.json()
    assert calls == ["Về kết luận «Điểm trung bình»: chia theo nhóm"]
    lineage = json.loads(
        (Path(settings.layers.runs) / "r_web__q1" / "lineage.json").read_text(encoding="utf-8")
    )
    assert lineage == {"parent": "r_web__q0", "claim": "Điểm trung bình"}


def test_json_ask_request_keys_are_scoped_to_the_dataset(
    client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = Path(settings.layers.runs) / "r_other"
    other.mkdir(parents=True, exist_ok=True)
    moment = datetime.now(UTC).isoformat()
    (other / "state.json").write_text(
        json.dumps(
            {
                "run_id": "r_other",
                "phase": "COMPLETED",
                "tasks": {},
                "created_at": moment,
                "updated_at": moment,
            }
        ),
        encoding="utf-8",
    )
    calls: list[str] = []

    def ask(space: Workspace, dataset: str, question: str) -> AskReport:
        calls.append(dataset)
        run_id = f"{dataset}__q1"
        round_dir = Path(space.settings.layers.runs) / run_id
        round_dir.mkdir(parents=True, exist_ok=True)
        (round_dir / "plan.json").write_text(
            json.dumps({"tasks": [{"task_id": "t", "params": {"question": question}}]}),
            encoding="utf-8",
        )
        (round_dir / "state.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "phase": "HALTED",
                    "tasks": {},
                    "created_at": moment,
                    "updated_at": moment,
                }
            ),
            encoding="utf-8",
        )
        return AskReport(
            round_id=run_id,
            question=question,
            reason="fixture",
            steps=(PlannedStep(task_id="t", agent_id="a9_manager"),),
            run=RunReport(run_id=run_id, status="halted"),
        )

    monkeypatch.setattr(Workspace, "ask", ask)
    client.post("/api/session", json={"password": PASSWORD})
    first = client.post(
        "/api/datasets/r_web/ask",
        json={"question": "cau hoi 1", "client_request_id": "same-key"},
    )
    second = client.post(
        "/api/datasets/r_other/ask",
        json={"question": "cau hoi 2", "client_request_id": "same-key"},
    )
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["round_id"] == "r_web__q1"
    assert second.json()["round_id"] == "r_other__q1"
    assert calls == ["r_web", "r_other"]


# --- tep qua lon -------------------------------------------------------------------
#
# Truoc day tep 11,4 MB bi proxy Next cat o 10 MB, may chu cho phan con lai mai
# khong toi, va trang bao "qua thoi gian cho". Mot tep vuot gioi han phai duoc
# tu choi NGAY, voi mot ly do noi dung nguyen nhan.


def test_a_file_over_the_limit_is_refused_with_a_reason(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(web_app, "MAX_UPLOAD_BYTES", 4)
    client.post("/api/session", json={"password": PASSWORD})
    answer = client.post(
        "/api/datasets",
        files={"tep": ("big.csv", b"a,b\n1,2\n", "text/csv")},
        data={"ten": "big"},
    )
    assert answer.status_code == 413
    assert answer.json()["error"]["code"] == "file_too_large"
    assert "vượt giới hạn" in answer.json()["error"]["message"]


def test_a_refused_file_is_not_written_to_disk(
    client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(web_app, "MAX_UPLOAD_BYTES", 4)
    client.post("/api/session", json={"password": PASSWORD})
    client.post(
        "/api/datasets",
        files={"tep": ("big.csv", b"a,b\n1,2\n", "text/csv")},
        data={"ten": "big"},
    )
    assert not (settings.layers.raw / "big.csv").exists()


def test_a_file_within_the_limit_still_goes_through(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(web_app, "MAX_UPLOAD_BYTES", 1024)
    client.post("/api/session", json={"password": PASSWORD})
    answer = client.post(
        "/api/datasets",
        files={"tep": ("small.csv", b"a,b\n1,2\n", "text/csv")},
        data={"ten": "small"},
    )
    assert answer.status_code == 202


def test_a_stranger_is_refused_before_the_size_is_looked_at(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nguoi la khong duoc biet ca gioi han kich thuoc - lop chan dung truoc."""
    monkeypatch.setattr(web_app, "MAX_UPLOAD_BYTES", 4)
    answer = client.post(
        "/api/datasets",
        files={"tep": ("big.csv", b"a,b\n1,2\n", "text/csv")},
        data={"ten": "big"},
    )
    assert answer.status_code == 401


# --- ban nhap chu giai qua API JSON -------------------------------------------------
#
# Route nay truoc day khong co test nao. No tra mot CHUOI trong khi ban Next cho
# mot MANG; trang goi  tren chuoi, vo o JavaScript, va bao "Khong soan duoc
# chu giai" trong khi model da soan xong du 96 dong.


def _fake_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        Workspace,
        "draft_glossary",
        lambda _self, _dataset: (
            chr(10).join(["Debt ratio % = tỷ lệ nợ", "Bankrupt? = phá sản"]),
            ["x: khong co cot"],
        ),
    )


def test_the_glossary_draft_comes_back_as_a_list_of_lines(
    client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_clean_table(settings)
    _fake_draft(monkeypatch)
    client.post("/api/session", json={"password": PASSWORD})
    answer = client.post("/api/datasets/r_web/glossary-draft", json={})
    assert answer.status_code == 200, answer.text
    assert answer.json()["lines"] == ["Debt ratio % = tỷ lệ nợ", "Bankrupt? = phá sản"]


def test_the_dropped_lines_come_back_too(
    client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_clean_table(settings)
    _fake_draft(monkeypatch)
    client.post("/api/session", json={"password": PASSWORD})
    assert client.post("/api/datasets/r_web/glossary-draft", json={}).json()["dropped"] == [
        "x: khong co cot"
    ]


def test_a_failed_draft_says_why(
    client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ly do phai di toi trang, khong duoc bien thanh mot cau chung chung."""
    from analysis_system.api import ServiceError

    def broken(_self: Workspace, _dataset: str) -> tuple[str, list[str]]:
        raise ServiceError("Chua cau hinh model nao, nen khong soan nhap duoc.")

    write_clean_table(settings)
    monkeypatch.setattr(Workspace, "draft_glossary", broken)
    client.post("/api/session", json={"password": PASSWORD})
    answer = client.post("/api/datasets/r_web/glossary-draft", json={})
    assert answer.status_code == 400
    assert "Chua cau hinh model" in answer.json()["error"]["message"]


def test_a_stranger_cannot_spend_a_model_call(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: list[str] = []
    monkeypatch.setattr(
        Workspace, "draft_glossary", lambda _self, dataset: called.append(dataset) or ("", [])
    )
    assert client.post("/api/datasets/r_web/glossary-draft", json={}).status_code == 401
    assert called == []
