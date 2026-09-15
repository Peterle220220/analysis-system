"""Những luật của tầng web không phụ thuộc giao diện nào.

Giao diện HTML cũ của Python đã bỏ (plans/refactor-ddd.md, quyết định 3); các test gọi
trang HTML của nó đi theo. Còn lại đây là những gì cả giao diện Next vẫn dựa vào: mật
khẩu, tên bộ dữ liệu, yêu cầu làm sạch, câu hỏi tiếp, những dòng chỉ dành cho người cấu
hình, lỗi chạy nền, và những gì Workspace đọc lại từ đĩa. Các route JSON có test riêng
ở test_web_api.py.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from analysis_system.api import Workspace, _first_sentence
from analysis_system.core import storage
from analysis_system.core.job_error import clear_error, read_error, write_error
from analysis_system.core.settings import LAYER_NAMES, LayerPaths, Settings, load_settings, resolve
from analysis_system.web.app import _with_context, added_rules, dataset_name
from analysis_system.web.auth import AuthError, hash_password, stored_credential
from analysis_system.web.state import for_operators_only

NOW = datetime.now(UTC)
PASSWORD = "mot mat khau du dai"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    roots = {name: tmp_path / name for name in LAYER_NAMES}
    for root in roots.values():
        root.mkdir(parents=True, exist_ok=True)
    return load_settings().model_copy(update={"layers": LayerPaths(**roots)})


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


# --- thuat ngu: ma luat trong danh sach "Can sua" -----------------------------------
#
# Chu he thong doc "Can sua: cast_numeric_safe tren ROA(C) ..." va hoi he thong
# dang sua cai gi. Ma luat phai thanh ten tieng Viet.


def test_a_rule_code_in_the_examination_is_said_in_vietnamese(settings: Settings) -> None:
    write_gate(settings, examined=["Cần sửa: cast_numeric_safe trên a, toàn bộ là số"])
    said = Workspace(settings=settings).examination("r_web")[0]
    assert "Chuyển cột đang lưu dạng chữ về dạng số" in said


def test_the_rule_code_is_kept_for_the_operator(settings: Settings) -> None:
    # Ma van con, trong ngoac vuong, de doi chieu voi nhat ky.
    write_gate(settings, examined=["Cần sửa: cast_numeric_safe trên a, toàn bộ là số"])
    assert "[cast_numeric_safe]" in Workspace(settings=settings).examination("r_web")[0]


def test_a_line_without_a_rule_code_is_left_word_for_word(settings: Settings) -> None:
    line = "Da xem 4 dong va KHONG thay gi can sua."
    write_gate(settings, examined=[line])
    assert Workspace(settings=settings).examination("r_web") == (line,)


# --- hoi tiep ve mot ket luan -------------------------------------------------------


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
        "Không tự chạy hồi quy, chọn biến giải thích là một nhận định, "
        "phải được khai rõ trong 'tests.regressions'."
    )


def test_a_line_about_the_data_itself_is_still_shown() -> None:
    # Ten cot den tu chinh tep cua nguoi dung. Chu he thong noi ro phai giu:
    # "de nguyen nhu the de user biet ban dang noi toi muc du lieu nao".
    assert not for_operators_only(
        "Equity_Market theo Duration: bỏ qua 2 nhóm có dưới 5 dòng, quá ít để nói gì"
    )
    assert not for_operators_only(
        "Có 28 cặp số có thể đo tương quan, chỉ chạy 8 cặp đầu, càng nhiều phép "
        "kiểm thì càng dễ có p_value nhỏ ra do ngẫu nhiên."
    )


def test_the_hidden_line_is_only_hidden_never_dropped() -> None:
    """An o tang trinh bay, nen du lieu di tiep van day du.

    Chu he thong noi ro hai ve: "khong can hien cho user xem" VA "van se giu lai
    thong tin cho he thong dung luc can". Mot ban sua chi lam ve dau la mot ban
    sua vut mat du lieu.
    """
    presenting = Path("src/analysis_system/web/state.py").read_text(encoding="utf-8")
    writing = Path("src/analysis_system/agents/a9_manager.py").read_text(encoding="utf-8")
    # Viec loc nam o tang dung JSON cho giao dien, khong nam trong duong ghi artifact.
    assert "for_operators_only" in presenting
    assert "for_operators_only" not in writing


# --- Workspace doc lai tu dia -------------------------------------------------------


def test_the_source_table_is_read_from_the_ingest_step(settings: Settings) -> None:
    """Trang bo du lieu phai cho thay du lieu GOC, khong phai ban sach."""
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


def test_a_run_that_died_hours_ago_is_not_shown_as_running(settings: Settings) -> None:
    """Mot lan chay bi ngat giua chung de lai phase RUNNING vinh vien.

    Mot cai vong xoay quay hoai cho no la mot loi noi doi, va no vua xay ra
    dung nhu vay tren may chu that.
    """
    round_dir = Path(settings.layers.runs) / "r_web__q9"
    round_dir.mkdir(parents=True, exist_ok=True)
    (round_dir / "plan.json").write_text(
        json.dumps({"tasks": [{"task_id": "t", "params": {"question": "Câu cũ"}}]}),
        encoding="utf-8",
    )
    moment = (datetime.now(UTC) - timedelta(hours=3)).isoformat()
    (round_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": "r_web__q9",
                "phase": "RUNNING",
                "tasks": {},
                "created_at": moment,
                "updated_at": moment,
            }
        ),
        encoding="utf-8",
    )

    space = Workspace(settings=settings)

    assert space.running("r_web__q9") is False
    assert "dừng giữa chừng" in space.why_stopped("r_web__q9")


# --- loi chay nen --------------------------------------------------------------------


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
