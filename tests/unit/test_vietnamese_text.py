"""Chu Viet moi noi mot kieu, va so viet bang chu.

Chu he thong: *"chu, so nhieu khi khong theo quy luat ... tieng Viet co dau,
tieng Viet khong dau"*. Du lieu Kaggle sach nen chuyen nay chua tung lo ra.

Do truoc khi xay, tren dung hinh dang do: mot cot dang le co HAI nhom bi dem
thanh BAY.

    Khách hàng · khach hang · KHÁCH HÀNG · Khách  hàng · Đại lý · dai ly

Va "một", "hai", "ba" khong phai so, nen ca cot bi tu choi.

KHONG CO MOT TU TIENG VIET NAO VIET CUNG trong luat gop bien the - do la yeu
cau chu he thong noi ro: *"'khach hang' chi la 1 vi du nho trong vo van tu cua
tieng Viet"*. Luat khong biet "khach hang" nghia la gi: bo dau, ha chu thuong,
gom khoang trang, hai o nao ra cung mot khoa thi la mot.

Rieng he dem thi phai co danh sach, nhung no la mot TAP DONG - muoi chu so, bon
bac, vai bien the doc trai - dung voi moi bo du lieu chu khong phai tu vung cua
bo nay.
"""

from __future__ import annotations

import pandas as pd

from analysis_system.core.vietnamese_text import (
    best_form,
    canonical_forms,
    number_from_words,
    variant_key,
)
from analysis_system.services.rulebook import RuleSpec, apply_rules

# --- gop bien the: khong mot tu nao duoc viet cung ---------------------------------


def test_diacritics_and_case_and_spacing_meet_at_one_key() -> None:
    keys = {variant_key(form) for form in ("Khách hàng", "khach hang", "KHÁCH HÀNG", "Khách  hàng")}
    assert len(keys) == 1


def test_two_genuinely_different_values_stay_apart() -> None:
    assert variant_key("Khách hàng") != variant_key("Đại lý")


def test_the_rule_works_on_words_it_has_never_seen() -> None:
    """Yeu cau cua chu he thong: moi dang chu, khong phai mot danh sach."""
    changes = canonical_forms(["Nhà cung cấp", "nha cung cap", "NHÀ CUNG CẤP"])
    assert set(changes) == {"nha cung cap", "NHÀ CUNG CẤP"}
    assert set(changes.values()) == {"Nhà cung cấp"}


def test_a_column_already_consistent_is_left_alone() -> None:
    assert canonical_forms(["Hà Nội", "Hà Nội", "Đà Nẵng"]) == {}


def test_empty_values_are_not_merged_together() -> None:
    # Gop cac o rong lai voi nhau la tron nhung o khong lien quan.
    assert canonical_forms(["", "  ", "!!"]) == {}


# --- cach viet nao duoc giu lam ten hien thi ---------------------------------------


def test_the_accented_spelling_wins() -> None:
    """Dau la thong tin MOT CHIEU: bo thi de, dung lai thi khong ai lam duoc."""
    assert best_form({"khach hang": 9, "Khách hàng": 1}) == "Khách hàng"


def test_it_wins_even_when_the_plain_one_is_far_more_common() -> None:
    assert best_form({"khach hang": 500, "Khách hàng": 1}) == "Khách hàng"


def test_all_caps_loses_to_ordinary_case() -> None:
    assert best_form({"KHÁCH HÀNG": 5, "Khách hàng": 1}) == "Khách hàng"


def test_frequency_breaks_a_tie() -> None:
    assert best_form({"Hà Nội": 2, "Hà nội": 7}) == "Hà nội"


def test_the_choice_is_the_same_every_run() -> None:
    counts = {"ha noi": 1, "Ha Noi": 1}
    assert best_form(counts) == best_form(dict(reversed(list(counts.items()))))


# --- so viet bang chu -------------------------------------------------------------


def test_the_plain_digits() -> None:
    assert [number_from_words(word) for word in ("một", "hai", "ba", "bốn")] == [1, 2, 3, 4]


def test_it_reads_undotted_vietnamese_too() -> None:
    # Nguoi nhap lieu go kieu nao cung phai doc duoc.
    assert number_from_words("hai muoi tu") == 24


def test_the_tens() -> None:
    assert number_from_words("mười") == 10
    assert number_from_words("mười lăm") == 15
    assert number_from_words("hai mươi") == 20
    assert number_from_words("hai mươi mốt") == 21


def test_the_hundreds_including_the_gap_word() -> None:
    assert number_from_words("một trăm") == 100
    assert number_from_words("một trăm linh năm") == 105


def test_the_big_scales() -> None:
    assert number_from_words("ba trăm nghìn") == 300_000
    assert number_from_words("một triệu") == 1_000_000
    assert number_from_words("một triệu hai trăm nghìn") == 1_200_000
    assert number_from_words("hai tỷ") == 2_000_000_000


def test_digits_and_words_mixed() -> None:
    assert number_from_words("1 triệu") == 1_000_000


def test_ordinary_text_is_not_a_number() -> None:
    assert number_from_words("khách hàng") is None


def test_a_sentence_containing_a_number_word_is_not_a_number() -> None:
    """Chi doi khi CA O doc len la mot con so."""
    assert number_from_words("một số khách hàng") is None


def test_nothing_is_not_a_number() -> None:
    assert number_from_words("") is None


# --- hai luat chay that -----------------------------------------------------------

BANG = pd.DataFrame(
    {
        "nhom": ["Khách hàng", "khach hang", "KHÁCH HÀNG", "Đại lý", "dai ly", "Đại lý"],
        "so_luong": ["1", "2", "một", "hai mươi mốt", "3", "một trăm"],
        "ten": ["An", "Bình", "Cường", "Dũng", "Em", "Phúc"],
    }
)


def _cleaned() -> tuple[pd.DataFrame, list[str]]:
    outcome = apply_rules(
        BANG,
        [RuleSpec(rule_id="merge_text_variants"), RuleSpec(rule_id="cast_words_to_numbers")],
    )
    return outcome.frame, [
        f"{entry.column}:{entry.before}->{entry.after}"
        for entry in outcome.diff
        if entry.row_index >= 0
    ]


def test_six_spellings_become_two_groups() -> None:
    frame, _ = _cleaned()
    assert sorted(frame["nhom"].unique()) == ["Khách hàng", "Đại lý"]


def test_the_spelled_numbers_become_digits() -> None:
    frame, _ = _cleaned()
    assert list(frame["so_luong"]) == ["1", "2", "1", "21", "3", "100"]


def test_a_column_of_names_is_not_touched() -> None:
    """Ten rieng khong phai bien the cua nhau, va khong phai so."""
    frame, _ = _cleaned()
    assert list(frame["ten"]) == ["An", "Bình", "Cường", "Dũng", "Em", "Phúc"]


def test_every_changed_cell_is_written_down() -> None:
    # Gop nham hai nhom that thanh mot la mat du lieu, nen no phai soi nguoc duoc.
    _, log = _cleaned()
    assert "nhom:khach hang->Khách hàng" in log
    assert "so_luong:một trăm->100" in log


def test_a_gender_column_is_not_read_as_numbers() -> None:
    """`nam` vua la so 5 vua la chu. Mot nua so o khong doc ra so nen bo qua."""
    frame = pd.DataFrame({"gioi_tinh": ["nam", "nữ", "nam", "nữ"]})
    outcome = apply_rules(frame, [RuleSpec(rule_id="cast_words_to_numbers")])
    assert list(outcome.frame["gioi_tinh"]) == ["nam", "nữ", "nam", "nữ"]


def test_a_column_with_one_value_is_not_read_as_numbers() -> None:
    """`nam` lap tu tren xuong duoi nhieu kha nang la chu, khong phai so 5."""
    frame = pd.DataFrame({"gioi_tinh": ["nam", "nam", "nam"]})
    outcome = apply_rules(frame, [RuleSpec(rule_id="cast_words_to_numbers")])
    assert list(outcome.frame["gioi_tinh"]) == ["nam", "nam", "nam"]


def test_a_numeric_column_is_left_to_the_casting_rule() -> None:
    frame = pd.DataFrame({"n": [1.5, 2.5, 3.5]})
    outcome = apply_rules(
        frame,
        [RuleSpec(rule_id="merge_text_variants"), RuleSpec(rule_id="cast_words_to_numbers")],
    )
    assert list(outcome.frame["n"]) == [1.5, 2.5, 3.5]


# --- hai danh sach phai khop nhau -------------------------------------------------


def test_every_registered_rule_is_in_the_running_order() -> None:
    """Mot luat co trong REGISTRY ma thieu o RULE_ORDER se KHONG BAO GIO CHAY.

    Da xay ra that voi dung hai luat nay: dang ky xong, chay khong loi, khong
    doi mot o nao, va khong co gi bao.
    """
    from analysis_system.services.rulebook import REGISTRY, RULE_ORDER

    assert set(REGISTRY) == set(RULE_ORDER)


# --- cot so dang luu dang chu khong phai viec cua luat gop ------------------------


def test_a_negative_number_is_not_merged_into_its_positive() -> None:
    """Bat duoc tren du lieu that: cot  co gia tri am.

    Phep gap bo moi ky tu khong phai chu hay so, nen "-1" va "1" ra cung mot
    khoa. Gop chung lai la MAT DU LIEU, khong phai gop bien the - cot so dang
    luu dang chu la viec cua cast_numeric_safe.
    """
    frame = pd.DataFrame({"kinh_nghiem": ["-1", "1", "2", "-2", "5", "9"]})
    outcome = apply_rules(frame, [RuleSpec(rule_id="merge_text_variants")])
    assert list(outcome.frame["kinh_nghiem"]) == ["-1", "1", "2", "-2", "5", "9"]


def test_the_rule_is_not_even_proposed_for_such_a_column() -> None:
    from analysis_system.services.diagnosis import examine

    frame = pd.DataFrame({"kinh_nghiem": ["-1", "1", "2", "-2", "5", "9"]})
    assert not [f for f in examine(frame).findings if f.rule_id == "merge_text_variants"]


def test_a_real_text_column_is_still_merged() -> None:
    # Chan ca du lieu binh thuong thi phep bao ve khong an toan, chi vo dung.
    frame = pd.DataFrame({"nhom": ["Hà Nội", "ha noi", "Đà Nẵng", "da nang"]})
    outcome = apply_rules(frame, [RuleSpec(rule_id="merge_text_variants")])
    assert sorted(outcome.frame["nhom"].unique()) == ["Hà Nội", "Đà Nẵng"]
