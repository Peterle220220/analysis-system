"""Ten cot that khong chiu vua mot bieu thuc chinh quy.

Mot bo du lieu du doan pha san lam lo cho nay. Cot dau ten `Bankrupt?`, cho ra
khoa `Bankrupt?.mean`. Model viet dung khoa ay vao placeholder, va he thong
khong nhan ra do la mot placeholder - vi mau chi nhan `[\\w.-]`, ma dau hoi
khong nam trong do.

Ket luan bi loai voi ly do "dan chi so khong khop", ba lan lien, tren mot cau
hoi chi la dem so dong. Nguyen van loi da ghi lai:

    metric_keys khai bao ['Bankrupt?.mean', 'rows.total']
    khong khop voi cac placeholder ['rows.total']

Cac cot con lai con te hon: ` ROA(A) before interest and % after tax` co khoang
trang dau dong, ngoac don, va dau phan tram.

Khong the doi du lieu cua nguoi dung cho vua mot bieu thuc chinh quy.
"""

from __future__ import annotations

import pytest

from analysis_system.domains.ai_planner.findings import PLACEHOLDER, render_all
from analysis_system.models.agents import Finding, MetricValue

# Nguyen van ten cot cua bo du lieu that.
KHOA_PHA_SAN = "Bankrupt?.mean"
KHOA_ROA = " ROA(A) before interest and % after tax.mean"

DA_DO = {
    KHOA_PHA_SAN: MetricValue(key=KHOA_PHA_SAN, value=0.0323, unit="", source="x"),
    KHOA_ROA: MetricValue(key=KHOA_ROA, value=0.55, unit="", source="x"),
    "rows.total": MetricValue(key="rows.total", value=6819.0, unit="dòng", source="volume"),
}


@pytest.mark.parametrize(
    "key",
    [
        "Bankrupt?.mean",
        " ROA(A) before interest and % after tax.mean",
        "Non-industry income and expenditure/revenue.mean",
        "cons.price.idx.mean",
        "rows.total",
    ],
)
def test_a_real_column_name_is_read_as_a_placeholder(key: str) -> None:
    assert PLACEHOLDER.findall("{" + key + "}") == [key]


def test_the_claim_that_was_rejected_three_times_now_renders() -> None:
    """Nguyen van hinh dang cau da bi loai."""
    finding = Finding(
        claim_template="Tỷ lệ công ty phá sản là {Bankrupt?.mean} trên tổng {rows.total}.",
        metric_keys=(KHOA_PHA_SAN, "rows.total"),
        evidence_ref="mart://x.parquet",
    )
    out, bad = render_all([finding], DA_DO)
    assert out, bad
    assert "0.03" in out[0].claim


def test_a_column_name_with_spaces_and_brackets_renders() -> None:
    finding = Finding(
        claim_template="Chỉ số trung bình là {" + KHOA_ROA + "}.",
        metric_keys=(KHOA_ROA,),
        evidence_ref="mart://x.parquet",
    )
    out, bad = render_all([finding], DA_DO)
    assert out, bad
    assert "0.55" in out[0].claim


# --- rong ra nhung khong buong lop chan --------------------------------------


def test_a_placeholder_naming_nothing_real_is_still_refused() -> None:
    """Rong ra thi mot cum `{gi do}` trong van xuoi cung bi doc la placeholder.

    Nhung `check_finding` doi chieu voi danh sach chi so, nen cai khong co that
    bi loai kem mot cau noi ro - to hon mot lop chan im lang.
    """
    finding = Finding(
        claim_template="Con số là {khong.co.chi.so.nay}.",
        metric_keys=("khong.co.chi.so.nay",),
        evidence_ref="mart://x.parquet",
    )
    out, bad = render_all([finding], DA_DO)
    assert not out
    assert bad


def test_a_typed_number_is_still_refused() -> None:
    # Lop chong bia so khong duoc noi long theo.
    finding = Finding(
        claim_template="Tỷ lệ phá sản là 3.23 %.",
        metric_keys=(KHOA_PHA_SAN,),
        evidence_ref="mart://x.parquet",
    )
    out, bad = render_all([finding], DA_DO)
    assert not out
    assert any("go truc tiep" in line for line in bad)
