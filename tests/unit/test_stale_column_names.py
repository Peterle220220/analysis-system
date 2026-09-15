"""Ban sua cach doc ten cot khong quay lai sua nhung bang da nam tren dia.

Bo `bankruptcy_prediction` duoc lam sach luc 09-08, giu nguyen 95 cai ten mang
mot dau cach vo hinh o dau. Ban sua ra doi 09-09 - sau do 11 tieng - va bang cu
van nam nguyen do voi ten cu.

Roi cau hoi khong khop duoc cot, va khong co gi tren man hinh noi hai chuyen do
lai voi nhau. Da mat mot luot chan doan sai vi dung chuyen nay: loi bi quy cho
tang khop chu, trong khi tang do chay dung.

`would_change` hoi mot bo ten: ban hom nay co biet don gi trong day khong.
"""

from __future__ import annotations

import pandas as pd

from analysis_system.domains.data_ingestion.column_names import tidied_names, tidy, would_change

# Dung nhung cai ten that trong tep cua chu he thong.
THAT = [
    "Bankrupt?",
    " ROA(C) before interest and depreciation before interest",
    " Operating Gross Margin",
]


# --- bang cu, ten con thua -----------------------------------------------------


def test_a_leading_space_is_something_today_would_clean() -> None:
    assert would_change([" Operating Gross Margin"])


def test_the_real_table_is_flagged() -> None:
    # 3 ten, 2 mang dau cach thua.
    assert len(would_change(THAT)) == 2


def test_a_clean_table_says_nothing() -> None:
    """Im lang la truong hop thuong gap, va la ly do canh bao con dang doc."""
    assert would_change(["Bankrupt?", "doanh_thu", "nam"]) == []


def test_an_empty_table_says_nothing() -> None:
    assert would_change([]) == []


def test_braces_are_something_today_would_clean() -> None:
    assert would_change(["ty_le_{no}"])


def test_a_duplicate_name_is_something_today_would_clean() -> None:
    assert would_change(["a", "a"])


def test_a_nameless_column_is_something_today_would_clean() -> None:
    assert would_change(["", "b"])


# --- mot luat, hai cho goi ------------------------------------------------------


def test_the_warning_and_the_cleaning_agree() -> None:
    """Hai ban sao cua mot luat la hai cau tra loi dang cho de mau thuan."""
    frame = pd.DataFrame({name: [1] for name in THAT})
    _, ke_lai = tidy(frame)
    assert would_change(THAT) == ke_lai


def test_cleaning_a_flagged_table_leaves_nothing_to_flag() -> None:
    """Don xong thi khong con gi de canh bao - neu khong, canh bao se keu mai."""
    frame = pd.DataFrame({name: [1] for name in THAT})
    tidied, _ = tidy(frame)
    assert would_change(list(tidied.columns)) == []


def test_the_names_come_back_cleaned() -> None:
    names, _ = tidied_names(THAT)
    assert names == [
        "Bankrupt?",
        "ROA(C) before interest and depreciation before interest",
        "Operating Gross Margin",
    ]


def test_a_table_needing_nothing_is_returned_untouched() -> None:
    frame = pd.DataFrame({"a": [1], "b": [2]})
    same, notes = tidy(frame)
    assert notes == []
    assert same is frame
