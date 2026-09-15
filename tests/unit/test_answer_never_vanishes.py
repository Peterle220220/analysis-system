"""Cho duoc doc nhieu nhat trang khong duoc phep trong tron.

Luot chay that, cap do 5: chu he thong hoi *"2 tieu chi nao nen dung dau tien
de canh bao rui ro pha san"*. Model VIET DUNG cau chot can viet, go thang mot
con so vao do, va code bo CA CAU:

    rejected: ["cau chot co con so go truc tiep - moi so phai la placeholder ..."]
    summary:  ""

Roi `_direct_answer` tra ve chuoi rong, nen o "Tra loi" bien mat khong dau vet.
Chu he thong doc xong ket luan la he thong "ne tranh khong dam chot".

Bo cau chot VAN DUNG - mot con so go tay khong truy nguoc duoc ve phep do nao.
Nhung "bo trong im lang" thi khong dung, va do la hai chuyen khac nhau.

Day cung la ly do KHONG chua bang mot luat trong prompt. Chinh du an nay da do:
prompt ghi "tuyet doi khong go so truc tiep" va model van go, nam lan trong bon
luot chay. Model o day khong quen gi ca - no lam dung viec duoc giao, va tang
sau moi la tang danh roi ket qua.
"""

from __future__ import annotations

from analysis_system.domains.ai_planner.direct_answer import MARK, plainly, refusals

GO_SO = "cau chot co con so go truc tiep - moi so phai la placeholder {ten_chi_so}"
LOAI_MOT_LUAN_DIEM = "ket luan 2 dan chi so khong co that: doanh_thu.mean"


# --- nhat lai ly do tu choi ----------------------------------------------------


def test_a_summary_refusal_is_picked_out() -> None:
    assert refusals([GO_SO]) == [GO_SO]


def test_a_rejected_claim_is_not_mistaken_for_one() -> None:
    """Hai chuyen khac nhau, va gop chung thi cau bao noi sai viec."""
    assert refusals([LOAI_MOT_LUAN_DIEM]) == []


def test_the_two_are_told_apart_in_one_list() -> None:
    assert refusals([LOAI_MOT_LUAN_DIEM, GO_SO]) == [GO_SO]


def test_nothing_rejected_means_nothing_picked_out() -> None:
    assert refusals([]) == []


def test_every_refusal_carries_the_mark() -> None:
    """Cach nhat lai dua tren tien to nay, nen tien to phai dung o dau moi ly do."""
    from analysis_system.domains.ai_planner.direct_answer import MAX_LENGTH, problems_with

    rong = problems_with("", {})
    dai = problems_with("x" * (MAX_LENGTH + 1), {})
    bia = problems_with("day la {khong_co_that}", {})
    for reasons in (rong, dai, bia):
        assert reasons
        assert all(reason.startswith(MARK) for reason in reasons)


# --- noi lai bang tieng nguoi ---------------------------------------------------


def test_the_typed_number_reason_is_said_in_plain_words() -> None:
    said = plainly(GO_SO)
    assert "gõ tay" in said
    assert "placeholder" not in said


def test_an_unknown_reason_still_says_something() -> None:
    # Khong duoc tra ve chuoi rong: rong la dung cai loi dang chua.
    assert plainly("cau chot hong theo mot kieu chua tung gap").strip()
