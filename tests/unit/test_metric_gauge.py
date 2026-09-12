"""The mot con so: luon co thang do va loi danh gia, khong bao gio la so troc.

Yeu cau (quy tac toan cuc): moi the hien mot gia tri don le phai kem thanh do cho
thay con so nam o dau so voi cac nguong, va mot nhan phu dich con so thanh danh
gia. Con so khong co thang de doc thi khong dung the.
"""

from __future__ import annotations

import re

import pytest

from analysis_system.services.metric_gauge import gauge_for, read_metric
from analysis_system.services.svg_chart import chart_for


def _verdict(key: str, value: float, context: dict[str, float] | None = None) -> str:
    reading = read_metric(key, value, context)
    assert reading is not None
    return reading.verdict


# --- loi danh gia dinh tinh --------------------------------------------------------


def test_a_strong_positive_correlation_is_said_in_words() -> None:
    assert _verdict("a.corr.with.b", 0.8) == "Tương quan thuận rất mạnh (r = 0.80)"


def test_a_negative_correlation_says_which_way() -> None:
    assert _verdict("a.corr.with.b", -0.32) == "Tương quan nghịch vừa phải (r = -0.32)"


def test_a_tiny_correlation_is_said_to_be_nothing() -> None:
    assert _verdict("a.corr.with.b", 0.04).startswith("Gần như không có tương quan")


def test_an_effect_size_uses_the_usual_thresholds() -> None:
    assert _verdict("m.effect_size.by.g", 1.17) == "Khác biệt lớn giữa các nhóm (d = 1.17)"
    assert _verdict("m.effect_size.by.g", 0.3).startswith("Khác biệt nhỏ")


def test_a_p_value_of_zero_reads_as_below_a_thousandth() -> None:
    assert _verdict("m.ttest.by.g.p_value", 0.0) == "Có ý nghĩa thống kê rất mạnh (p < 0.001)"
    assert _verdict("m.ttest.by.g.p_value", 0.2) == "Chưa đủ bằng chứng thống kê (p = 0.200)"


def test_a_t_statistic_is_read_against_chance() -> None:
    assert _verdict("m.ttest.by.g.t_stat", 6.26) == (
        "Chênh lệch vượt xa ngưỡng ngẫu nhiên (t = 6.26)"
    )


def test_eta_squared_is_read_in_percent() -> None:
    assert "vừa" in _verdict("m.eta_sq.by.g", 6.26)


def test_a_share_says_how_big_a_part_it_is() -> None:
    assert _verdict("g.1.share_pct", 3.23) == "Chiếm tỷ trọng rất nhỏ (3.23 %)"


def test_a_mean_is_placed_in_its_columns_real_range() -> None:
    context = {"m.min": 0.0, "m.max": 1.0}
    assert _verdict("m.mean", 0.52, context) == "Trung bình nằm quanh giữa khoảng giá trị (0.52)"
    assert _verdict("m.mean.by.g.1", 0.95, context).startswith("Trung bình nằm gần mức cao nhất")


def test_a_gap_is_measured_against_the_columns_range() -> None:
    context = {"m.min": 0.0, "m.max": 1.0}
    assert _verdict("m.diff.by.g", 0.07, context).startswith("Chênh lệch nhỏ so với biên độ")


# --- khong co thang thi khong dung the ----------------------------------------------


def test_a_number_with_no_scale_gets_no_card() -> None:
    assert read_metric("rows.total", 6819.0) is None
    assert read_metric("m.sum", 12.0) is None
    assert read_metric("a.corr.with.b.n", 381.0) is None


def test_a_mean_without_its_columns_range_gets_no_card() -> None:
    assert read_metric("m.mean", 0.52) is None


def test_a_lone_number_is_never_drawn_naked() -> None:
    assert chart_for([("tổng số dòng", 6819.0)], "dòng", keys=["rows.total"]) == ""
    assert chart_for([("không rõ", 1.0)]) == ""


# --- the co thanh do that -------------------------------------------------------------


def _card() -> str:
    return gauge_for("a.corr.with.b", 0.8, "Tương quan: A với B")


def test_every_card_carries_a_bar_with_bands_and_a_marker() -> None:
    card = _card()
    assert 'class="gauge-track"' in card
    assert card.count('class="gauge-band') == 9
    assert 'class="gauge-band hit"' in card
    assert 'class="gauge-marker"' in card


def test_the_marker_sits_where_the_number_is() -> None:
    position = re.search(r'class="gauge-marker" style="left:([\d.]+)%"', _card())
    assert position is not None
    assert float(position.group(1)) == pytest.approx(90.0)


def test_a_two_sided_scale_marks_zero() -> None:
    assert 'class="gauge-zero" style="left:50.0%"' in _card()


def test_the_card_names_the_number_and_its_meaning() -> None:
    card = _card()
    assert '<p class="chart-title">Tương quan: A với B</p>' in card
    assert '<div class="gauge-value">0.80</div>' in card
    assert "Tương quan thuận rất mạnh (r = 0.80)" in card


def test_the_marker_has_a_tooltip_and_keyboard_focus() -> None:
    card = _card()
    assert 'tabindex="0" data-tip-label="Tương quan thuận rất mạnh (r = 0.80)"' in card


def test_a_label_cannot_inject_markup() -> None:
    card = gauge_for("a.corr.with.b", 0.5, '<script>x</script>" onload="y')
    assert "<script>" not in card
    assert '" onload="' not in card


def test_the_chart_picker_draws_a_card_for_a_lone_scaled_number() -> None:
    drawn = chart_for([("Độ lớn tác động", 1.17)], keys=["m.effect_size.by.g"])
    assert "chart gauge" in drawn
    assert "Khác biệt lớn giữa các nhóm (d = 1.17)" in drawn
