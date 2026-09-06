"""Cây việc: bộ dữ liệu → bản sạch → từng phân tích → phân tích con.

Trước đây dashboard là một cuộn chat dài vô tận. Hỏi tới câu thứ tư thì không
ai còn biết mình đang ở đâu, câu nào đẻ ra câu nào, và muốn quay lại một kết
luận cũ thì phải cuộn đi tìm.

Chủ hệ thống mô tả đúng thứ cần có:

    "finance_data sẽ là tập bố sau đó sẽ sinh ra ... finance_data_clean rồi
     trong mục clean đó sẽ có mục con với tên là (phân tích 1, phân tích 2,
     phân tích 3) ... và trong các tập con đó sẽ có A1.1, A1.2 ... giống với
     việc bạn tạo folder và có các file trong các file"

Quan hệ cha–con không suy ra được từ mã lần chạy: `finance_data__q3` không nói
nó sinh ra từ kết luận nào của `finance_data__q1`. Nên nó được **ghi lại** khi
người dùng bấm hỏi tiếp, vào `runs/<lượt>/lineage.json`. Một tệp nhỏ, ghi một
lần, đọc mãi - và nếu tệp không có thì lượt đó là con trực tiếp của bản sạch,
đúng như trước.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

LINEAGE_FILE: Final[str] = "lineage.json"


@dataclass(frozen=True)
class Lineage:
    """Một lượt hỏi sinh ra từ đâu."""

    parent: str = ""
    claim: str = ""


def write_lineage(run_dir: Path, parent: str, claim: str) -> None:
    """Ghi lại lượt hỏi này đào sâu từ kết luận nào của lượt nào."""
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / LINEAGE_FILE).write_text(
        json.dumps({"parent": parent, "claim": claim}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def read_lineage(run_dir: Path) -> Lineage:
    """Nguồn gốc của một lượt hỏi, hoặc rỗng nếu nó hỏi thẳng trên bản sạch."""
    path = run_dir / LINEAGE_FILE
    if not path.is_file():
        return Lineage()
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return Lineage()
    return Lineage(parent=str(stored.get("parent") or ""), claim=str(stored.get("claim") or ""))


@dataclass
class Node:
    """Một mục trong cây, và những mục nằm trong nó."""

    run_id: str
    label: str
    href: str
    children: list[Node] = field(default_factory=list)
    # Số thứ tự người đọc thấy: "1", rồi "1.1", "1.2". Không phải mã lần chạy.
    number: str = ""


def build_tree(
    dataset: str,
    rounds: list[tuple[str, str]],
    lineage: dict[str, Lineage],
) -> Node:
    """Dựng cây từ danh sách lượt hỏi và quan hệ cha–con của chúng.

    Args:
        dataset: mã bộ dữ liệu gốc.
        rounds: (mã lượt, câu hỏi), cũ trước - thứ tự này quyết định số
            "Phân tích 1, 2, 3", nên nó phải ổn định.
        lineage: mã lượt -> nguồn gốc.

    Returns:
        Gốc cây là bộ dữ liệu, dưới nó là bản sạch, dưới nữa là các phân tích.
    """
    root = Node(run_id=dataset, label=dataset, href=f"/bo/{dataset}")
    clean = Node(
        run_id=f"{dataset}__clean",
        label="Dữ liệu sạch",
        href=f"/bo/{dataset}#du-lieu-sach",
    )
    root.children.append(clean)

    nodes: dict[str, Node] = {}
    for run_id, question in rounds:
        nodes[run_id] = Node(
            run_id=run_id,
            label=_short(question) or run_id,
            href=f"/bo/{dataset}/pt/{run_id}",
        )

    # Gắn con vào cha. Cha phải có thật trong danh sách; một lượt tro ve mot
    # lan chay da bi xoa thi treo thang duoi ban sach, chu khong bien mat.
    for run_id, node in nodes.items():
        parent_id = lineage.get(run_id, Lineage()).parent
        parent = nodes.get(parent_id) if parent_id else None
        (parent.children if parent is not None else clean.children).append(node)

    _number(clean.children, "")
    return root


def _number(nodes: list[Node], prefix: str) -> None:
    """Đánh số như mục lục: 1, 2, rồi 1.1, 1.2 bên trong."""
    for index, node in enumerate(nodes, 1):
        node.number = f"{prefix}{index}"
        _number(node.children, f"{node.number}.")


def path_to(root: Node, run_id: str) -> list[Node]:
    """Đường từ gốc xuống một mục, để nói cho người đọc biết họ đang ở đâu."""
    if root.run_id == run_id:
        return [root]
    for child in root.children:
        found = path_to(child, run_id)
        if found:
            return [root, *found]
    return []


def _short(question: str, limit: int = 48) -> str:
    """Câu hỏi, rút gọn vừa một dòng trong cây."""
    text = " ".join(question.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
