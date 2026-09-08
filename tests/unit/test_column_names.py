"""Don ten cot ngay o cua vao.

Bon loi lien tiep tren bon bo du lieu deu la mot ho: mot gia dinh ve ten cot,
dong cung tu hoi he thong chi duoc thu tren du lieu sach se.

Mot luot do co chu dich chi ra dung hai cho con vo, va ca hai deu la TEN COT -
moi hinh dang bang khac deu da chiu duoc.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from analysis_system.services.column_names import tidy

# --- ba viec, moi viec chua mot loi co that -----------------------------------


def test_a_leading_space_is_cut() -> None:
    """` ROA(A) ...` mang mot dau cach vo hinh o dau, va model phai chep lai
    dung ky tu khong nhin thay do thi con so moi hien ra."""
    frame = pd.DataFrame({" ROA(A) before interest and % after tax": [1.0]})
    tidied, notes = tidy(frame)
    assert list(tidied.columns) == ["ROA(A) before interest and % after tax"]
    assert notes


def test_braces_become_round_brackets() -> None:
    """Placeholder viet bang ngoac nhon, nen mot ten cot chua ngoac nhon thi
    khong tai nao tro toi duoc."""
    tidied, notes = tidy(pd.DataFrame({"col{with}braces": [1.0]}))
    assert list(tidied.columns) == ["col(with)braces"]
    assert notes


def test_duplicate_names_are_pulled_apart() -> None:
    """Hai cot cung ten lam pandas tra ve mot bang con thay vi mot cot, va tang
    thong ke vo voi mot TypeError khong noi gi ve nguyen nhan."""
    frame = pd.DataFrame(np.zeros((3, 2)), columns=["a", "a"])
    tidied, notes = tidy(frame)
    assert list(tidied.columns) == ["a", "a__2"]
    assert any("trùng tên" in note for note in notes)


def test_a_deduplicated_frame_can_be_measured() -> None:
    """Day la ca da vo that. Sau khi don thi tang thong ke chay duoc."""
    from analysis_system.services.metrics import compute_metrics

    frame = pd.DataFrame(np.zeros((40, 2)), columns=["a", "a"])
    tidied, _ = tidy(frame)
    assert compute_metrics(tidied, dimensions=tuple(tidied.columns))


def test_an_empty_name_gets_one() -> None:
    tidied, notes = tidy(pd.DataFrame({"   ": [1.0], "b": [2.0]}))
    assert "cot_1" in list(tidied.columns)
    assert notes


# --- KHONG duoc doi gi khac ---------------------------------------------------


def test_a_name_that_is_already_fine_is_left_exactly_alone() -> None:
    frame = pd.DataFrame({"Bankrupt?": [1], "cons.price.idx": [2.0], "y": ["yes"]})
    tidied, notes = tidy(frame)
    assert list(tidied.columns) == ["Bankrupt?", "cons.price.idx", "y"]
    assert notes == []


def test_case_and_spaces_inside_the_name_are_kept() -> None:
    """Ten cot phai giu nguyen de nguoi doc biet dang noi toi muc nao trong tep
    cua ho."""
    frame = pd.DataFrame({"Doanh thu (triệu đồng)": [1.0], "UPPER lower MiXeD": [2.0]})
    tidied, notes = tidy(frame)
    assert list(tidied.columns) == ["Doanh thu (triệu đồng)", "UPPER lower MiXeD"]
    assert notes == []


def test_vietnamese_accents_are_kept() -> None:
    tidied, notes = tidy(pd.DataFrame({"cột_tiếng_việt_có_dấu": [1.0]}))
    assert list(tidied.columns) == ["cột_tiếng_việt_có_dấu"]
    assert notes == []


def test_a_question_mark_is_kept() -> None:
    # `Bankrupt?` dung duoc sau khi placeholder duoc noi rong; khong can doi ten.
    tidied, _ = tidy(pd.DataFrame({"Bankrupt?": [1]}))
    assert list(tidied.columns) == ["Bankrupt?"]


# --- ke lai moi thay doi ------------------------------------------------------


def test_every_change_is_reported() -> None:
    """Doi ten cot trong im lang la chuyen nguoi dung chi phat hien ra khi cau
    hoi cua ho khong khop cot nao."""
    frame = pd.DataFrame({" a ": [1.0], "b{x}": [2.0]})
    _, notes = tidy(frame)
    assert len(notes) == 2


def test_the_data_itself_is_untouched() -> None:
    frame = pd.DataFrame({" a ": [1.0, 2.0, 3.0]})
    tidied, _ = tidy(frame)
    assert list(tidied["a"]) == [1.0, 2.0, 3.0]


def test_an_empty_frame_survives() -> None:
    tidied, notes = tidy(pd.DataFrame())
    assert tidied.empty
    assert notes == []
