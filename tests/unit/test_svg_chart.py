"""Bieu do ve thang bang HTML/SVG, khong them thu vien nao.

Hai dieu kien khong duoc pha:

* thang do chay tu 0 - cat goc lam mot chenh lech 2 % trong nhu gap doi, va do
  la cach ve mot bieu do noi doi ma khong co con so nao sai;
* nhan va gia tri den tu chinh metric key da do, khong qua tay model.
"""

from __future__ import annotations

import re

import pytest

from analysis_system.services.svg_chart import MAX_BARS, bar_chart, chart_keys, pairs_from

CAP = [("Financial_Consultants", 40.0), ("Newspapers", 25.0), ("Internet", 12.5)]


def _widths(drawn: str) -> list[float]:
    return [
        float(found) for found in re.findall(r'class="bar-fill" style="width:([\d.]+)%"', drawn)
    ]


# --- thang do chay tu 0 -------------------------------------------------------


def test_the_scale_starts_at_zero() -> None:
    """Gia tri 12.5 tren 40 phai ra dung mot phan ba be ngang, khong phai mot vach."""
    widths = _widths(bar_chart(CAP))
    assert widths[2] / widths[0] == pytest.approx(12.5 / 40.0, abs=1e-3)


def test_the_largest_value_fills_the_plot() -> None:
    widths = _widths(bar_chart(CAP))
    assert widths[0] == max(widths) == 100.0


def test_a_zero_value_draws_no_bar() -> None:
    assert _widths(bar_chart([("a", 0.0), ("b", 10.0)]))[0] == 0.0


def test_every_value_being_zero_does_not_divide_by_zero() -> None:
    assert bar_chart([("a", 0.0), ("b", 0.0)])


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
    assert bar_chart([]) == ""
    assert pairs_from({}, ["a.b.c"]) == []


def test_too_many_bars_are_cut_rather_than_drawn_unreadably() -> None:
    many = [(f"n{index}", float(index + 1)) for index in range(30)]
    assert len(_widths(bar_chart(many))) == MAX_BARS


# --- HTML hop le, an toan, doc duoc -------------------------------------------


def test_it_is_one_figure() -> None:
    drawn = bar_chart(CAP, unit="%", title="Kênh thông tin")
    assert drawn.startswith('<figure class="chart bars"')
    assert drawn.endswith("</figure>")


def test_a_label_with_angle_brackets_cannot_inject_markup() -> None:
    # Nhan den tu ten cot trong tep nguoi dung tai len, va tu o Nhan gia tri.
    drawn = bar_chart([('<script>x</script>" onmouseover="y', 1.0)])
    assert "<script>" not in drawn
    assert "&lt;script&gt;" in drawn
    assert '" onmouseover="' not in drawn


def test_the_unit_is_printed_beside_the_number() -> None:
    assert "40 %" in bar_chart(CAP, unit="%")


def test_it_carries_a_label_for_screen_readers() -> None:
    assert 'aria-label="Kênh thông tin"' in bar_chart(CAP, title="Kênh thông tin")


def test_a_very_long_label_is_shortened_on_the_bar_but_whole_in_the_tooltip() -> None:
    drawn = bar_chart([("x" * 80, 1.0)])
    assert f'class="bar-label">{"x" * 29}…<' in drawn
    assert f'data-tip-label="{"x" * 80}"' in drawn


def test_values_on_the_bars_are_rounded_to_two_places() -> None:
    drawn = bar_chart([("a", 0.6083), ("b", 0.5987)])
    assert 'class="bar-value">0.61<' in drawn
    assert 'class="bar-value">0.60<' in drawn


def test_the_tooltip_carries_the_precise_number() -> None:
    assert 'data-tip-value="0.6083"' in bar_chart([("a", 0.6083), ("b", 0.5987)])


def test_every_bar_can_be_reached_by_keyboard() -> None:
    drawn = bar_chart(CAP)
    assert drawn.count('tabindex="0"') == len(CAP)


def test_the_highest_bar_is_the_one_emphasised() -> None:
    drawn = bar_chart([("thap", 1.0), ("cao", 3.0), ("giua", 2.0)])
    assert drawn.count('class="bar-row lead"') == 1
    assert 'class="bar-row lead" tabindex="0" data-tip-label="cao"' in drawn


# --- dong ket luan: bieu do ke chuyen, tinh bang code --------------------------


def test_two_groups_say_which_is_higher_and_by_how_much() -> None:
    drawn = bar_chart([("Nhóm A", 0.5987), ("Nhóm B", 0.6083)], story=True)
    caption = re.search(r'<figcaption class="takeaway">(.*?)</figcaption>', drawn)
    assert caption is not None
    # Lam tron 2 chu so thi 0.0096 thanh 0.01 va mat cau chuyen.
    assert caption.group(1) == "<b>Nhóm B</b> cao hơn Nhóm A: 0.6083 so với 0.5987, chênh 0.0096."


def test_several_groups_name_the_highest_and_the_lowest() -> None:
    drawn = bar_chart(CAP, unit="%", story=True)
    assert "Cao nhất: <b>Financial_Consultants</b> (40 %)" in drawn
    assert "Thấp nhất: Internet (12.50 %)" in drawn


def test_equal_groups_are_said_to_be_equal() -> None:
    assert "Các nhóm bằng nhau" in bar_chart([("a", 2.0), ("b", 2.0)], story=True)


def test_no_story_is_told_unless_asked() -> None:
    # Chu "takeaway" con nam trong CSS di kem bieu do: kiem PHAN TU, khong kiem chu.
    assert "<figcaption" not in bar_chart(CAP)


def test_numbers_of_one_kind_share_a_chart() -> None:
    assert chart_keys(["m.mean.by.g.0", "m.mean.by.g.1"]) == ["m.mean.by.g.0", "m.mean.by.g.1"]


def test_a_mix_of_statistics_draws_no_chart() -> None:
    """Muc chenh va p_value tren cung mot truc la mot ban log, khong phai bieu do."""
    assert chart_keys(["m.diff.by.g", "m.ttest.by.g.p_value"]) == []


def test_the_largest_family_is_kept_and_the_odd_number_left_out() -> None:
    """Tong so dong 6.819 canh hai ty le phan tram thi de bep ca hai."""
    keys = ["g.0.share_pct", "g.1.share_pct", "rows.total"]
    assert chart_keys(keys) == ["g.0.share_pct", "g.1.share_pct"]


def test_one_number_is_still_drawn() -> None:
    assert chart_keys(["rows.total"]) == ["rows.total"]


# --- nhan phai la TEN NHOM, khong phai ten phep tinh --------------------------


def test_a_grouped_key_is_labelled_by_its_group() -> None:
    """Tren man hinh moi cot deu ghi "mean": campaign.mean.by.y.yes co chu
    "mean" o dung cho ban dau di lay nhan.

    Bon cot canh nhau mang cung mot cai nhan thi bieu do khong noi gi ca - te
    hon khong co bieu do, vi no trong nhu co noi.
    """
    found = pairs_from({"campaign.mean.by.y.yes": 2.05}, ["campaign.mean.by.y.yes"])
    assert found == [("y: yes", 2.05)]


def test_the_grouping_column_takes_its_glossary_name() -> None:
    found = pairs_from(
        {"campaign.mean.by.y.yes": 2.05}, ["campaign.mean.by.y.yes"], names={"y": "Đăng ký"}
    )
    assert found == [("Đăng ký: yes", 2.05)]


def test_a_value_label_replaces_the_raw_value() -> None:
    metrics = {"m.mean.by.flag.0": 0.61, "m.mean.by.flag.1": 0.60}
    labels = {"flag": {"0": "Còn hoạt động", "1": "Đã đóng cửa"}}
    assert [name for name, _ in pairs_from(metrics, list(metrics), labels)] == [
        "Còn hoạt động",
        "Đã đóng cửa",
    ]


def test_a_value_label_also_names_a_share() -> None:
    found = pairs_from({"flag.1.share_pct": 3.23}, ["flag.1.share_pct"], {"flag": {"1": "Có"}})
    assert found == [("Có", 3.23)]


def test_a_value_label_survives_a_drifted_space_in_the_key() -> None:
    found = pairs_from({"m.mean.by. flag.1": 0.6}, ["m.mean.by. flag.1"], {"flag": {"1": "Có"}})
    assert found == [("Có", 0.6)]


def test_two_groups_of_one_breakdown_get_different_labels() -> None:
    metrics = {"campaign.mean.by.y.yes": 2.05, "campaign.mean.by.y.no": 2.63}
    labels = [name for name, _ in pairs_from(metrics, list(metrics))]
    assert len(set(labels)) == 2


def test_no_label_is_ever_the_name_of_a_statistic() -> None:
    metrics = {
        "campaign.mean.by.y.yes": 2.05,
        "flag_x.mean.by.outcome.success": 0.65,
        "y.yes.share_pct.by.outcome.success": 65.11,
    }
    for name, _ in pairs_from(metrics, list(metrics)):
        assert name not in {"mean", "share_pct", "count", "median"}


def test_a_plain_category_key_keeps_its_short_label() -> None:
    # Source.Internet.share_pct van cho ra Internet, khong doi thanh cai gi dai hon.
    assert pairs_from({"Source.Internet.share_pct": 12.5}, ["Source.Internet.share_pct"]) == [
        ("Internet", 12.5)
    ]


# --- chon loai bieu do theo HINH DANG chi so ---------------------------------


def _kind(drawn: str) -> str:
    if "chart gauge" in drawn:
        return "thuoc do"
    if "chart big" in drawn:
        return "so to"
    if "chart donut" in drawn:
        return "tron"
    if "chart bars" in drawn:
        return "cot"
    if "<path" in drawn:
        return "duong"
    return "khong ve"


def test_one_number_alone_gets_a_gauge_when_it_has_a_scale() -> None:
    from analysis_system.services.svg_chart import chart_for

    drawn = chart_for([("Tương quan", 0.8)], keys=["a.corr.with.b"])
    assert _kind(drawn) == "thuoc do"


def test_one_number_without_a_scale_is_not_drawn_naked() -> None:
    from analysis_system.services.svg_chart import chart_for

    assert _kind(chart_for([("tong so dong", 6819.0)], "dong", keys=["rows.total"])) == "khong ve"


def test_parts_of_a_whole_become_a_donut() -> None:
    from analysis_system.services.svg_chart import chart_for

    assert _kind(chart_for([("khong", 96.77), ("co", 3.23)], "%")) == "tron"


def test_values_in_time_order_become_a_line() -> None:
    from analysis_system.services.svg_chart import chart_for

    pairs = [("2026-01", 10.0), ("2026-02", 14.0), ("2026-03", 12.0), ("2026-04", 18.0)]
    assert _kind(chart_for(pairs)) == "duong"


def test_anything_else_falls_back_to_bars() -> None:
    from analysis_system.services.svg_chart import chart_for

    assert _kind(chart_for([("a", 5.0), ("b", 9.0), ("c", 2.0)])) == "cot"


def test_the_donut_and_the_line_carry_tooltips_too() -> None:
    from analysis_system.services.svg_chart import donut_svg, line_svg

    assert 'data-tip-label="khong"' in donut_svg([("khong", 96.77), ("co", 3.23)])
    pairs = [("2026-01", 10.0), ("2026-02", 14.0), ("2026-03", 12.0), ("2026-04", 18.0)]
    assert 'data-tip-label="2026-04"' in line_svg(pairs)


# --- cac cho phai TU CHOI ve ---------------------------------------------------


def test_numbers_that_do_not_add_up_are_not_a_pie() -> None:
    from analysis_system.services.svg_chart import donut_svg

    assert donut_svg([("a", 40.0), ("b", 35.0)]) == ""


def test_groups_with_no_order_are_not_joined_by_a_line() -> None:
    from analysis_system.services.svg_chart import line_svg

    pairs = [("nam", 10.0), ("nu", 14.0), ("khac", 12.0), ("chua ro", 18.0)]
    assert line_svg(pairs) == ""


def test_too_few_points_are_not_a_line() -> None:
    from analysis_system.services.svg_chart import line_svg

    assert line_svg([("2026-01", 10.0), ("2026-02", 14.0)]) == ""


def test_two_numbers_are_not_shown_as_one_gauge() -> None:
    from analysis_system.services.svg_chart import chart_for

    assert _kind(chart_for([("a", 1.0), ("b", 2.0)], keys=["a.corr.with.b"])) == "cot"


def test_nothing_to_draw_still_draws_nothing() -> None:
    from analysis_system.services.svg_chart import chart_for

    assert chart_for([]) == ""


# --- nhan cho so cua mot phep kiem ------------------------------------------------


def test_a_test_statistic_says_what_it_measures() -> None:
    """Luot chay that: "0.57" voi nhan la ten cot nhom, khong ai doc ra do la gi."""
    found = pairs_from(
        {"m.effect_size.by.flag": 0.57},
        ["m.effect_size.by.flag"],
        names={"m": "Biên lợi nhuận", "flag": "Đóng cửa"},
    )
    assert found == [("Độ lớn tác động: Biên lợi nhuận theo Đóng cửa", 0.57)]


def test_a_test_statistic_without_a_glossary_keeps_the_column_names() -> None:
    assert pairs_from({"m.diff.by.flag": 0.01}, ["m.diff.by.flag"]) == [
        ("Mức chênh: m theo flag", 0.01)
    ]


def test_a_correlation_names_both_columns() -> None:
    assert pairs_from({"a.corr.with.b": -0.26}, ["a.corr.with.b"]) == [
        ("Tương quan: a với b", -0.26)
    ]


def test_a_big_number_keeps_its_whole_label() -> None:
    from analysis_system.services.svg_chart import chart_for

    label = "Độ lớn tác động: Biên lợi nhuận gộp hoạt động theo nhóm"
    assert label in chart_for([(label, 0.57)], keys=["m.effect_size.by.g"])


# --- tieu de bieu do: do cai gi, theo cai gi, bang ten tieng Viet ------------------


def test_the_title_says_what_is_measured_and_by_what() -> None:
    from analysis_system.services.svg_chart import chart_title

    keys = ["m.mean.by.flag.0", "m.mean.by.flag.1"]
    names = {"m": "biên lợi nhuận", "flag": "đóng cửa"}
    assert chart_title(keys, names) == "Trung bình biên lợi nhuận theo đóng cửa"


def test_a_share_chart_is_titled_by_its_column() -> None:
    from analysis_system.services.svg_chart import chart_title

    assert chart_title(["flag.0.share_pct", "flag.1.share_pct"], {"flag": "đóng cửa"}) == (
        "Tỷ lệ theo đóng cửa"
    )


def test_without_a_glossary_the_title_keeps_the_column_names() -> None:
    from analysis_system.services.svg_chart import chart_title

    assert chart_title(["m.mean.by.flag.0", "m.mean.by.flag.1"]) == "Trung bình m theo flag"


def test_one_number_needs_no_title() -> None:
    from analysis_system.services.svg_chart import chart_title

    assert chart_title(["m.mean"]) == ""


def test_the_title_is_shown_and_read_aloud() -> None:
    drawn = bar_chart(CAP, heading="Tỷ lệ theo kênh")
    assert '<p class="chart-title">Tỷ lệ theo kênh</p>' in drawn
    assert 'aria-label="Tỷ lệ theo kênh"' in drawn
