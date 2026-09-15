"""Ba cho chua hoan chinh, tim ra khi kiem toan lai he thong tren mot lan chay that."""

from __future__ import annotations

from analysis_system.agents.a9_manager import moored_needs
from analysis_system.models.agents import DataNeed, Finding, MetricValue
from analysis_system.services.answer_shape import unanswered_end
from analysis_system.services.findings import (
    rankings,
    render_all,
    strip_known_labels,
    without_doubled_units,
)

QUESTION = "Nhan cam xuc nao chiem ty le cao nhat trong cot_2, va nhan nao thap nhat?"
VOCABULARY = [QUESTION, "cot_2.joy.share_pct", "cot_2.surprise.share_pct"]


def need(ask: str) -> DataNeed:
    return DataNeed(blocked_by="mot loi tu choi that", ask=ask, unlocks="tra loi chinh xac hon")


# --- 1. yeu cau du lieu khong dinh gi toi lan chay ---------------------------------


def test_the_real_unmoored_request_is_refused() -> None:
    # Verbatim from a live run. Asked which emotion label was commonest, the
    # Manager asked for sales data. The refusal it quoted was real, so the
    # existing check let it through - and somebody would have gone and fetched
    # it before finding out it changed nothing.
    kept, notes = moored_needs([need("thêm dữ liệu bán hàng của năm 2024")], VOCABULARY)
    assert kept == ()
    assert any("khong dinh gi toi lan chay nay" in note for note in notes)


def test_a_request_about_this_data_is_kept() -> None:
    asked = need("cung cấp thêm nhãn cảm xúc cho các dòng còn thiếu")
    kept, notes = moored_needs([asked], VOCABULARY)
    assert kept == (asked,)
    assert notes == []


def test_the_check_works_across_a_difference_in_diacritics() -> None:
    # This is why the test is lexical. The semantic scorer refuses to judge when
    # one side carries accents and the other does not - which is right, and is
    # exactly how this arrived: an unaccented question and an accented request.
    kept, _ = moored_needs([need("thêm nhãn cảm xúc")], ["Nhan cam xuc nao cao nhat?"])
    assert len(kept) == 1


def test_nothing_is_filtered_when_the_run_said_nothing() -> None:
    # With no vocabulary there is nothing to be moored to, and filtering on that
    # would throw away every request.
    asked = need("bat ky thu gi")
    assert moored_needs([asked], []) == ((asked,), [])


def test_a_request_about_the_system_rather_than_the_subject_is_kept() -> None:
    # Caught by an existing test, not by reading it back: "khai bao bien giai
    # thich trong tests.regressions" asks for a DECLARATION, not for data. It
    # shares no word with a question about exam results and every word with the
    # refusal it lifts - so a request is moored to that refusal as well.
    asked = DataNeed(
        blocked_by=(
            "a7_analyst khong tu chay hoi quy - chon bien giai thich phai duoc "
            "khai ro trong tests.regressions"
        ),
        ask="khai bao bien giai thich trong tests.regressions",
        unlocks="chay duoc hoi quy",
    )
    kept, notes = moored_needs([asked], ["diem thi phu thuoc vao nhung yeu to gi"])
    assert kept == (asked,)
    assert notes == []


def test_quoting_a_refusal_is_not_a_loophole() -> None:
    # The bad request quotes a real refusal too. What saves the good one is that
    # its own words appear IN that refusal; the bad one's do not.
    asked = DataNeed(
        blocked_by="khong tu de xuat duoc phep kiem nao: bang khong co du cot so",
        ask="thêm dữ liệu bán hàng của năm 2024",
        unlocks="so sanh",
    )
    kept, notes = moored_needs([asked], VOCABULARY)
    assert kept == ()
    assert notes


# --- 4. khoa dua cho model phai la khoa CO THAT ------------------------------------


def counted() -> dict[str, MetricValue]:
    """Chi so dem theo nhan, dung hinh dang compute_metrics sinh ra."""
    return {
        key: MetricValue(key=key, value=value, unit="dong", source="mart://x.parquet")
        for key, value in {
            "cot_2.joy.count": 5361.0,
            "cot_2.anger.count": 2159.0,
            "cot_2.surprise.count": 572.0,
        }.items()
    }


def test_every_ranking_key_is_one_the_metrics_really_have() -> None:
    # The bug: rebuilding a key from family and group is right for
    # `X.mean.by.C.<group>`, where the group is last, and wrong for
    # `C.<group>.count`, where it is in the middle. Joining them gave
    # `cot_2.count.joy` while the metric is `cot_2.joy.count`, so the model was
    # handed keys that do not exist, used them, and had every ranking claim
    # rejected for citing a metric that was never computed.
    metrics = counted()
    for row in rankings(metrics):
        assert row["khoa"] in metrics, row["khoa"]


def test_the_ranking_names_the_right_ends() -> None:
    ranked = {row["xep_hang"]: row["khoa"] for row in rankings(counted())}
    assert ranked["cao nhat"] == "cot_2.joy.count"
    assert ranked["thap nhat"] == "cot_2.surprise.count"


def test_a_group_at_the_end_of_the_key_still_works() -> None:
    # The other shape, which was never broken - kept so a fix to one does not
    # quietly break the other.
    metrics = {
        key: MetricValue(key=key, value=value, source="mart://x.parquet")
        for key, value in {
            "gio.mean.by.nhom.a": 5.0,
            "gio.mean.by.nhom.b": 9.0,
        }.items()
    }
    ranked = {row["xep_hang"]: row["khoa"] for row in rankings(metrics)}
    assert ranked["cao nhat"] == "gio.mean.by.nhom.b"
    assert all(row["khoa"] in metrics for row in rankings(metrics))


# --- 2. cau hoi hai ve, tra loi mot ve ---------------------------------------------


def test_answering_one_end_of_a_two_ended_question_is_said_out_loud() -> None:
    # Measured on a live run: the claim about the highest named the wrong group
    # and was rejected, correctly. Nothing noticed half the question was left
    # standing, so a confident answer arrived to something half asked.
    said = ["Nhan cam xuc surprise chiem ty le thap nhat trong cot_2, voi 3.58 %."]
    shortfall = unanswered_end(QUESTION, said)
    assert "cao nhat" in shortfall
    assert "bo ngo" in shortfall


def test_answering_both_ends_says_nothing() -> None:
    said = [
        "Nhan surprise thap nhat, 3.58 %.",
        "Nhan joy chiem ty le cao nhat, 33.51 %.",
    ]
    assert unanswered_end(QUESTION, said) == ""


def test_a_question_with_one_end_is_left_alone() -> None:
    assert unanswered_end("Nhan nao cao nhat?", ["Nhan joy cao nhat."]) == ""


def test_the_missing_end_is_named_correctly() -> None:
    # Which half is missing has to be right, or the note sends the reader after
    # the wrong thing.
    said = ["Nhan joy chiem ty le cao nhat, 33.51 %."]
    assert "thap nhat" in unanswered_end(QUESTION, said)


# --- 3. don vi go tay sau placeholder -----------------------------------------------


def percent() -> dict[str, MetricValue]:
    return {
        "cot_2.joy.share_pct": MetricValue(
            key="cot_2.joy.share_pct", value=33.51, unit="%", source="mart://x.parquet"
        )
    }


def test_a_redundant_unit_is_tidied_rather_than_costing_the_finding() -> None:
    # Refused at first, on the grounds that trimming means deciding which "%"
    # the sentence meant. That was wrong - the rendered value always carries its
    # unit - and the refusal cost two findings in one run.
    finding = Finding(
        claim_template="Nhan joy chiem {cot_2.joy.share_pct}% tong so.",
        evidence_ref="mart://x.parquet",
    )
    rendered, notes = render_all([finding], percent())
    assert len(rendered) == 1
    assert rendered[0].claim == "Nhan joy chiem 33.51 % tong so."
    assert any("da bo don vi go tay" in note for note in notes)


def test_the_tidying_is_written_down_rather_than_done_in_silence() -> None:
    # A repair nobody is told about is a system quietly rewriting what the model
    # said, which is the thing this module exists to prevent.
    finding = Finding(
        claim_template="Ty le la {cot_2.joy.share_pct}%.", evidence_ref="mart://x.parquet"
    )
    _, notes = render_all([finding], percent())
    assert notes


def test_a_claim_with_no_redundant_unit_is_untouched() -> None:
    template = "Nhan joy chiem {cot_2.joy.share_pct} tong so."
    tidied, changed = without_doubled_units(template, percent())
    assert tidied == template
    assert not changed


def test_a_unit_further_along_the_sentence_is_not_a_duplicate() -> None:
    # Only the unit immediately after the placeholder is redundant. One later in
    # the sentence is part of what the writer meant to say.
    template = "Ty le {cot_2.joy.share_pct} tren tong, con lai la 100 % khac."
    tidied, changed = without_doubled_units(template, percent())
    assert not changed
    assert tidied == template


# --- nhan nhom co chua so, viet bang dau cach --------------------------------------


def age_groups() -> dict[str, MetricValue]:
    """Nguyen van cac khoa da gay ra loi tren lan chay that."""
    return {
        key: MetricValue(key=key, value=1.0, unit="", source="t")
        for key in (
            "Gold.mean.by.age_group.dưới_30",
            "Gold.mean.by.age_group.30_trở_lên",
            "rows.total",
        )
    }


def test_a_group_named_with_spaces_is_still_recognised() -> None:
    """Ca ba model deu bi nem sach ket luan vi mot cho khong khop.

    Nhan trong du lieu la `dưới_30`; model viet "dưới 30" nhu moi nguoi viet
    binh thuong. So 30 lot lai, va cau bi nem voi ly do "go so truc tiep" -
    trong khi no chi dang goi ten mot nhom.
    """
    left = strip_known_labels("Nhóm dưới 30 tuổi đầu tư vào Gold nhiều hơn", age_groups())
    assert "30" not in left


def test_the_underscore_spelling_still_works() -> None:
    # Duong cu khong duoc hong.
    left = strip_known_labels("Nhóm dưới_30 đầu tư nhiều hơn", age_groups())
    assert "30" not in left


def test_a_hyphen_spelling_works_too() -> None:
    left = strip_known_labels("Nhóm dưới-30 đầu tư nhiều hơn", age_groups())
    assert "30" not in left


def test_a_number_that_is_not_a_group_name_is_still_caught() -> None:
    """Ca cai check nay ton tai de bat con so bia ra.

    Noi long de nhan ten nhom KHONG duoc phep noi long cho nhung con so khong
    den tu du lieu.
    """
    left = strip_known_labels("Nhóm dưới 30 tuổi chiếm 62.5 phần trăm", age_groups())
    assert "62.5" in left


def test_a_label_with_no_digits_is_left_alone() -> None:
    # Khong co chu so thi khong lien quan toi luat nay, va dong vao chi lam
    # cau nhan dinh mat chu.
    metrics = {
        "Avenue.Equity.share_pct": MetricValue(
            key="Avenue.Equity.share_pct", value=1.0, unit="%", source="t"
        )
    }
    assert "Equity" in strip_known_labels("Nhóm Equity cao nhất", metrics)
