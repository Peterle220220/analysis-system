"""Uoc luong ky toi - va cac cho PHAI TU CHOI.

`timeline.py` co y khong co phan nay, va ly do no ghi van dung nguyen: mot con
so du bao truy ve mot mo hinh, khong truy ve dong du lieu nao. Nen cho nay
khong pha luat do, no dung ngoai luat do - va su tach bach la toan bo thiet ke.

Nua tren cua bai nay la cac cho phai tu choi. Tu choi la ket qua binh thuong o
day, khong phai loi.
"""

from __future__ import annotations

import pytest

from analysis_system.domains.execution_engine.forecast import (
    MIN_PERIODS,
    Projection,
    Refusal,
    horizon,
    project,
    series_in,
)

# Mot chuoi tang deu, du dai, khop duong thang gan nhu hoan hao.
TANG_DEU = [10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0, 24.0, 26.0, 28.0, 30.0, 32.0]


# --- phai tu choi -------------------------------------------------------------


def test_too_few_periods_is_refused() -> None:
    """Phat hien mot xu huong va keo dai no la hai viec khac nhau."""
    found = project([1.0, 2.0, 3.0, 4.0, 5.0])
    assert isinstance(found, Refusal)
    assert str(MIN_PERIODS) in found.reason


def test_reaching_further_than_a_third_of_what_was_seen_is_refused() -> None:
    """Day la cho moi du bao hong, va no la mot con so chu khong phai loi khuyen."""
    found = project(TANG_DEU, ahead=9)
    assert isinstance(found, Refusal)
    assert "tối đa 4 kỳ" in found.reason


def test_a_scatter_with_no_line_through_it_is_refused() -> None:
    # Keo dai mot duong khong co o do la bia.
    nhay = [10.0, 90.0, 20.0, 80.0, 30.0, 70.0, 15.0, 85.0, 25.0, 75.0]
    found = project(nhay)
    assert isinstance(found, Refusal)
    assert "đường thẳng" in found.reason


def test_a_flat_series_is_refused_rather_than_projected_flat() -> None:
    found = project([5.0] * 12)
    assert isinstance(found, Refusal)


def test_asking_for_zero_periods_ahead_is_refused() -> None:
    assert isinstance(project(TANG_DEU, ahead=0), Refusal)


def test_nothing_at_all_is_refused() -> None:
    assert isinstance(project([]), Refusal)


# --- khi that su uoc luong duoc -----------------------------------------------


def test_a_clean_trend_can_be_carried_one_period_forward() -> None:
    found = project(TANG_DEU, ahead=1)
    assert isinstance(found, Projection)
    # Ky thu 13 cua mot chuoi tang deu 2 mot ky, bat dau tu 10.
    assert found.low <= 34.0 <= found.high


def test_it_gives_a_range_and_not_a_single_number() -> None:
    """Mot con so le moi nguoi ta tin vao do chinh xac khong co that."""
    found = project([10.0, 12.5, 14.0, 16.5, 18.0, 20.5, 22.0, 24.5, 26.0, 28.5])
    assert isinstance(found, Projection)
    assert found.high > found.low


def test_a_noisier_series_gets_a_wider_range() -> None:
    """Du lieu cang nhay thi khoang cang rong, va dieu do dung."""
    sach = project(TANG_DEU, ahead=1)
    nhieu = project([10.0, 13.0, 13.5, 17.0, 17.5, 21.0, 21.5, 25.0, 25.5, 29.0, 29.5, 33.0])
    assert isinstance(sach, Projection)
    assert isinstance(nhieu, Projection)
    assert (nhieu.high - nhieu.low) > (sach.high - sach.low)


def test_it_never_travels_without_saying_it_is_an_estimate() -> None:
    found = project(TANG_DEU, ahead=1)
    assert isinstance(found, Projection)
    assert "ƯỚC LƯỢNG" in found.caveat
    assert "KHÔNG phải" in found.caveat


def test_a_falling_series_is_carried_down() -> None:
    found = project(list(reversed(TANG_DEU)), ahead=1)
    assert isinstance(found, Projection)
    assert found.high < 10.0


# --- xa nhat den dau ----------------------------------------------------------


@pytest.mark.parametrize(
    ("observed", "furthest"),
    [(12, 4), (9, 3), (8, 2), (5, 1)],
)
def test_how_far_it_will_go(observed: int, furthest: int) -> None:
    assert horizon(observed) == furthest


def test_the_furthest_period_is_allowed_and_the_next_one_is_not() -> None:
    assert isinstance(project(TANG_DEU, ahead=horizon(len(TANG_DEU))), Projection)
    assert isinstance(project(TANG_DEU, ahead=horizon(len(TANG_DEU)) + 1), Refusal)


# --- no dung ngoai he thong metric --------------------------------------------


def test_the_result_carries_no_metric_key() -> None:
    """Khong ket luan nao duoc phep dan mot con so uoc luong.

    Mot luan diem trich so nay se bi chinh lop kiem metric key nem di, y het
    trich mot chi so khong ton tai - va do la hanh vi dung.
    """
    found = project(TANG_DEU, ahead=1)
    assert isinstance(found, Projection)
    assert not hasattr(found, "key")
    assert not hasattr(found, "metric_keys")


# --- nhan ra mot truc thoi gian, va chi mot truc thoi gian --------------------


def _thang(name: str, count: int = 12) -> dict[str, float]:
    return {
        f"{name}.by.ngay_ban.2026-{month:02d}": float(month * 10) for month in range(1, count + 1)
    }


def test_a_run_of_month_labels_is_a_time_series() -> None:
    found = series_in(_thang("doanh_thu.mean"))
    assert list(found) == ["doanh_thu.mean theo ngay_ban"]
    assert len(found["doanh_thu.mean theo ngay_ban"]) == 12


def test_group_labels_that_are_not_periods_are_not_a_time_series() -> None:
    """Keo dai mot duong qua hai nhom gioi tinh la mot cau vo nghia noi bang
    giong chac chan."""
    metrics = {f"PPF.mean.by.gender.{name}": 1.0 for name in ("Male", "Female")}
    assert series_in(metrics) == {}


def test_one_stray_group_label_disqualifies_the_whole_series() -> None:
    """Mot day lan `Male` vao giua cac thang khong phai mot truc thoi gian."""
    metrics = _thang("doanh_thu.mean")
    metrics["doanh_thu.mean.by.ngay_ban.Male"] = 5.0
    assert series_in(metrics) == {}


def test_a_series_too_short_to_project_is_not_offered() -> None:
    assert series_in(_thang("doanh_thu.mean", count=MIN_PERIODS - 1)) == {}


def test_quarters_and_years_count_as_periods() -> None:
    quy = {f"x.mean.by.ky.2026-Q{q}": 1.0 * q for q in range(1, 5)}
    quy.update({f"x.mean.by.ky.2027-Q{q}": 5.0 + q for q in range(1, 5)})
    assert "x.mean theo ky" in series_in(quy)

    nam = {f"y.mean.by.nam.{2018 + step}": float(step) for step in range(MIN_PERIODS)}
    assert "y.mean theo nam" in series_in(nam)


def test_the_series_comes_back_in_time_order() -> None:
    found = series_in(_thang("doanh_thu.mean"))["doanh_thu.mean theo ngay_ban"]
    assert [label for label, _ in found] == sorted(label for label, _ in found)
    assert found[0][0] == "2026-01"


def test_a_plain_metric_with_no_breakdown_is_ignored() -> None:
    assert series_in({"rows.total": 40.0, "age.mean": 27.8}) == {}


def test_a_measured_series_can_be_carried_forward_end_to_end() -> None:
    found = series_in(_thang("doanh_thu.mean"))["doanh_thu.mean theo ngay_ban"]
    carried = project([value for _, value in found], ahead=1)
    assert isinstance(carried, Projection)
    assert carried.low <= 130.0 <= carried.high
