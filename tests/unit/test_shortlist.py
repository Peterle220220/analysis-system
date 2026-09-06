"""Chon chi so nao gui cho model, va noi ra cai nao bi bo.

Loi that da xay ra: bang 25 cot sinh ra 73.096 token dau vao, model tieu het
ngan sach dau ra vao viec can nhac, va tra ve `content: null` voi
`finish_reason: "length"`. Nguoi dung khong nhan duoc gi ngoai mot dong
LLM_FAILED.
"""

from __future__ import annotations

from typing import Any

from analysis_system.services.shortlist import DEFAULT_BUDGET, choose, named_in, rank


def metric(key: str, value: float = 1.0, unit: str = "") -> dict[str, Any]:
    return {"key": key, "value": value, "unit": unit, "source": "x"}


def wide_table(columns: int = 25) -> list[dict[str, Any]]:
    """Mot bang rong: moi cap cot mot tuong quan, moi nhom mot bang so sanh."""
    out = [metric("rows.total", 40.0, "dòng")]
    names = [f"cot_{index}" for index in range(columns)]
    for name in names:
        out.append(metric(f"{name}.mean"))
        for other in names:
            if other != name:
                out.append(metric(f"{name}.corr.with.{other}"))
                for group in range(6):
                    out.append(metric(f"{name}.mean.by.{other}.nhom_{group}"))
    return out


# --- ngan sach ---------------------------------------------------------------------


def test_a_small_table_is_sent_whole_and_says_nothing() -> None:
    # Khong bo gi thi khong co gi de noi.
    metrics = [metric("rows.total"), metric("age.mean")]
    kept, note = choose(metrics, "Tuổi trung bình?")
    assert kept == sorted(metrics, key=lambda item: str(item["key"]))
    assert note == ""


def test_a_wide_table_is_cut_to_the_budget() -> None:
    metrics = wide_table()
    assert len(metrics) > 3_000, "bang thu phai du rong de cham tran"

    kept, note = choose(metrics, "Có gì đáng chú ý?")

    assert len(kept) < len(metrics)
    assert sum(len(str(item)) + 2 for item in kept) <= DEFAULT_BUDGET
    assert note, "bo bot ma khong noi la giau"


def test_what_was_left_out_is_counted_out_loud() -> None:
    """Mot con so vang mat va mot con so khong ai duoc bao trong giong het nhau.

    Do la luat cua ca he thong nay, va no ap dung cho chinh viec cat bot nay.
    """
    metrics = wide_table()
    _, note = choose(metrics, "Có gì đáng chú ý?")
    assert f"{len(metrics):,}" in note
    assert "không được xét" in note


def test_the_total_row_count_always_survives() -> None:
    # `rows.total` la mau so cua moi ty le. Mat no thi moi phan tram deu treo.
    kept, _ = choose(wide_table(), "Có gì đáng chú ý?")
    assert any(item["key"] == "rows.total" for item in kept)


# --- uu tien cot duoc hoi toi -------------------------------------------------------


def test_columns_the_question_names_come_first() -> None:
    metrics = wide_table()
    kept, _ = choose(metrics, "So sánh cot_7 với cot_9 giúp tôi")
    heads = {str(item["key"]).split(".", 1)[0] for item in kept}
    assert "cot_7" in heads
    assert "cot_9" in heads


def test_a_column_named_with_an_underscore_is_recognised() -> None:
    # Nguoi dung go ten cot y nhu no nam trong tep: `Reason_Equity`.
    keys = ["Reason_Equity.count", "Gold.mean", "rows.total"]
    assert named_in("phân tích cột Reason_Equity giúp tôi", keys) == {"Reason_Equity"}


def test_half_a_column_name_still_matches() -> None:
    # "cac cot ly do (Reason_Equity, Reason_Mutual)" - nguoi ta cung hay chi
    # viet mot nua.
    keys = ["Reason_Equity.count"]
    assert named_in("yếu tố equity ảnh hưởng thế nào", keys) == {"Reason_Equity"}


def test_a_question_written_with_diacritics_still_matches_a_plain_column() -> None:
    keys = ["tuoi.mean"]
    assert named_in("độ tuổi trung bình theo tuoi", keys) == {"tuoi"}


def test_a_question_naming_nothing_leaves_the_ordering_to_the_kinds() -> None:
    assert named_in("có gì đáng chú ý không", ["Gold.mean"]) == set()


# --- thu tu -------------------------------------------------------------------------


def test_the_headline_numbers_outrank_the_group_by_group_detail() -> None:
    # Mot cai trung binh chung dang gia hon trung binh cua nhom thu muoi bay.
    assert rank("age.mean", set()) < rank("age.mean.by.city.Hanoi", set())


def test_the_row_count_outranks_everything() -> None:
    assert rank("rows.total", set()) < rank("age.mean", set())


def test_a_column_that_was_asked_about_outranks_a_headline_that_was_not() -> None:
    assert rank("Gold.mean.by.city.Hanoi", {"Gold"}) < rank("age.mean", {"Gold"})


# --- truong hop bien ----------------------------------------------------------------


def test_no_metrics_is_not_a_crash() -> None:
    assert choose([], "câu hỏi") == ([], "")


def test_one_metric_larger_than_the_budget_is_still_sent() -> None:
    # Gui mot chi so qua kho con hon gui rong: mot danh sach rong khong noi gi
    # ca, va model se tra loi bang khong co gi.
    big = metric("x" * 500)
    kept, _ = choose([big], "câu hỏi", budget=10)
    assert kept == [big]


def test_the_list_the_model_sees_is_still_sorted_by_key() -> None:
    # Sap xep o tren chi de CHON; cai model doc van phai de doc.
    kept, _ = choose([metric("z.mean"), metric("a.mean")], "câu hỏi")
    assert [item["key"] for item in kept] == ["a.mean", "z.mean"]
