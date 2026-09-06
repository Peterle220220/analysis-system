"""Cay viec: bo du lieu -> ban sach -> phan tich -> phan tich con.

Chu he thong mo ta no bang hinh anh thu muc: "giong voi viec ban tao folder va
co cac file trong cac file". Cai duoc kiem o day la hinh dang do dung, va so
thu tu nguoi doc thay khong doi khi co them mot luot hoi moi.
"""

from __future__ import annotations

import json
from pathlib import Path

from analysis_system.web.tree import (
    Lineage,
    Node,
    build_tree,
    path_to,
    read_lineage,
    write_lineage,
)


def flat(node: Node, depth: int = 0) -> list[tuple[int, str, str]]:
    """Ca cay thanh mot danh sach (do sau, so thu tu, nhan), de doc bang mat."""
    out = [(depth, node.number, node.label)]
    for child in node.children:
        out.extend(flat(child, depth + 1))
    return out


def test_a_dataset_with_no_questions_still_has_its_clean_data() -> None:
    root = build_tree("finance_data", [], {})
    assert [item[2] for item in flat(root)] == ["finance_data", "Dữ liệu sạch"]


def test_analyses_hang_under_the_clean_data() -> None:
    root = build_tree(
        "finance_data",
        [("finance_data__q1", "Tỷ lệ nam nữ?"), ("finance_data__q2", "Tuổi trung bình?")],
        {},
    )
    labels = [item[2] for item in flat(root)]
    assert labels == ["finance_data", "Dữ liệu sạch", "Tỷ lệ nam nữ?", "Tuổi trung bình?"]


def test_a_follow_up_sits_inside_the_analysis_it_came_from() -> None:
    # Day la ca chinh: A1 de ra A1.1. Khong suy ra duoc tu ma lan chay, nen no
    # phai den tu lineage da ghi lai.
    root = build_tree(
        "d",
        [("d__q1", "Câu A"), ("d__q2", "Đào sâu A1")],
        {"d__q2": Lineage(parent="d__q1", claim="A1")},
    )
    analyses = root.children[0].children
    assert len(analyses) == 1
    assert analyses[0].label == "Câu A"
    assert [child.label for child in analyses[0].children] == ["Đào sâu A1"]


def test_the_numbering_reads_like_a_table_of_contents() -> None:
    root = build_tree(
        "d",
        [("d__q1", "A"), ("d__q2", "B"), ("d__q3", "A1 sâu hơn"), ("d__q4", "A1 sâu nữa")],
        {
            "d__q3": Lineage(parent="d__q1", claim="A1"),
            "d__q4": Lineage(parent="d__q3", claim="A1.1"),
        },
    )
    numbered = [(item[1], item[2]) for item in flat(root) if item[1]]
    assert numbered == [
        ("1", "A"),
        ("1.1", "A1 sâu hơn"),
        ("1.1.1", "A1 sâu nữa"),
        ("2", "B"),
    ]


def test_a_follow_up_whose_parent_is_gone_still_appears() -> None:
    # Xoa mot luot hoi cu khong duoc lam bien mat nhung luot sinh ra tu no.
    root = build_tree("d", [("d__q2", "Con mo coi")], {"d__q2": Lineage(parent="d__q1")})
    assert [child.label for child in root.children[0].children] == ["Con mo coi"]


def test_a_long_question_is_shortened_for_the_tree() -> None:
    long_one = "Hãy tính tỷ lệ nam nữ và liệt kê ba kênh thông tin được dùng nhiều nhất"
    root = build_tree("d", [("d__q1", long_one)], {})
    label = root.children[0].children[0].label
    assert len(label) <= 48
    assert label.endswith("…")


def test_the_path_says_where_you_are() -> None:
    root = build_tree("d", [("d__q1", "A")], {})
    names = [node.label for node in path_to(root, "d__q1")]
    assert names == ["d", "Dữ liệu sạch", "A"]


def test_lineage_survives_a_round_trip(tmp_path: Path) -> None:
    write_lineage(tmp_path / "d__q2", parent="d__q1", claim="Nam chiếm 62.5 %")
    found = read_lineage(tmp_path / "d__q2")
    assert found.parent == "d__q1"
    assert found.claim == "Nam chiếm 62.5 %"


def test_a_round_with_no_lineage_file_has_no_parent(tmp_path: Path) -> None:
    assert read_lineage(tmp_path / "chua_co") == Lineage()


def test_a_broken_lineage_file_is_not_a_crash(tmp_path: Path) -> None:
    # Mot tep hong khong duoc lam sap ca trang; luot hoi do chi mat cha.
    run_dir = tmp_path / "d__q2"
    run_dir.mkdir()
    (run_dir / "lineage.json").write_text("{khong phai json", encoding="utf-8")
    assert read_lineage(run_dir) == Lineage()


def test_lineage_is_written_as_readable_json(tmp_path: Path) -> None:
    write_lineage(tmp_path / "d__q2", parent="d__q1", claim="Nữ chiếm 37.5 %")
    stored = json.loads((tmp_path / "d__q2" / "lineage.json").read_text(encoding="utf-8"))
    # Khong escape unicode: tep nay de nguoi doc duoc khi can dò.
    assert stored["claim"] == "Nữ chiếm 37.5 %"
