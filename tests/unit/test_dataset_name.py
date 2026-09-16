"""Ten bo du lieu tu ten tep tieng Viet: bo dau, giu nguyen chu, van an toan cho duong dan."""

from __future__ import annotations

from analysis_system.api.inputs import dataset_name


def test_a_vietnamese_file_name_keeps_its_words_without_the_marks() -> None:
    # Truoc day moi chu co dau thanh "_": "bao cao" thanh "b_o_c_o".
    name = dataset_name("", "báo cáo tài chính MBB của 4 quý gần nhất.xls")
    assert name == "bao_cao_tai_chinh_mbb_cua_4_quy_gan_nhat"


def test_a_typed_name_with_d_bar_and_capitals_is_folded_too() -> None:
    assert dataset_name("Đơn hàng Quý 3", "x.csv") == "don_hang_quy_3"
    assert dataset_name("  Kết quả   kinh doanh ", "x.csv") == "ket_qua_kinh_doanh"


def test_folding_never_opens_a_way_out_of_the_folder() -> None:
    assert dataset_name("../../étc/passwd", "x.csv") == "etc_passwd"
    assert dataset_name("", "ảnh ổ đĩa.csv") == "anh_o_dia"
