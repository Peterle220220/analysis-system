"""Bieu do ve thang bang SVG, khong them thu vien nao.

Hai dieu kien khong duoc pha:

* thang do chay tu 0 - cat goc lam mot chenh lech 2 % trong nhu gap doi, va do
  la cach ve mot bieu do noi doi ma khong co con so nao sai;
* nhan va gia tri den tu chinh metric key da do, khong qua tay model.
"""

from __future__ import annotations

import re

import pytest

from analysis_system.services.svg_chart import MAX_BARS, bar_svg, pairs_from

CAP = [("Financial_Consultants", 40.0), ("Newspapers", 25.0), ("Internet", 12.5)]


def _widths(svg: str) -> list[float]:
    return [float(found) for found in re.findall(r'<rect [^>]*width="([\d.]+)"', svg)]


# --- thang do chay tu 0 -------------------------------------------------------


def test_the_scale_starts_at_zero() -> None:
    """Gia tri 12.5 tren 40 phai ra dung mot phan ba be ngang, khong phai mot vach."""
    widths = _widths(bar_svg(CAP))
    # Dung sai la cho lam tron mot chu so thap phan luc in toa do, khong phai
    # cho cach tinh: 12.5 tren 40 phai ra dung mot phan ba be ngang.
    assert widths[2] / widths[0] == pytest.approx(12.5 / 40.0, abs=1e-3)


def test_the_largest_value_fills_the_plot() -> None:
    widths = _widths(bar_svg(CAP))
    assert widths[0] == max(widths)


def test_a_zero_value_draws_no_bar() -> None:
    assert _widths(bar_svg([("a", 0.0), ("b", 10.0)]))[0] == 0.0


def test_every_value_being_zero_does_not_divide_by_zero() -> None:
    assert bar_svg([("a", 0.0), ("b", 0.0)])


# --- khong ve cai gi khong co so dang sau -------------------------------------


def test_a_key_with_no_measured_value_is_left_out() -> None:
    """Ve mot cot khong co so dang sau la bia mot cot."""
    found = pairs_from(
        {"Source.Internet.share_pct": 12.5}, ["Source.Internet.share_pct", "khong.co.that"]
    )
    assert found == [("Internet", 12.5)]


def test_the_label_comes_from_the_key_itself() -> None:
    found = pairs_from(
        {"Source.Financial_Consultants.share_pct": 40.0}, ["Source.Financial_Consultants.share_pct"]
    )
    assert found == [("Financial_Consultants", 40.0)]


def test_a_short_key_still_gets_a_label() -> None:
    assert pairs_from({"rows.total": 40.0}, ["rows.total"]) == [("total", 40.0)]


# --- khong ve khi khong co gi de ve -------------------------------------------


def test_nothing_to_draw_draws_nothing() -> None:
    """Mot bieu do khong cot trong y het mot bieu do dang tai."""
    assert bar_svg([]) == ""
    assert pairs_from({}, ["a.b.c"]) == []


def test_too_many_bars_are_cut_rather_than_drawn_unreadably() -> None:
    many = [(f"n{index}", float(index + 1)) for index in range(30)]
    assert len(_widths(bar_svg(many))) == MAX_BARS


# --- van la SVG hop le, va an toan --------------------------------------------


def test_it_is_an_svg_element() -> None:
    svg = bar_svg(CAP, unit="%", title="Kênh thông tin")
    assert svg.startswith("<svg ")
    assert svg.endswith("</svg>")


def test_a_label_with_angle_brackets_cannot_inject_markup() -> None:
    # Nhan den tu ten cot trong tep nguoi dung tai len.
    svg = bar_svg([("<script>x</script>", 1.0)])
    assert "<script>" not in svg
    assert "&lt;script&gt;" in svg


def test_the_unit_is_printed_beside_the_number() -> None:
    assert "40 %" in bar_svg(CAP, unit="%")


def test_it_carries_a_label_for_screen_readers() -> None:
    assert 'aria-label="Kênh thông tin"' in bar_svg(CAP, title="Kênh thông tin")


def test_a_very_long_label_is_shortened() -> None:
    svg = bar_svg([("x" * 80, 1.0)])
    assert "…" in svg
    assert "x" * 80 not in svg
