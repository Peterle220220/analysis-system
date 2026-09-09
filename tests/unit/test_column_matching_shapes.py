"""Cach doan "cau hoi nhac toi cot nao" co chay voi MOI kieu dat ten khong?

Chu he thong nhac: no khong chi ap dung cho bo du lieu nay. Nen do, tren bay
kieu dat ten cot gap trong thuc te - moi kieu mot bang, moi bang vai cau hoi.

Khong goi model. Chay trong mot giay.
"""

from __future__ import annotations

import pytest

from analysis_system.services.shortlist import named_in

BO = [
    (
        "snake_case tieng Viet",
        ["don_hang_thang_1", "don_hang_thang_2", "doanh_thu", "chi_phi", "khach_hang"],
        [
            ("doanh_thu thang nay the nao", {"doanh_thu"}),
            ("don_hang_thang_1 co bao nhieu", {"don_hang_thang_1"}),
            ("so sanh chi phi va doanh thu", {"chi_phi", "doanh_thu"}),
        ],
    ),
    (
        "CamelCase tieng Anh",
        ["TotalRevenue", "TotalCost", "CustomerCount", "OrderDate"],
        [
            ("CustomerCount la bao nhieu", {"CustomerCount"}),
            ("OrderDate the nao", {"OrderDate"}),
        ],
    ),
    (
        "tieng Viet co dau, co dau cach",
        ["Doanh thu thuần", "Doanh thu gộp", "Chi phí bán hàng", "Số lượng đơn"],
        [
            ("Doanh thu thuần bao nhieu", {"Doanh thu thuần"}),
            ("Chi phí bán hàng the nao", {"Chi phí bán hàng"}),
        ],
    ),
    (
        "ma ky co hau to",
        ["Q1_2024", "Q2_2024", "Q3_2024", "Q4_2024", "region"],
        [
            ("Q3_2024 tang hay giam", {"Q3_2024"}),
            ("region nao cao nhat", {"region"}),
        ],
    ),
    (
        "viet tat co ngoac",
        ["ROA(A) truoc thue", "ROA(B) sau thue", "EBITDA (adj)", "EBITDA (raw)", "nhom"],
        [
            ("ROA(B) the nao", {"ROA(B) sau thue"}),
            ("EBITDA (adj) bao nhieu", {"EBITDA (adj)"}),
        ],
    ),
    (
        "ten co dau cham",
        ["cons.price.idx", "cons.conf.idx", "emp.var.rate", "y"],
        [
            ("cons.conf.idx the nao", {"cons.conf.idx"}),
            ("emp.var.rate co lien quan khong", {"emp.var.rate"}),
        ],
    ),
    (
        "co don vi trong ten",
        [
            "Doanh thu (triệu đồng)",
            "Chi phí (triệu đồng)",
            "Thời gian (ngày)",
            "Số lượng (cái)",
        ],
        [
            ("Thời gian (ngày) trung binh", {"Thời gian (ngày)"}),
            ("Doanh thu bao nhieu trieu dong", {"Doanh thu (triệu đồng)"}),
        ],
    ),
]


CASES = [(kieu, cau, mong) for kieu, cot, cases in BO for cau, mong in cases]
COLUMNS = {kieu: cot for kieu, cot, _ in BO}


@pytest.mark.parametrize(("kieu", "cau", "mong"), CASES)
def test_the_question_names_exactly_the_right_columns(kieu: str, cau: str, mong: set[str]) -> None:
    assert named_in(cau, COLUMNS[kieu]) == mong
