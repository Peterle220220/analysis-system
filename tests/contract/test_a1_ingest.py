"""A1 tests: it must load faithfully, detect honestly, and change nothing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from analysis_system.agents.a1_ingest import IngestAgent, staging_uri_for
from analysis_system.core import storage
from analysis_system.core.settings import LAYER_NAMES, LayerPaths, Settings, load_settings, resolve
from analysis_system.models.base import DataRef, ScopeToken, TaskRequest
from analysis_system.services.ingestion import (
    IngestionError,
    detect_delimiter,
    detect_dialect,
    detect_encoding,
    detect_format,
    detect_header,
)

NOW = datetime(2026, 8, 31, 16, 0, tzinfo=UTC)
MANIFEST_DIR = Path(__file__).resolve().parents[2] / "config" / "manifests"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    roots = {name: tmp_path / name for name in LAYER_NAMES}
    for root in roots.values():
        root.mkdir(parents=True, exist_ok=True)
    return load_settings().model_copy(update={"layers": LayerPaths(**roots)})


def token(params: dict[str, object] | None = None) -> ScopeToken:
    """A token matching the shipped a1_ingest manifest."""
    return ScopeToken(
        run_id="r_ing",
        task_id="t_ingest",
        agent_id="a1_ingest",
        allow_read=("raw://**", "extracted://**"),
        allow_write=("staging://**",),
        allow_tools=("pandas", "pyarrow"),
        params=params or {},
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
    )


def put_raw(settings: Settings, name: str, content: str, encoding: str = "utf-8") -> DataRef:
    """Write a source file into the raw layer and reference it."""
    (settings.layers.raw / name).write_text(content, encoding=encoding, newline="\n")
    return DataRef(path=f"raw://{name}", format="csv", content_hash="a" * 64)


def run(settings: Settings, ref: DataRef, params: dict[str, object] | None = None) -> object:
    agent = IngestAgent(settings, MANIFEST_DIR)
    request = TaskRequest(scope=token(params), input_refs=(ref,), instruction="nap du lieu")
    return agent.run(request, now=NOW)


# --- detection ----------------------------------------------------------------


def test_the_format_comes_from_the_suffix() -> None:
    assert detect_format("a.csv") == "csv"
    assert detect_format("a.PARQUET") == "parquet"
    assert detect_format("a.xlsx") == "xlsx"
    # .xls la "so tinh"; noi dung that (HTML, SpreadsheetML, nhi phan) do storage nhan ra.
    assert detect_format("bao_cao.XLS") == "xlsx"
    assert detect_format("a.jsonl") == "json"


def test_an_unknown_suffix_is_refused_rather_than_guessed() -> None:
    with pytest.raises(IngestionError, match="Khong doc duoc dinh dang"):
        detect_format("bao_cao.docx")


def test_a_byte_order_mark_is_consumed_not_left_in_the_first_column() -> None:
    # Otherwise the first column is named "﻿case_id" and every later
    # reference to case_id silently misses.
    assert detect_encoding("case_id,x\n1,2\n".encode("utf-8-sig")) == "utf-8-sig"


def test_a_file_that_is_not_utf8_still_decodes() -> None:
    # 0xE9 is a valid single byte in the Windows code pages and an invalid
    # start byte in UTF-8, so this is a file that only a fallback can read.
    raw = b"ten,gia\nCaf\xe9,10\n"
    encoding = detect_encoding(raw)
    assert encoding not in {"utf-8", "utf-8-sig"}
    assert raw.decode(encoding).startswith("ten,gia")


def test_plain_ascii_is_read_as_utf8_not_as_a_fallback() -> None:
    assert detect_encoding(b"ten,gia\nCafe,10\n") == "utf-8-sig"


def test_the_delimiter_is_the_one_that_splits_every_line_the_same_way() -> None:
    text = "a;b;c\n1;2;3\n4;5;6\n"
    delimiter, confident = detect_delimiter(text)
    assert delimiter == ";"
    assert confident


def test_a_tab_separated_file_is_recognised() -> None:
    delimiter, confident = detect_delimiter("a\tb\n1\t2\n")
    assert delimiter == "\t"
    assert confident


def test_weak_evidence_is_reported_as_weak() -> None:
    # Ragged lines mean the separator is a guess, and the run should say so.
    _, confident = detect_delimiter("mot dong van xuoi khong co dau phan cach\n")
    assert not confident


def test_a_header_row_is_text_in_every_field() -> None:
    assert detect_header("case_id,price\n1,300\n", ",")


def test_a_first_row_carrying_numbers_is_not_a_header() -> None:
    assert not detect_header("1,300\n2,450\n", ",")


def test_duplicate_names_disqualify_a_header() -> None:
    assert not detect_header("a,a\nx,y\n", ",")


# --- loading ------------------------------------------------------------------


def test_a_csv_is_staged_as_parquet(settings: Settings) -> None:
    ref = put_raw(settings, "nha.csv", "case_id,price\n0012,300000\n0013,450000\n")
    result = run(settings, ref)
    assert result.is_ok, result.error  # type: ignore[attr-defined]
    payload = result.payload  # type: ignore[attr-defined]
    assert payload["rows"] == 2
    assert payload["columns"] == 2
    assert payload["source_format"] == "csv"
    assert payload["delimiter"] == ","
    assert payload["has_header"] is True


def test_nothing_is_reinterpreted_on_the_way_in(settings: Settings) -> None:
    # A leading-zero id read as an integer is destroyed before anyone can decide.
    ref = put_raw(settings, "nha.csv", "case_id,price\n0012,300000.50\n")
    result = run(settings, ref)
    staged = storage.read_parquet(resolve(result.output_refs[0].path, settings))  # type: ignore[attr-defined]
    assert staged.loc[0, "case_id"] == "0012"
    assert staged.loc[0, "price"] == "300000.50"


def test_a_semicolon_file_is_read_with_the_right_separator(settings: Settings) -> None:
    ref = put_raw(settings, "nha.csv", "a;b;c\n1;2;3\n4;5;6\n")
    result = run(settings, ref)
    assert result.payload["columns"] == 3  # type: ignore[attr-defined]
    assert result.payload["delimiter"] == ";"  # type: ignore[attr-defined]


def test_the_staged_file_is_named_after_the_run() -> None:
    assert staging_uri_for("raw://nha.csv", "r_1") == "staging://r_1_nha.parquet"
    # Two runs on two datasets cannot overwrite one another.
    assert staging_uri_for("raw://nha.csv", "r_2") != staging_uri_for("raw://nha.csv", "r_1")


def test_an_explicit_target_is_honoured(settings: Settings) -> None:
    ref = put_raw(settings, "nha.csv", "a,b\n1,2\n")
    result = run(settings, ref, {"target": "staging://ten_rieng.parquet"})
    assert result.output_refs[0].path == "staging://ten_rieng.parquet"  # type: ignore[attr-defined]


def test_json_lines_are_read(settings: Settings) -> None:
    (settings.layers.raw / "log.jsonl").write_text(
        '{"a": 1, "b": "x"}\n{"a": 2, "b": "y"}\n', encoding="utf-8"
    )
    ref = DataRef(path="raw://log.jsonl", format="json", content_hash="b" * 64)
    result = run(settings, ref)
    assert result.is_ok, result.error  # type: ignore[attr-defined]
    assert result.payload["rows"] == 2  # type: ignore[attr-defined]


def test_a_workbook_is_read(settings: Settings) -> None:
    pd.DataFrame({"a": ["1", "2"], "b": ["x", "y"]}).to_excel(
        settings.layers.raw / "so.xlsx", index=False
    )
    ref = DataRef(path="raw://so.xlsx", format="blob", content_hash="c" * 64)
    result = run(settings, ref)
    assert result.is_ok, result.error  # type: ignore[attr-defined]
    assert result.payload["rows"] == 2  # type: ignore[attr-defined]
    assert result.payload["source_format"] == "xlsx"  # type: ignore[attr-defined]


def test_an_html_page_saved_as_xls_is_read_and_its_tables_stacked(settings: Settings) -> None:
    # Bao cao tai tu web: duoi .xls, ben trong la HTML hai bang cung cot quy.
    # Truoc day: UNSUPPORTED_FORMAT, du lieu khong vao duoc he thong.
    def table(title: str, rows: str) -> str:
        return f"<table><tr><th>{title}</th><th>Q1-2026</th><th>Q2-2026</th></tr>{rows}</table>"

    page = (
        '<html xmlns:x="urn:schemas-microsoft-com:office:excel"><body>'
        + table("Kết quả kinh doanh", "<tr><td>Thu nhập lãi</td><td>12990.52</td><td>-</td></tr>")
        + table("Cân đối kế toán", "<tr><td>Tiền mặt</td><td>1070868.78</td><td>0.10</td></tr>")
        + "</body></html>"
    )
    (settings.layers.raw / "bctc.xls").write_text(page, encoding="utf-8")
    ref = DataRef(path="raw://bctc.xls", format="blob", content_hash="e" * 64)
    result = run(settings, ref)
    assert result.is_ok, result.error  # type: ignore[attr-defined]
    assert result.payload["rows"] == 2  # type: ignore[attr-defined]
    assert result.payload["source_format"] == "xlsx"  # type: ignore[attr-defined]
    assert any("xếp chồng" in note for note in result.declined)  # type: ignore[attr-defined]
    staged = storage.read_parquet(settings.layers.staging / "r_ing_bctc.parquet")
    assert staged.iloc[:, 2].tolist() == ["12990.52", "1070868.78"]
    assert staged.iloc[:, 3].tolist() == ["-", "0.10"]


# --- what the manifest forbids ------------------------------------------------


def test_it_cannot_write_back_into_raw(settings: Settings) -> None:
    ref = put_raw(settings, "nha.csv", "a,b\n1,2\n")
    result = run(settings, ref, {"target": "raw://ghi_de.parquet"})
    assert result.status == "BOUNDARY_VIOLATION"  # type: ignore[attr-defined]
    assert not (settings.layers.raw / "ghi_de.parquet").exists()


def test_an_unsupported_format_fails_honestly(settings: Settings) -> None:
    (settings.layers.raw / "hop_dong.docx").write_text("x", encoding="utf-8")
    ref = DataRef(path="raw://hop_dong.docx", format="blob", content_hash="d" * 64)
    result = run(settings, ref)
    assert result.status == "FAILED"  # type: ignore[attr-defined]
    assert result.error.code == "UNSUPPORTED_FORMAT"  # type: ignore[attr-defined]


def test_a_missing_input_is_reported(settings: Settings) -> None:
    agent = IngestAgent(settings, MANIFEST_DIR)
    result = agent.run(TaskRequest(scope=token(), instruction="nap"), now=NOW)
    assert result.status == "FAILED"
    assert result.error is not None
    assert result.error.code == "NO_INPUT"


def test_the_manifest_forbids_a_model(settings: Settings) -> None:
    # A1 must never call one: the spec puts it entirely on the code side.
    agent = IngestAgent(settings, MANIFEST_DIR)
    assert agent.manifest.allow.llm.enabled is False


# --- L89: file toan chu, khong co dong tieu de ---------------------------------

LABELLED = (
    b"i didnt feel humiliated;sadness\n"
    b"im grabbing a minute to post i feel greedy wrong;anger\n"
    b"i am feeling grouchy;anger\n"
    b"ive been feeling a little burdened lately;sadness\n"
    b"i feel so hopeless and damned;sadness\n"
)


def test_a_file_that_is_text_all_the_way_down_has_no_header() -> None:
    # The old test was "a header row is text in every field, a data row carries
    # a number". Every field here is text, so it said header - and the first
    # sentence became a column name while the row disappeared.
    assert detect_dialect(LABELLED).has_header is False


def test_a_value_repeating_in_its_own_column_is_what_gives_it_away() -> None:
    # "sadness" appears again below. No column name does that.
    assert detect_dialect(LABELLED).delimiter == ";"
    assert detect_dialect(LABELLED).has_header is False


def test_a_real_header_is_still_recognised() -> None:
    # The new rule must not start calling ordinary headers data.
    with_header = b"ma_phieu;kenh;gio_xu_ly\nP001;app;24.5\nP002;web;13.0\nP003;app;9.5\n"
    assert detect_dialect(with_header).has_header is True


def test_a_header_whose_name_also_appears_as_a_value_is_still_a_header() -> None:
    # A column called "kenh" holding no value "kenh" is the normal case; the
    # rule only fires when the name itself repeats in its own column.
    tricky = b"kenh;ghi_chu\napp;kenh nay moi\nweb;binh thuong\nzalo;binh thuong\n"
    assert detect_dialect(tricky).has_header is True


def test_a_headerless_file_keeps_every_row_and_gets_neutral_names(tmp_path: Path) -> None:
    # The count is the point: reading this as if it had a header cost a row,
    # silently, and named a column after a sentence.
    path = tmp_path / "nhan.csv"
    path.write_bytes(LABELLED)
    dialect = detect_dialect(LABELLED)
    frame = storage.read_csv(
        path,
        encoding=dialect.encoding,
        delimiter=dialect.delimiter,
        has_header=dialect.has_header,
    )
    assert len(frame) == 5
    assert list(frame.columns) == ["cot_1", "cot_2"]
    assert frame["cot_2"].tolist() == ["sadness", "anger", "anger", "sadness", "sadness"]
