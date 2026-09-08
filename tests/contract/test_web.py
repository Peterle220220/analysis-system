"""Dashboard: khong dang nhap thi khong thay gi, va khong quyet dinh gi o day."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from analysis_system.api import Workspace, _first_sentence
from analysis_system.services import storage
from analysis_system.services.job_error import clear_error, read_error, write_error
from analysis_system.settings import LAYER_NAMES, LayerPaths, Settings, load_settings, resolve
from analysis_system.web.app import (
    SESSION_COOKIE,
    Guard,
    _with_context,
    added_rules,
    build,
    dataset_name,
)
from analysis_system.web.auth import AuthError, hash_password, stored_credential
from analysis_system.web.render import (
    _blocked,
    _risk_banner,
    _round_number,
    for_operators_only,
    safe,
)

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


def test_the_runs_are_listed_on_the_data_page(client: TestClient) -> None:
    """Danh sach nay tung nam o trang chu, va no dai them mot dong moi lan co
    tep moi - voi vai tram bo du lieu thi cho tai len nam ngoai man hinh.

    No chuyen sang muc Data, noi no co cho de dai ra.
    """
    sign_in(client)
    assert "r_web" in client.get("/du-lieu").text


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


# --- ket luan "da xem" ------------------------------------------------------------


def write_gate(
    settings: Settings,
    *,
    examined: list[str],
    gate_id: str = "g1",
    agent_id: str = "a3_cleaner",
    title: str = "HUMAN GATE 1 - duyet rule lam sach",
) -> None:
    """Mot cau hoi nam tren dia, kem thu no da nhin thay."""
    directory = Path(settings.layers.runs) / "r_web" / "gates"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{gate_id}.json").write_text(
        json.dumps(
            {
                "gate_id": gate_id,
                "run_id": "r_web",
                "task_id": "t1",
                "agent_id": agent_id,
                "title": title,
                "question": "Rule nao duoc phep chay?",
                "options": [{"option_id": "trim_whitespace", "label": "Cat khoang trang"}],
                "payload": {"da_xem": examined},
                "result_hash": "abc",
                "created_at": NOW.isoformat(),
            }
        ),
        encoding="utf-8",
    )


def test_nothing_is_ticked_before_a_person_ticks_it(client: TestClient, settings: Settings) -> None:
    # A live run offered six rules, one of which was "cast every column" - on a
    # table whose first column is student_id. Ticked by default, one click would
    # have approved it. The gate exists so that approving is something a person
    # does, not something that happens while they agree to the rest.
    write_gate(settings, examined=["Da xem 4 dong."])
    sign_in(client)

    page = client.get("/bo/r_web").text

    assert "checked" not in page


def test_the_page_says_what_was_looked_at_before_asking_to_approve(
    client: TestClient, settings: Settings
) -> None:
    # The user asked for exactly this: the system must say *where* it wants to
    # clean and *how*, before anybody agrees to anything. An approval form with
    # no account of what was examined is a form asking for a signature on
    # nothing.
    write_gate(settings, examined=["Da xem 4 dong. Cot ten_khach: 2/4 dong thua khoang trang."])
    sign_in(client)

    page = client.get("/bo/r_web").text

    assert "Cot ten_khach: 2/4 dong thua khoang trang." in page


def test_the_examination_outlives_the_approval(settings: Settings) -> None:
    # The verdict used to be printed once, at the terminal, while the run was
    # going. The moment somebody most wants it is later: after cleaning has run,
    # when they ask what was actually done to their data.
    write_gate(settings, examined=["Da xem 4 dong va KHONG thay gi can sua."])
    space = Workspace(settings=settings)

    assert space.examination("r_web") == ("Da xem 4 dong va KHONG thay gi can sua.",)


def test_the_same_verdict_twice_is_read_once(settings: Settings) -> None:
    # A re-run repeats an unchanged verdict word for word. Showing it twice
    # tells nobody anything and reads like two separate findings.
    line = "Da xem 4 dong va KHONG thay gi can sua."
    write_gate(settings, examined=[line], gate_id="g1")
    write_gate(settings, examined=[line], gate_id="g2")

    assert Workspace(settings=settings).examination("r_web") == (line,)


def test_a_run_with_no_gates_examined_nothing(settings: Settings) -> None:
    assert Workspace(settings=settings).examination("r_web") == ()


# --- man duyet phai goi dung ten viec -----------------------------------------------


def test_a_claims_gate_is_not_called_cleaning(client: TestClient, settings: Settings) -> None:
    # Moi gate deu tung hien duoi tieu de "Lam sach", ke ca gate duyet ket luan
    # cua Manager. Nguoi doc mot tieu de noi sai viec ho dang lam thi ho khong
    # duyet, ho doan.
    write_gate(
        settings,
        examined=[],
        agent_id="a9_manager",
        title="DUYET LAP LUAN - cau tra loi cua Manager",
    )
    sign_in(client)

    page = client.get("/bo/r_web").text

    assert "Duyệt kết luận" in page
    assert "Làm sạch — đang chờ bạn" not in page


def test_a_claims_gate_offers_no_cleaning_rule_box(client: TestClient, settings: Settings) -> None:
    # "ten_luat:cot1,cot2" khong co nghia gi o mot gate duyet ket luan, va mot o
    # nhap khong co nghia la mot loi moi go vao do thu gi do.
    write_gate(settings, examined=[], agent_id="a9_manager", title="DUYET LAP LUAN")
    sign_in(client)

    page = client.get("/bo/r_web").text

    assert "tên_luật" not in page
    # Ten cua chinh o nhap do, chu khong phai chu "textarea" - chu do con nam
    # trong CSS cua moi trang, nen kiem no la kiem nham.
    assert "name=them" not in page


def test_a_cleaning_gate_still_offers_the_rule_box(client: TestClient, settings: Settings) -> None:
    # Yeu cau goc cua chu he thong: nguoi dung phai them duoc cach lam sach.
    write_gate(settings, examined=[])
    sign_in(client)

    page = client.get("/bo/r_web").text

    assert "Làm sạch — đang chờ bạn" in page
    assert "tên_luật" in page


# --- gia tri tren form phai den dung noi -------------------------------------------


def test_the_gate_id_on_the_form_reaches_the_handler(
    client: TestClient, settings: Settings
) -> None:
    """Mot loi im lang da lam chet ca dashboard.

    Ba tham so form dung chung MOT doi tuong `Form()` de tranh mot canh bao cua
    linter. FastAPI ghi alias thang vao chinh doi tuong do, nen tat ca cung tro
    toi mot o - o dau tien duoc dang ky, la `password`. `gate_id` vi the luon
    rong, va bam "Dong y va lam sach" chi nhan lai "Khong tim thay gate ''".

    38 test cua trang web deu qua, vi khong cai nao GUI mot gia tri that len roi
    kiem xem no co den noi khong. Bai hoc nam o day, khong phai o ban sua.
    """
    write_gate(settings, examined=[], gate_id="gate_t3_clean")
    sign_in(client)

    client.post(
        "/bo/r_web/duyet",
        data={"gate_id": "gate_t3_clean", "chon": ["trim_whitespace"], "them": ""},
    )

    # Kiem cai da xay ra, khong phai cai da hien ra. Quyet dinh duoc ghi vao
    # state truoc khi chay tiep, nen no co mat o day la bang chung gate_id da
    # den noi. Chay tiep co that bai vi ly do khac cung khong sao.
    state = json.loads((Path(settings.layers.runs) / "r_web" / "state.json").read_text())
    assert "gate_t3_clean" in state["gates"]


def test_the_question_typed_in_the_box_reaches_the_handler(client: TestClient) -> None:
    # Cung mot loi: `cau_hoi` doc o `password` nen luon rong, va go cau hoi vao
    # dashboard thi khong co gi xay ra ca.
    sign_in(client)

    answer = client.post("/bo/r_web/hoi", data={"cau_hoi": "Doanh thu thang nao cao nhat?"})

    # Cau hoi rong quay ve ngay bang 303 ma khong dong den gi. Cau hoi that phai
    # di tiep vao `space.ask` - o day khong co bang sach nen no bao loi, va mot
    # loi la bang chung no DA duoc goi.
    assert answer.status_code != 303, "cau hoi khong den duoc noi xu ly"


def test_the_name_typed_for_a_dataset_reaches_the_handler(client: TestClient) -> None:
    # `ten` cung doc o `password`, nen ten bo du lieu nguoi dung dat bi bo qua
    # va moi thu roi ve ten tep. Khong ai bao ho biet.
    sign_in(client)

    answer = client.post(
        "/tai-len",
        data={"ten": "ban_hang_quy3"},
        files={"tep": ("bat_ky.csv", b"a,b\n1,2\n", "text/csv")},
    )

    assert "bat_ky" not in answer.headers.get("location", "ban_hang_quy3")


# --- moi trang phai noi ro no de lam gi --------------------------------------------


def test_a_round_has_no_page_of_its_own(client: TestClient) -> None:
    # Truoc day co, va no la mot ngo cut: duyet xong bi day toi mot trang chi co
    # moi o nhap cau hoi, khong noi minh la trang gi, khong co cau tra loi vua
    # duyet, khong co duong quay lai. Cuoc hoi dap song o trang bo du lieu.
    sign_in(client)

    answer = client.get("/bo/r_web__q1")

    assert answer.status_code == 303
    assert answer.headers["location"] == "/bo/r_web"


def test_the_dataset_page_says_what_it_is_for(client: TestClient) -> None:
    sign_in(client)
    page_text = client.get("/bo/r_web").text
    assert "đặt câu hỏi" in page_text


def test_the_home_page_says_what_it_is_for(client: TestClient) -> None:
    sign_in(client)
    page_text = client.get("/").text
    assert "Thả một tệp vào đây" in page_text


def test_the_dataset_page_is_titled_by_name_not_by_run_id(client: TestClient) -> None:
    # `finance_data__q1` tren dau trang khong noi gi voi ai.
    sign_in(client)
    page_text = client.get("/bo/r_web").text
    assert "<title>Bộ dữ liệu: r_web</title>" in page_text


# --- cay viec, hoi tiep, va noi ro vi sao khong co cau tra loi --------------------


def test_the_dataset_page_shows_the_tree_on_the_left(client: TestClient) -> None:
    # Mot cuon chat dai vo tan khong cho nguoi doc biet minh dang o dau.
    sign_in(client)
    page_text = client.get("/bo/r_web").text
    assert "class=aside" in page_text
    assert "Dữ liệu sạch" in page_text


def write_round(
    settings: Settings,
    run_id: str,
    question: str,
    *,
    answered: bool,
    phase: str = "",
    now: datetime | None = None,
    measured: dict[str, float] | None = None,
) -> None:
    """Mot luot hoi tren dia: xong, dang chay, hay hong."""
    round_dir = Path(settings.layers.runs) / run_id
    round_dir.mkdir(parents=True, exist_ok=True)
    (round_dir / "plan.json").write_text(
        json.dumps({"tasks": [{"task_id": "t", "params": {"question": question}}]}),
        encoding="utf-8",
    )
    moment = (now or NOW).isoformat()
    uri = f"artifacts://{run_id}_answer.json"
    tasks: dict[str, object] = {}
    if answered:
        # Cau tra loi duoc tim qua output_refs trong state, khong qua ten tep -
        # nen mot fixture chi ghi tep ra dia se khong bao gio duoc doc thay.
        tasks["t_answer"] = {
            "task_id": "t_answer",
            "agent_id": "a9_manager",
            "phase": "OK",
            "attempts": 1,
            "input_hashes": [],
            "params_hash": "0" * 64,
            "output_refs": [
                {"path": uri, "format": "json", "content_hash": "a" * 64, "schema_version": "1"}
            ],
            "metrics": {},
            "error": None,
            "updated_at": moment,
        }
    if answered and measured:
        # Bieu do duoc dung tu chinh cac so A7 do duoc, va chung nam trong
        # artifact `_findings.json` - cung duong `_artifact` di, tuc la qua
        # output_refs chu khong qua ten tep.
        tasks["t2"] = {
            "task_id": "t2",
            "agent_id": "a7_analyst",
            "phase": "OK",
            "attempts": 1,
            "input_hashes": [],
            "params_hash": "0" * 64,
            "output_refs": [
                {
                    "path": f"artifacts://{run_id}_t2_findings.json",
                    "format": "json",
                    "content_hash": "b" * 64,
                    "schema_version": "1",
                }
            ],
            "metrics": {},
            "error": None,
            "updated_at": moment,
        }
    (round_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "phase": phase or ("COMPLETED" if answered else "HALTED"),
                "tasks": tasks,
                "created_at": moment,
                "updated_at": moment,
            }
        ),
        encoding="utf-8",
    )
    if answered:
        Path(settings.layers.artifacts).mkdir(parents=True, exist_ok=True)
        (Path(settings.layers.artifacts) / f"{run_id}_answer.json").write_text(
            json.dumps(
                {
                    "question": question,
                    "claims": [
                        {
                            "claim": "Nam chiếm 62.50 %.",
                            "metric_keys": ["gender.Male.share_pct"],
                            "evidence_ref": "mart://x.parquet",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
    if answered and measured:
        (Path(settings.layers.artifacts) / f"{run_id}_t2_findings.json").write_text(
            json.dumps(
                {
                    "source": "mart://x.parquet",
                    "question": question,
                    "metrics": [
                        {"key": key, "value": value, "source": "share"}
                        for key, value in measured.items()
                    ],
                }
            ),
            encoding="utf-8",
        )


def test_the_dataset_page_lists_analyses_instead_of_dumping_every_answer(
    client: TestClient, settings: Settings
) -> None:
    # Truoc day trang nay in tron moi cau tra loi cua moi luot, noi duoi nhau.
    write_round(settings, "r_web__q1", "Tỷ lệ nam nữ?", answered=True)
    sign_in(client)

    page_text = client.get("/bo/r_web").text

    assert "Các phân tích" in page_text
    assert "Phân tích 1" in page_text
    assert "Tỷ lệ nam nữ?" in page_text


def test_a_round_that_produced_nothing_is_not_numbered_as_an_analysis(
    client: TestClient, settings: Settings
) -> None:
    """Chu he thong dem duoc hai phan tich trong khi chi hoi mot lan.

    Luot thu hai hong o buoc a4_transformer, nhung no dung chung danh sach va
    mang so thu tu cua rieng no, nen no trong y het mot phan tich that.
    """
    write_round(settings, "r_web__q1", "Tỷ lệ nam nữ?", answered=True)
    write_round(settings, "r_web__q2", "Tỷ lệ nam nữ?", answered=False)
    sign_in(client)

    page_text = client.get("/bo/r_web").text

    assert "Phân tích 1" in page_text
    assert "Phân tích 2" not in page_text
    # Van hien ra, chu khong bi giau: giau han thi nguoi ta khong hieu vi sao
    # cau minh vua hoi bien mat.
    assert "1 lượt hỏi không hoàn thành" in page_text


def test_an_analysis_that_does_not_exist_says_so(client: TestClient) -> None:
    sign_in(client)
    assert client.get("/bo/r_web/pt/khong_co").status_code == 404


def test_a_follow_up_carries_the_claim_it_came_from() -> None:
    # Neu khong noi ra thi Manager tra loi mot cau hoi treo lo lung.
    asked = _with_context("chia theo tuổi", "Nam chiếm 62.5 %")
    assert "Nam chiếm 62.5 %" in asked
    assert "chia theo tuổi" in asked


def test_a_plain_question_is_not_dressed_up() -> None:
    assert _with_context("Tỷ lệ nam nữ?", "") == "Tỷ lệ nam nữ?"


# --- dong danh cho nguoi cau hinh, khong danh cho nguoi doc ----------------------


def test_a_line_about_a_config_key_is_not_shown_to_the_reader() -> None:
    """Nguoi dung khong dat duoc 'tests.regressions' tu dashboard.

    Nen voi ho day la mot loi khuyen khong lam theo duoc - va mot dong nhu vay
    nam giua phan ket qua chi lam loang thu that su dang doc.
    """
    assert for_operators_only(
        "Không tự chạy hồi quy — chọn biến giải thích là một nhận định, "
        "phải được khai rõ trong 'tests.regressions'."
    )


def test_a_line_about_the_data_itself_is_still_shown() -> None:
    # Ten cot den tu chinh tep cua nguoi dung. Chu he thong noi ro phai giu:
    # "de nguyen nhu the de user biet ban dang noi toi muc du lieu nao".
    assert not for_operators_only(
        "Equity_Market theo Duration: bỏ qua 2 nhóm có dưới 5 dòng — quá ít để nói gì"
    )
    assert not for_operators_only(
        "Có 28 cặp số có thể đo tương quan, chỉ chạy 8 cặp đầu — càng nhiều phép "
        "kiểm thì càng dễ có p_value nhỏ ra do ngẫu nhiên."
    )


def test_the_hidden_line_is_only_hidden_never_dropped() -> None:
    """An o tang trinh bay, nen du lieu di tiep van day du.

    Chu he thong noi ro hai ve: "khong can hien cho user xem" VA "van se giu lai
    thong tin cho he thong dung luc can". Mot ban sua chi lam ve dau la mot ban
    sua vut mat du lieu.
    """
    from analysis_system.web import render

    source = Path(render.__file__).read_text(encoding="utf-8")
    # Viec loc nam trong ham dung HTML, khong nam trong duong ghi artifact.
    assert "for_operators_only" in source
    assert "for_operators_only" not in Path("src/analysis_system/agents/a9_manager.py").read_text(
        encoding="utf-8"
    )


def test_the_clean_data_has_a_page_of_its_own(client: TestClient) -> None:
    # Truoc day muc "Du lieu sach" trong cay chi la mot cai neo tren cung trang,
    # nen bam vao thi khong co gi thay doi.
    sign_in(client)
    answer = client.get("/bo/r_web/sach")
    assert answer.status_code == 200
    assert "Dữ liệu sạch" in answer.text


def test_the_source_table_is_read_from_the_ingest_step(settings: Settings) -> None:
    """Trang bo du lieu phai cho thay du lieu GOC, khong phai ban sach.

    Truoc day ca hai la mot, nen bam vao "Du lieu sach" o cay ben trai thi
    khong co gi doi.
    """
    run_dir = Path(settings.layers.runs) / "r_goc"
    run_dir.mkdir(parents=True, exist_ok=True)
    storage.write_parquet(
        pd.DataFrame({"ten": ["An", "Bình"], "tuoi": ["25", "30"]}),
        resolve("staging://r_goc_in.parquet", settings),
    )
    moment = NOW.isoformat()
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": "r_goc",
                "phase": "COMPLETED",
                "tasks": {
                    "t1_ingest": {
                        "task_id": "t1_ingest",
                        "agent_id": "a1_ingest",
                        "phase": "OK",
                        "attempts": 1,
                        "input_hashes": [],
                        "params_hash": "0" * 64,
                        "output_refs": [
                            {
                                "path": "staging://r_goc_in.parquet",
                                "format": "parquet",
                                "content_hash": "b" * 64,
                                "schema_version": "1",
                            }
                        ],
                        "metrics": {},
                        "error": None,
                        "updated_at": moment,
                    }
                },
                "created_at": moment,
                "updated_at": moment,
            }
        ),
        encoding="utf-8",
    )

    table = Workspace(settings=settings).staged_table("r_goc")

    assert table is not None
    assert table.rows == 2
    assert table.columns == ("ten", "tuoi")


def test_a_long_model_error_is_cut_down_before_it_reaches_the_page() -> None:
    """Mot loi tu model mang theo nguyen van phan hoi cua no.

    In thang ra thi no chiem tron man hinh va day moi thu khac xuong duoi. Ban
    day du van nam trong state.json, noi nguoi di tim loi can no.
    """
    raw = (
        "Khong tim thay cau tra loi JSON trong phan hoi cua OpenRouter. "
        "Phan hoi day du: " + '{"id": "gen-1788702249"} ' * 200
    )
    short = _first_sentence(raw)
    assert len(short) <= 161
    assert "gen-1788702249" not in short


def test_the_tree_and_the_list_agree_on_how_many_analyses_there_are(
    client: TestClient, settings: Settings
) -> None:
    """Hai cho hien cung mot thu ma quyet dinh rieng thi som muon cung lech.

    Da lech that: toi sua danh sach giua trang cho no thoi danh so luot hong,
    roi de nguyen cay ben trai - nen danh sach noi mot phan tich, cay noi hai,
    tren cung mot man hinh.
    """
    write_round(settings, "r_web__q1", "Tỷ lệ nam nữ?", answered=True)
    write_round(settings, "r_web__q2", "Tỷ lệ nam nữ?", answered=False)
    sign_in(client)

    page_text = client.get("/bo/r_web").text
    aside = page_text.split("<nav class=aside>")[1].split("</nav>")[0]

    # Cay chi liet ke luot ra duoc ket qua, dung nhu danh sach.
    assert aside.count("/pt/r_web__q1") == 1
    assert "/pt/r_web__q2" not in aside
    assert "Phân tích 1" in page_text
    assert "Phân tích 2" not in page_text


def test_a_broken_round_is_still_reachable_from_the_list(
    client: TestClient, settings: Settings
) -> None:
    # Khong hien trong cay khong co nghia la bien mat: nguoi dung van phai den
    # duoc no de biet chuyen gi da xay ra voi cau minh vua hoi.
    write_round(settings, "r_web__q2", "Tỷ lệ nam nữ?", answered=False)
    sign_in(client)

    page_text = client.get("/bo/r_web").text

    assert "1 lượt hỏi không hoàn thành" in page_text
    assert "/pt/r_web__q2" in page_text


def test_the_same_number_means_the_same_analysis_on_both_sides(
    client: TestClient, settings: Settings
) -> None:
    """Cay danh so cu->moi, danh sach danh so moi->cu.

    Cung ba phan tich, hai thu tu nguoc nhau, tren cung mot man hinh: "Phan tich
    1" o hai ben la hai phan tich khac nhau.
    """
    write_round(settings, "r_web__q1", "Câu hỏi cũ nhất", answered=True)
    write_round(settings, "r_web__q2", "Câu hỏi giữa", answered=True)
    write_round(settings, "r_web__q3", "Câu hỏi mới nhất", answered=True)
    sign_in(client)

    page_text = client.get("/bo/r_web").text
    aside = page_text.split("<nav class=aside>")[1].split("</nav>")[0]
    body = page_text.split("</nav>")[1]

    # Cu truoc o ca hai ben.
    assert aside.index("Câu hỏi cũ nhất") < aside.index("Câu hỏi mới nhất")
    assert body.index("Câu hỏi cũ nhất") < body.index("Câu hỏi mới nhất")
    # Va so 1 tro dung vao cai cu nhat.
    assert "1. </span>Câu hỏi cũ nhất" in aside
    assert body.index("Phân tích 1") < body.index("Câu hỏi cũ nhất")


def test_the_numbering_does_not_shift_when_a_new_analysis_arrives(
    client: TestClient, settings: Settings
) -> None:
    # Cu truoc la thu tu dung: hoi them mot cau thi cac so cu giu nguyen. Danh
    # so moi truoc thi moi lan hoi la moi cai ten doi mot lan, va mot ghi chu
    # "xem Phan tich 2" viet hom qua se tro sang cho khac.
    write_round(settings, "r_web__q1", "Câu đầu", answered=True)
    sign_in(client)
    before = client.get("/bo/r_web").text
    assert "<b>Phân tích 1</b> — Câu đầu" in before

    write_round(settings, "r_web__q2", "Câu sau", answered=True)
    after = client.get("/bo/r_web").text

    assert "<b>Phân tích 1</b> — Câu đầu" in after
    assert "<b>Phân tích 2</b> — Câu sau" in after


def test_round_ten_comes_after_round_nine_not_before_it() -> None:
    # So sanh bang chu thi "__q10" dung truoc "__q9".
    order = sorted(["d__q9", "d__q10", "d__q1"], key=_round_number)
    assert order == ["d__q1", "d__q9", "d__q10"]


# --- chi bao dang chay ------------------------------------------------------------


def test_a_running_question_shows_a_moving_indicator(
    client: TestClient, settings: Settings
) -> None:
    """Roi trang trong luc cau hoi dang chay thi mat dau no hoan toan.

    Chi bao doc tu trang thai tren dia, khong tu trinh duyet - nen quay lai
    trang thi no van con, dung nhu luc do cau hoi van dang chay.
    """
    write_round(
        settings,
        "r_web__q1",
        "Tỷ lệ nam nữ?",
        answered=False,
        phase="RUNNING",
        now=datetime.now(UTC),
    )
    sign_in(client)

    page_text = client.get("/bo/r_web").text

    assert "class=spin" in page_text
    assert "Đang xử lý:" in page_text
    # Trang tu cap nhat, do may chu quyet dinh.
    assert "http-equiv=refresh" in page_text


def test_a_running_question_is_not_called_unfinished(
    client: TestClient, settings: Settings
) -> None:
    # No chua xong, nhung "khong hoan thanh" la mot cau noi khac han.
    write_round(
        settings,
        "r_web__q1",
        "Tỷ lệ nam nữ?",
        answered=False,
        phase="RUNNING",
        now=datetime.now(UTC),
    )
    sign_in(client)

    page_text = client.get("/bo/r_web").text

    assert "Đang chạy" in page_text
    assert "lượt hỏi không hoàn thành" not in page_text


def test_the_page_stops_refreshing_when_nothing_is_running(
    client: TestClient, settings: Settings
) -> None:
    # Xong viec thi trang thoi tu tai, khong ai phai nho tat no di.
    write_round(settings, "r_web__q1", "Tỷ lệ nam nữ?", answered=True)
    sign_in(client)

    page_text = client.get("/bo/r_web").text

    assert "http-equiv=refresh" not in page_text
    assert "class=spin" not in page_text


def test_a_run_that_died_hours_ago_is_not_shown_as_running(settings: Settings) -> None:
    """Mot lan chay bi ngat giua chung de lai phase RUNNING vinh vien.

    Mot cai vong xoay quay hoai cho no la mot loi noi doi, va no vua xay ra
    dung nhu vay tren may chu that.
    """
    write_round(
        settings,
        "r_web__q9",
        "Câu cũ",
        answered=False,
        phase="RUNNING",
        now=datetime.now(UTC) - timedelta(hours=3),
    )

    space = Workspace(settings=settings)

    assert space.running("r_web__q9") is False
    assert "dừng giữa chừng" in space.why_stopped("r_web__q9")


# --- ket luan bi chan phai hien ra ------------------------------------------------


class FakeAnswer:
    """Mot cau tra loi da co ket luan bi chan, dung nguyen van ly do that."""

    def __init__(self, rejected: list[str], warnings: list[str] | None = None) -> None:
        self.claims: list[object] = []
        self.unanswered: tuple[str, ...] = ()
        self.needs: tuple[object, ...] = ()
        self.rejected = tuple(rejected)
        self.warnings = tuple(warnings or [])


def test_a_blocked_claim_is_shown_not_swallowed() -> None:
    """Muoi ket luan bi nem di trong bon lan chay, man hinh khong noi mot chu.

    Tu cho nguoi dung ngoi, cau hoi cua ho tu nhien cut mat ba phan tu - va ho
    ket luan la "Manager bo do tac vu". That ra Manager tra loi du, noi sai ba
    lan, va lop kiem duyet xoa ca ba.
    """
    answer = FakeAnswer(
        [
            "finding[2]: cau nhan dinh noi nhom 'Fund_Diversification' la cao nhat trong "
            "'Reason_Mutual.share_pct', nhung nhom cao nhat that su la 'Better_Returns'"
        ]
    )

    html = _blocked(answer)

    assert "Hệ thống đã chặn 1 kết luận" in html
    assert "nói sai so với dữ liệu" in html
    assert "Better_Returns" in html


def test_the_three_reasons_are_told_apart() -> None:
    # Noi sai, khong dan duoc nguon, va lac de la ba chuyen khac han nhau.
    answer = FakeAnswer(
        [
            "finding[0]: nhung nhom cao nhat that su la 'Risk_Free'",
            "finding[1]: cau nhan dinh chua con so go truc tiep - phai la placeholder",
            "finding[2]: loai vi khong tra loi cau hoi (do lien quan 0.19 < 0.25)",
        ]
    )

    html = _blocked(answer)

    assert "nói sai so với dữ liệu" in html
    assert "không dẫn được về chỉ số nào" in html
    assert "không trả lời câu hỏi đã hỏi" in html


def test_it_says_the_blocked_ones_are_not_in_the_answer() -> None:
    # Nguoi doc phai biet ngay day khong phai ket luan cua ho.
    html = _blocked(FakeAnswer(["finding[0]: cau nhan dinh chua con so go truc tiep"]))
    assert "KHÔNG nằm trong câu trả lời" in html


def test_nothing_blocked_shows_nothing() -> None:
    # Khong co gi de noi thi khong noi.
    assert _blocked(FakeAnswer([])) == ""


# --- canh bao do tin cay dat truoc ket luan ---------------------------------------


def test_a_reliability_warning_is_shown_before_the_claims() -> None:
    """Dat sau thi nguoi doc da tin xong roi moi doc toi.

    Nhung dong nay noi "con so duoi day mong toi muc dung tin voi", va biet dieu
    do sau khi da tin la biet muon.
    """
    answer = FakeAnswer([], ["bỏ qua 1 nhóm có dưới 5 dòng — quá ít để nói gì"])

    html = _risk_banner(answer)

    assert "quá ít để nói gì" in html
    assert "mức tin cậy" in html


def test_the_warning_is_not_folded_away() -> None:
    # Mot khoi gap lai thi phan lon khong ai mo.
    html = _risk_banner(FakeAnswer([], ["mẫu quá nhỏ"]))
    assert "<details" not in html


def test_no_warning_shows_nothing() -> None:
    assert _risk_banner(FakeAnswer([])) == ""


def test_a_checkbox_is_not_stretched_across_the_row(client: TestClient) -> None:
    """`width: 100%` ap ca len checkbox lam no gian het dong.

    Trong anh chu he thong gui, o tich roi lech han sang phai, cach xa cai nhan
    no thuoc ve - nguoi dung nhin thay mot o tich lo lung khong biet cua muc
    nao, va do la mot man duyet khong duyet duoc.
    """
    sign_in(client)
    css = client.get("/").text
    assert "input[type=checkbox]" in css
    assert "width: auto" in css


# --- tai len tra trang ngay, lam sach chay nen ------------------------------------


def test_uploading_returns_at_once_instead_of_waiting(client: TestClient) -> None:
    """Truoc day viec lam sach chay NGAY trong request va mat hon bon phut.

    Trinh duyet quay vong vong roi tu bo cuoc, trong khi may chu van dang lam -
    "toi khong biet no co dang chay hay khong". Gio nguoi dung ve thang trang bo
    du lieu va thay chi bao dang chay o do.
    """
    sign_in(client)

    answer = client.post(
        "/tai-len",
        data={"ten": "bo_moi"},
        files={"tep": ("x.csv", b"a,b\n1,2\n", "text/csv")},
    )

    assert answer.status_code == 303
    assert answer.headers["location"] == "/bo/bo_moi"


def test_a_background_failure_is_written_down_not_lost(tmp_path: Path) -> None:
    """Viec chay nen hong o cho khong ai dang nhin.

    Khong con request nao de tra loi ve: `raise` o do chi vao nhat ky may chu,
    noi nguoi dung khong bao gio doc.
    """
    write_error(tmp_path, "Khong doc duoc CSV: dong 3 thieu cot")
    assert "dong 3 thieu cot" in read_error(tmp_path)


def test_a_long_error_is_cut_before_it_reaches_the_page(tmp_path: Path) -> None:
    # Nguoi dung khong doc stack trace. Ban day du van o nhat ky may chu.
    write_error(tmp_path, "x" * 900)
    assert len(read_error(tmp_path)) <= 400


def test_no_error_reads_empty(tmp_path: Path) -> None:
    assert read_error(tmp_path) == ""


def test_retrying_clears_the_old_error(tmp_path: Path) -> None:
    # Khong ai duoc doc phai loi cua lan truoc va tuong la cua lan nay.
    write_error(tmp_path, "loi cu")
    clear_error(tmp_path)
    assert read_error(tmp_path) == ""


def test_the_dataset_page_shows_a_background_failure(
    client: TestClient, settings: Settings
) -> None:
    # Hong o cho khong ai nhin, nhung nguoi dung quay lai thi phai thay.
    write_error(Path(settings.layers.runs) / "r_web", "Khong doc duoc tep: sai dinh dang")
    sign_in(client)

    page_text = client.get("/bo/r_web").text

    assert "Không đọc được tệp" in page_text
    assert "sai dinh dang" in page_text


# --- mang cau tra loi di --------------------------------------------------------


def test_an_answer_can_be_taken_away_as_excel(client: TestClient, settings: Settings) -> None:
    write_round(settings, "r_web__q1", "Tỷ lệ nam nữ?", answered=True)
    sign_in(client)

    got = client.get("/bo/r_web/pt/r_web__q1/tai/excel")

    assert got.status_code == 200
    assert got.content[:2] == b"PK"
    assert "r_web__q1.xlsx" in got.headers["content-disposition"]


def test_an_answer_can_be_taken_away_as_word(client: TestClient, settings: Settings) -> None:
    write_round(settings, "r_web__q1", "Tỷ lệ nam nữ?", answered=True)
    sign_in(client)

    got = client.get("/bo/r_web/pt/r_web__q1/tai/word")

    assert got.status_code == 200
    assert got.content[:2] == b"PK"
    assert "r_web__q1.docx" in got.headers["content-disposition"]


def test_the_page_offers_both_formats(client: TestClient, settings: Settings) -> None:
    write_round(settings, "r_web__q1", "Tỷ lệ nam nữ?", answered=True)
    sign_in(client)

    page_text = client.get("/bo/r_web/pt/r_web__q1").text

    assert "/tai/excel" in page_text
    assert "/tai/word" in page_text


def test_a_stranger_cannot_take_an_answer_away(client: TestClient, settings: Settings) -> None:
    write_round(settings, "r_web__q1", "Tỷ lệ nam nữ?", answered=True)

    got = client.get("/bo/r_web/pt/r_web__q1/tai/excel")

    assert got.status_code == 303
    assert got.headers["location"] == "/dang-nhap"


def test_a_round_belonging_to_another_dataset_is_refused(
    client: TestClient, settings: Settings
) -> None:
    """Mot run_id den tu URL khong duoc doc cau tra loi cua bo khac.

    Doan dung ten mot lan chay khong phai la duoc phep doc no.
    """
    write_round(settings, "r_khac__q1", "Cau hoi cua bo khac", answered=True)
    sign_in(client)

    got = client.get("/bo/r_web/pt/r_khac__q1/tai/excel")

    assert got.status_code == 404


def test_an_unknown_format_is_refused(client: TestClient, settings: Settings) -> None:
    write_round(settings, "r_web__q1", "Tỷ lệ nam nữ?", answered=True)
    sign_in(client)

    assert client.get("/bo/r_web/pt/r_web__q1/tai/pdf").status_code == 404


def test_a_round_with_no_answer_yet_is_refused(client: TestClient, settings: Settings) -> None:
    write_round(settings, "r_web__q1", "Tỷ lệ nam nữ?", answered=False)
    sign_in(client)

    assert client.get("/bo/r_web/pt/r_web__q1/tai/excel").status_code == 404


# --- bieu do ve thang tren trang ------------------------------------------------


DO_DUOC = {
    "gender.Male.share_pct": 62.5,
    "gender.Female.share_pct": 37.5,
}


def test_a_claim_gets_a_chart_drawn_from_the_numbers_behind_it(
    client: TestClient, settings: Settings
) -> None:
    write_round(settings, "r_web__q1", "Ty le nam nu?", answered=True, measured=DO_DUOC)
    sign_in(client)

    page_text = client.get("/bo/r_web/pt/r_web__q1").text

    # Loai bieu do do HINH DANG chi so quyet dinh: mot con so le thi ve mot cot
    # la thua, nen no hien thanh mot so to. Ca bon loai deu mang class "chart".
    assert 'class="chart' in page_text or "class=chart" in page_text
    assert "62.50" in page_text


def test_the_chart_needs_no_javascript_and_no_library(
    client: TestClient, settings: Settings
) -> None:
    """SVG la van ban. Khong mot dong nao tai ve tu dau ca."""
    write_round(settings, "r_web__q1", "Ty le nam nu?", answered=True, measured=DO_DUOC)
    sign_in(client)

    page_text = client.get("/bo/r_web/pt/r_web__q1").text

    assert "<script" not in page_text
    assert "http://" not in page_text


def test_without_measured_numbers_no_chart_is_invented(
    client: TestClient, settings: Settings
) -> None:
    # Ve mot cot khong co so dang sau la bia mot cot.
    write_round(settings, "r_web__q1", "Ty le nam nu?", answered=True)
    sign_in(client)

    assert "<svg " not in client.get("/bo/r_web/pt/r_web__q1").text


# --- uoc luong ky toi: tach han khoi ket luan ---------------------------------


THEO_THANG = {
    f"doanh_thu.mean.by.ngay_ban.2026-{month:02d}": float(month * 10) for month in range(1, 13)
}


def test_a_time_series_gets_an_estimate_of_the_next_period(
    client: TestClient, settings: Settings
) -> None:
    write_round(settings, "r_web__q1", "Doanh thu the nao?", answered=True, measured=THEO_THANG)
    sign_in(client)

    page_text = client.get("/bo/r_web/pt/r_web__q1").text

    assert "Ước lượng kỳ tới" in page_text


def test_the_estimate_never_reads_as_a_measurement(client: TestClient, settings: Settings) -> None:
    """Moi con so phia tren truy nguoc duoc ve mot dong du lieu. Con so nay thi
    truy ve mot duong thang, va nguoi doc phai thay duoc su khac nhau do."""
    write_round(settings, "r_web__q1", "Doanh thu the nao?", answered=True, measured=THEO_THANG)
    sign_in(client)

    page_text = client.get("/bo/r_web/pt/r_web__q1").text

    assert "KHÔNG phải số đo" in page_text


def test_the_estimate_is_a_range_not_a_single_number(
    client: TestClient, settings: Settings
) -> None:
    write_round(settings, "r_web__q1", "Doanh thu the nao?", answered=True, measured=THEO_THANG)
    sign_in(client)

    assert "–" in client.get("/bo/r_web/pt/r_web__q1").text


def test_data_with_no_time_axis_gets_no_estimate_section(
    client: TestClient, settings: Settings
) -> None:
    """Im lang, chu khong phai mot the rong noi "chua co du lieu"."""
    write_round(
        settings,
        "r_web__q1",
        "Ty le nam nu?",
        answered=True,
        measured={"gender.Male.share_pct": 62.5, "gender.Female.share_pct": 37.5},
    )
    sign_in(client)

    assert "Ước lượng kỳ tới" not in client.get("/bo/r_web/pt/r_web__q1").text


def test_a_series_too_short_to_stand_on_gets_no_estimate(
    client: TestClient, settings: Settings
) -> None:
    ngan = {
        f"doanh_thu.mean.by.ngay_ban.2026-{month:02d}": float(month * 10) for month in range(1, 6)
    }
    write_round(settings, "r_web__q1", "Doanh thu the nao?", answered=True, measured=ngan)
    sign_in(client)

    assert "Ước lượng kỳ tới" not in client.get("/bo/r_web/pt/r_web__q1").text


# --- duong ve trang dau ---------------------------------------------------------


def test_every_page_has_a_way_back_to_the_start(client: TestClient, settings: Settings) -> None:
    """Vao mot bo du lieu roi thi ca trang chi con moi nut Dang xuat.

    Muon tai tep khac len phai sua thanh dia chi, hoac dang xuat roi dang nhap
    lai - hai viec khong ai nen phai lam de quay ve trang dau.
    """
    write_round(settings, "r_web__q1", "Ty le nam nu?", answered=True)
    sign_in(client)

    for path in ("/bo/r_web", "/bo/r_web/pt/r_web__q1"):
        page_text = client.get(path).text
        assert "class=brand" in page_text, path
        assert 'href="/"' in page_text, path


def test_the_way_back_is_the_system_name(client: TestClient) -> None:
    sign_in(client)
    assert "Analysis System" in client.get("/").text


def test_the_sign_in_page_names_the_same_system(client: TestClient) -> None:
    # Hai cho viet khac nhau thi nguoi dung tuong la hai he thong.
    assert "Analysis System" in client.get("/dang-nhap").text


# --- thanh dieu huong chinh -----------------------------------------------------


NAV_PATHS = ("/", "/du-lieu", "/bang-dieu-khien")


@pytest.mark.parametrize("path", NAV_PATHS)
def test_each_main_page_opens(client: TestClient, path: str) -> None:
    sign_in(client)
    assert client.get(path).status_code == 200


@pytest.mark.parametrize("path", NAV_PATHS)
def test_no_stranger_reaches_a_main_page(client: TestClient, path: str) -> None:
    answer = client.get(path)
    assert answer.status_code == 303
    assert answer.headers["location"] == "/dang-nhap"


def test_every_page_carries_the_same_three_places(client: TestClient, settings: Settings) -> None:
    """Mot thanh co dinh nghia la o dau cung biet minh dang o dau va di duoc
    sang cho khac - thu ma mot trang don le khong tu cho duoc."""
    write_round(settings, "r_web__q1", "Ty le nam nu?", answered=True)
    sign_in(client)

    for path in (*NAV_PATHS, "/bo/r_web", "/bo/r_web/pt/r_web__q1"):
        page_text = client.get(path).text
        for name in ("Home", "Data", "Dashboard"):
            assert f">{name}</a>" in page_text, f"{path} thieu {name}"


def test_the_page_you_are_on_is_marked(client: TestClient) -> None:
    sign_in(client)
    assert 'href="/du-lieu" class="here"' in client.get("/du-lieu").text


def test_a_dataset_page_counts_as_being_under_data(client: TestClient) -> None:
    # Dung trong mot bo du lieu thi van la dang o muc Data.
    sign_in(client)
    assert 'href="/du-lieu" class="here"' in client.get("/bo/r_web").text


def test_the_data_page_lists_the_datasets(client: TestClient) -> None:
    sign_in(client)
    assert "r_web" in client.get("/du-lieu").text


def test_the_builder_says_it_is_not_built_rather_than_showing_a_blank(
    client: TestClient,
) -> None:
    """Mot trang trong trong y het mot trang hong, va nguoi dung se di tim mot
    nut khong ton tai."""
    sign_in(client)
    assert "Chưa dựng xong" in client.get("/bang-dieu-khien").text


# --- don bot phan tich ----------------------------------------------------------


def _rounds_on_disk(settings: Settings) -> set[str]:
    return {path.name for path in Path(settings.layers.runs).iterdir() if path.is_dir()}


def test_a_chosen_analysis_is_deleted(client: TestClient, settings: Settings) -> None:
    """Mot bo du lieu tich duoc muoi bon phan tich chi sau mot buoi thu, va
    phan lon la rac. Khong co cho don thi danh sach chi dai them mai."""
    write_round(settings, "r_web__q1", "Cau mot", answered=True)
    write_round(settings, "r_web__q2", "Cau hai", answered=True)
    sign_in(client)

    answer = client.post("/bo/r_web/xoa-phan-tich", data={"xoa": "r_web__q1"})

    assert answer.status_code == 303
    left = _rounds_on_disk(settings)
    assert "r_web__q1" not in left
    assert "r_web__q2" in left


def test_several_can_go_at_once(client: TestClient, settings: Settings) -> None:
    write_round(settings, "r_web__q1", "Cau mot", answered=True)
    write_round(settings, "r_web__q2", "Cau hai", answered=True)
    sign_in(client)

    client.post("/bo/r_web/xoa-phan-tich", data={"xoa": ["r_web__q1", "r_web__q2"]})

    left = _rounds_on_disk(settings)
    assert "r_web__q1" not in left
    assert "r_web__q2" not in left


def test_the_dataset_itself_is_never_touched(client: TestClient, settings: Settings) -> None:
    """Xoa mot phan tich khong duoc dung toi du lieu goc hay ban da lam sach."""
    write_round(settings, "r_web__q1", "Cau mot", answered=True)
    sign_in(client)

    client.post("/bo/r_web/xoa-phan-tich", data={"xoa": "r_web__q1"})

    assert "r_web" in _rounds_on_disk(settings)


def test_an_analysis_of_another_dataset_is_refused(client: TestClient, settings: Settings) -> None:
    """Mot ma den tu trinh duyet khong duoc phep xoa thu cua bo khac chi vi no
    doan dung cai ten."""
    write_round(settings, "r_khac__q1", "Cua bo khac", answered=True)
    sign_in(client)

    answer = client.post("/bo/r_web/xoa-phan-tich", data={"xoa": "r_khac__q1"})

    assert answer.status_code == 400
    assert "r_khac__q1" in _rounds_on_disk(settings)


def test_the_dataset_id_itself_cannot_be_passed_as_a_round(
    client: TestClient, settings: Settings
) -> None:
    # `belongings` khop theo tien to, nen xoa bo se cuon theo moi luot hoi -
    # mot viec khac han voi viec nguoi dung dang lam.
    sign_in(client)

    answer = client.post("/bo/r_web/xoa-phan-tich", data={"xoa": "r_web"})

    assert answer.status_code == 400
    assert "r_web" in _rounds_on_disk(settings)


def test_a_running_analysis_is_not_deleted(client: TestClient, settings: Settings) -> None:
    """Xoa mot viec dang chay thi no van chay tiep roi ghi lai thu muc vua bi
    xoa, va cai con lai la mot nua luot chay khong ai doc duoc."""
    write_round(settings, "r_web__q1", "Dang chay", answered=False, phase="RUNNING", now=NOW)
    sign_in(client)

    answer = client.post("/bo/r_web/xoa-phan-tich", data={"xoa": "r_web__q1"})

    assert answer.status_code == 409
    assert "r_web__q1" in _rounds_on_disk(settings)


def test_choosing_nothing_deletes_nothing(client: TestClient, settings: Settings) -> None:
    write_round(settings, "r_web__q1", "Cau mot", answered=True)
    sign_in(client)

    answer = client.post("/bo/r_web/xoa-phan-tich", data={})

    assert answer.status_code == 303
    assert "r_web__q1" in _rounds_on_disk(settings)


def test_a_stranger_cannot_delete_anything(client: TestClient, settings: Settings) -> None:
    write_round(settings, "r_web__q1", "Cau mot", answered=True)

    answer = client.post("/bo/r_web/xoa-phan-tich", data={"xoa": "r_web__q1"})

    assert answer.status_code == 303
    assert answer.headers["location"] == "/dang-nhap"
    assert "r_web__q1" in _rounds_on_disk(settings)


def test_the_tidy_up_form_is_behind_a_fold(client: TestClient, settings: Settings) -> None:
    """Xoa la viec khong lui duoc, nen no phai can mot cu bam de mo ra va mot
    cu nua de lam - chu khong nam canh cho nguoi ta bam hang ngay."""
    write_round(settings, "r_web__q1", "Cau mot", answered=True)
    sign_in(client)

    page_text = client.get("/bo/r_web").text

    assert "Dọn bớt phân tích" in page_text
    assert "<details" in page_text


# --- trang chu khong con om danh sach ------------------------------------------


def test_the_home_page_no_longer_lists_every_run(client: TestClient) -> None:
    """Danh sach do dai them mot dong moi lan co tep moi, va cho tai len bi day
    xuong duoi - voi vai tram bo du lieu thi viec chinh cua trang chu nam ngoai
    man hinh."""
    sign_in(client)

    page_text = client.get("/").text

    assert "Đang làm" not in page_text
    assert "Đưa dữ liệu vào" in page_text


def test_the_home_page_points_at_where_the_list_went(client: TestClient) -> None:
    sign_in(client)
    assert 'href="/du-lieu"' in client.get("/").text


# --- trang he thong va nut cap nhat ---------------------------------------------


def test_the_system_page_opens(client: TestClient) -> None:
    sign_in(client)
    assert client.get("/he-thong").status_code == 200


def test_it_shows_the_running_version(client: TestClient) -> None:
    sign_in(client)
    assert "Bản đang chạy" in client.get("/he-thong").text


def test_it_offers_both_buttons(client: TestClient) -> None:
    """Xem co gi moi va ap dung no la hai viec, nen co hai nut."""
    sign_in(client)
    page_text = client.get("/he-thong").text
    assert "/he-thong/kiem-tra" in page_text
    assert "/he-thong/cap-nhat" in page_text


@pytest.mark.parametrize("path", ["/he-thong", "/he-thong/kiem-tra", "/he-thong/cap-nhat"])
def test_no_stranger_reaches_the_update_controls(client: TestClient, path: str) -> None:
    """Mot nut chay duoc code moi tren may chu la mot cua de chay code tu xa."""
    answer = client.post(path) if path != "/he-thong" else client.get(path)
    assert answer.status_code == 303
    assert answer.headers["location"] == "/dang-nhap"


def test_the_update_button_takes_no_branch_or_remote(client: TestClient) -> None:
    """Khong co o nhap nhanh, nhap remote, nhap gi ca - chi dung nhanh dang
    theo doi cua kho dang chay."""
    sign_in(client)
    page_text = client.get("/he-thong").text
    at = page_text.index("/he-thong/cap-nhat")
    form = page_text[at : at + 300]
    assert "<input" not in form


def test_the_system_page_is_in_the_main_nav(client: TestClient) -> None:
    sign_in(client)
    assert ">Hệ thống</a>" in client.get("/").text
