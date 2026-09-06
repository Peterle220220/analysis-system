"""Dashboard: khong dang nhap thi khong thay gi, va khong quyet dinh gi o day."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from analysis_system.api import Workspace, _first_sentence
from analysis_system.services import storage
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
from analysis_system.web.render import _round_number, for_operators_only, safe

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


def write_round(settings: Settings, run_id: str, question: str, *, answered: bool) -> None:
    """Mot luot hoi tren dia, co hoac khong co ket qua."""
    round_dir = Path(settings.layers.runs) / run_id
    round_dir.mkdir(parents=True, exist_ok=True)
    (round_dir / "plan.json").write_text(
        json.dumps({"tasks": [{"task_id": "t", "params": {"question": question}}]}),
        encoding="utf-8",
    )
    moment = NOW.isoformat()
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
    (round_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "phase": "COMPLETED" if answered else "HALTED",
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
