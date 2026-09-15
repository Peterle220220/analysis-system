"""Chi so gom thanh ho theo cot.

Dieu kien khong duoc pha: KHOA GIU NGUYEN VEN TUNG KY TU. Model trich khoa ra
de viet `{khoa}`, va mot khoa bi cat ngan hay ghep lai la mot khoa khong ton
tai. Du an nay da tra gia cho dung chuyen do mot lan - khoa ghep lai tu cac
manh cho ra `cot_2.count.joy` trong khi chi so that la `cot_2.joy.count`, va
moi ket luan xep hang bi loai vi dan mot chi so chua tung duoc tinh.
"""

from __future__ import annotations

from typing import Any

from analysis_system.domains.execution_engine.metric_families import LOOSE, family_of, grouped

# Nguyen van dang metrics_view ma A9 dung.
PHANG: list[dict[str, Any]] = [
    {"key": "Source.Internet.share_pct", "value": 25.0, "unit": "%"},
    {"key": "Source.Financial_Consultants.share_pct", "value": 40.0, "unit": "%"},
    {"key": "PPF.mean.by.gender.Male", "value": 1.84, "unit": ""},
    {"key": "PPF.mean.by.gender.Female", "value": 2.33, "unit": ""},
    {"key": "rows.total", "value": 40.0, "unit": "dòng"},
    {"key": "age.mean", "value": 27.8, "unit": ""},
]


def _family(out: list[dict[str, Any]], name: str) -> dict[str, Any]:
    return next(item for item in out if item["cot"] == name)


# --- dieu kien khong duoc pha -------------------------------------------------


def test_every_key_survives_exactly_as_it_was() -> None:
    out = grouped(PHANG)
    seen = [entry["key"] for family in out for entry in family["chi_so"]]
    assert sorted(seen) == sorted(entry["key"] for entry in PHANG)


def test_the_entries_themselves_are_untouched() -> None:
    # Chi xep lai cho ngoi, khong viet lai gi ca.
    out = grouped(PHANG)
    every = [entry for family in out for entry in family["chi_so"]]
    for entry in PHANG:
        assert entry in every


def test_nothing_is_lost_and_nothing_is_added() -> None:
    out = grouped(PHANG)
    assert sum(len(family["chi_so"]) for family in out) == len(PHANG)


# --- gom theo cot -------------------------------------------------------------


def test_a_breakdown_becomes_one_family() -> None:
    out = grouped(PHANG)
    assert len(_family(out, "Source")["chi_so"]) == 2
    assert len(_family(out, "PPF")["chi_so"]) == 2


def test_a_lone_metric_does_not_get_a_family_of_its_own() -> None:
    """Mot ho mot phan tu chi them mot tang ngoac cho nguoi doc."""
    out = grouped(PHANG)
    names = [family["cot"] for family in out]
    assert "rows" not in names
    assert "age" not in names
    assert len(_family(out, LOOSE)["chi_so"]) == 2


def test_the_column_the_question_names_comes_first() -> None:
    out = grouped(PHANG, "kênh thông tin (Source) nào phổ biến nhất")
    assert out[0]["cot"] == "Source"
    assert out[0]["cau_hoi_co_nhac_toi"]


def test_a_column_the_question_never_mentions_is_not_flagged() -> None:
    out = grouped(PHANG, "kênh thông tin (Source) nào phổ biến nhất")
    assert not _family(out, "PPF")["cau_hoi_co_nhac_toi"]


def test_without_a_question_nothing_is_flagged() -> None:
    assert all(not family["cau_hoi_co_nhac_toi"] for family in grouped(PHANG))


def test_the_order_inside_a_family_is_the_order_it_arrived_in() -> None:
    """`shortlist.choose` da xep theo muc quan trong roi. Xep lai lan nua la
    hai cho cung tra loi mot cau hoi."""
    out = grouped(PHANG)
    assert [entry["key"] for entry in _family(out, "Source")["chi_so"]] == [
        "Source.Internet.share_pct",
        "Source.Financial_Consultants.share_pct",
    ]


def test_nothing_in_means_nothing_out() -> None:
    assert grouped([]) == []


def test_the_family_of_a_key_is_its_first_segment() -> None:
    assert family_of("Source.Internet.share_pct") == "Source"
    assert family_of("rows.total") == "rows"
    assert family_of("") == LOOSE
