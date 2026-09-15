"""Khoang trang trong ten khoa khong duoc lam vo mot ket luan dung.

Mot cot ten ` ROA(C) before interest and depreciation before interest` mang mot
dau cach vo hinh o dau. Model phai chep lai DUNG ky tu khong nhin thay do o CA
HAI cho - trong metric_keys va trong placeholder.

Tren mot luot chay that no chep thua mot dau cach, viet `{ ` cho de doc:

    metric_keys khai  ' ROA(C) ... .mean'
    placeholder tim  '  ROA(C) ... .mean'

Ca ket luan bi loai. Doi hoi ay la mot cai bay, khong phai mot lop bao ve.

Chuan hoa thi cai bay bien mat, va KHONG lop chan nao bi noi: sau khi chuan
hoa, khoa van phai khop mot chi so CO THAT thi moi qua.
"""

from __future__ import annotations

import pytest

from analysis_system.models.agents import Finding, MetricValue
from analysis_system.services.findings import render_all, resolve_key, tidy_key

# Nguyen van ten cot cua bo du lieu that.
KHOA = " ROA(C) before interest and depreciation before interest.mean"
DA_DO = {KHOA: MetricValue(key=KHOA, value=0.505, unit="", source="x")}


@pytest.mark.parametrize(
    "viet",
    [
        KHOA,  # dung nguyen van
        " " + KHOA,  # thua mot dau cach - ca da hong that
        "  " + KHOA + "  ",  # thua ca hai dau
        KHOA.strip(),  # thieu dau cach dau
        KHOA.replace(" before", "  before"),  # thua dau cach o giua
    ],
)
def test_a_claim_survives_any_spacing_of_the_key(viet: str) -> None:
    finding = Finding(
        claim_template="ROA trung bình là {" + viet + "}.",
        metric_keys=(KHOA,),
        evidence_ref="mart://x.parquet",
    )
    out, bad = render_all([finding], DA_DO)
    assert out, bad
    assert "0.51" in out[0].claim


def test_the_declaration_may_be_spaced_differently_from_the_placeholder() -> None:
    """Model phai chep dung ky tu vo hinh o CA HAI cho, va lech mot ben la du
    de mat ca ket luan."""
    finding = Finding(
        claim_template="ROA là { " + KHOA + "}.",
        metric_keys=(KHOA.strip(),),
        evidence_ref="mart://x.parquet",
    )
    out, bad = render_all([finding], DA_DO)
    assert out, bad


# --- KHONG lop chan nao bi noi ------------------------------------------------


def test_a_key_that_does_not_exist_is_still_refused() -> None:
    """Sau khi chuan hoa, khoa van phai khop mot chi so CO THAT."""
    finding = Finding(
        claim_template="Giá trị là {khong.co.that}.",
        metric_keys=("khong.co.that",),
        evidence_ref="mart://x.parquet",
    )
    out, bad = render_all([finding], DA_DO)
    assert not out
    assert bad


def test_a_typed_number_is_still_refused() -> None:
    finding = Finding(
        claim_template="ROA trung bình là 0.51.",
        metric_keys=(KHOA,),
        evidence_ref="mart://x.parquet",
    )
    out, bad = render_all([finding], DA_DO)
    assert not out


def test_two_different_keys_do_not_collapse_into_one() -> None:
    """Chuan hoa khoang trang KHONG duoc lam hai khoa khac nhau thanh mot."""
    assert tidy_key("a.mean") != tidy_key("b.mean")
    assert tidy_key(" Debt ratio %.mean") != tidy_key(" ROA(C).mean")


# --- ban than phep tra khoa ---------------------------------------------------


def test_it_finds_the_real_key_behind_a_sloppy_one() -> None:
    assert resolve_key("  " + KHOA, DA_DO) == KHOA


def test_it_returns_nothing_when_there_is_nothing_to_find() -> None:
    assert resolve_key("khong.co.that", DA_DO) is None


def test_an_exact_key_is_returned_unchanged() -> None:
    assert resolve_key(KHOA, DA_DO) == KHOA
