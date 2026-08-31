"""Cut a fixed, immutable fixture out of the BPI Challenge 2019 XES event log.

Run by hand, once. The CSV it produces is committed and from then on treated as
immutable: the test suite reads the committed file and never regenerates it.

Selection rule (deterministic, no randomness anywhere):

1. Index every trace in the source file: case id, variant signature, event count.
2. Sort the index by case id.
3. Spend the first half of the budget taking the first case of every variant not
   seen yet, skipping any case that would push the running total over.
4. Spend the remaining half filling in case id order, so common variants repeat
   and variant frequency stays a number worth reading.

Taking whole cases matters: a case cut in half makes process mining report a
process that never happened.

Reading the source uses xml.etree directly rather than services.storage, because
storage deliberately has no XES reader and this script is a one-off developer
tool that runs outside the pipeline. Everything it *writes* still goes through
services.storage, so the fixture is written atomically with pinned line endings.

Usage:
    python3 scripts/make_fixture.py \
        --source ~/analysis-data/raw/BPI_Challenge_2019.xes \
        --out tests/fixtures/bpi19_slice.csv
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import sys
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pandas as pd

from analysis_system.services import storage

# XES attribute elements. Anything else inside a trace or event is structure.
ATTRIBUTE_TAGS: Final[frozenset[str]] = frozenset(
    {"string", "date", "int", "float", "boolean", "id"}
)

# Trace-level XES key -> fixture column. Every case attribute is kept: Phase 2
# compares KPIs by vendor, company and spend area, and a fixture that dropped
# them would have to be rebuilt.
TRACE_COLUMNS: Final[dict[str, str]] = {
    "concept:name": "case_id",
    "Purchasing Document": "case_purchasing_document",
    "Item": "case_item",
    "Item Type": "case_item_type",
    "Item Category": "case_item_category",
    "GR-Based Inv. Verif.": "case_gr_based_inv_verif",
    "Goods Receipt": "case_goods_receipt",
    "Source": "case_source",
    "Purch. Doc. Category name": "case_purch_doc_category_name",
    "Company": "case_company",
    "Spend classification text": "case_spend_classification_text",
    "Spend area text": "case_spend_area_text",
    "Sub spend area text": "case_sub_spend_area_text",
    "Vendor": "case_vendor",
    "Name": "case_name",
    "Document Type": "case_document_type",
}

# Event-level XES key -> fixture column.
EVENT_COLUMNS: Final[dict[str, str]] = {
    "concept:name": "activity",
    "time:timestamp": "timestamp",
    "org:resource": "resource",
    "User": "user",
    "Cumulative net worth (EUR)": "cumulative_net_worth_eur",
}

# event_seq is not in the source: it is the position of the event inside its
# case, taken from XES document order. Without it the many events that share a
# timestamp have no defined order, and variant discovery stops being
# reproducible - which would break criterion S1.
SEQUENCE_COLUMN: Final[str] = "event_seq"

COLUMN_ORDER: Final[tuple[str, ...]] = (
    "case_id",
    SEQUENCE_COLUMN,
    "activity",
    "timestamp",
    "resource",
    "user",
    "cumulative_net_worth_eur",
    *sorted(name for key, name in TRACE_COLUMNS.items() if key != "concept:name"),
)

DEFAULT_TARGET_EVENTS: Final[int] = 5000

# Share of the budget reserved for covering distinct variants. The rest is
# filled in case id order so common variants repeat and variant *frequency*
# stays a meaningful number - a slice where every variant occurs exactly once
# cannot support any frequency analysis at all.
DEFAULT_VARIANT_SHARE: Final[float] = 0.5

Trace = tuple[dict[str, str], list[dict[str, str]]]


class FixtureError(RuntimeError):
    """The source log does not match what the fixture builder expects."""


@dataclass(frozen=True)
class IndexEntry:
    """One trace, summarised so the whole log fits in memory during selection."""

    case_id: str
    variant_hash: str
    event_count: int


def iter_traces(path: Path) -> Iterator[Trace]:
    """Stream traces out of an XES file without loading it into memory.

    The BPI 2019 log is a single 694 MB line, so a line-oriented reader is
    useless here and the whole file cannot be parsed into a tree.

    Yields:
        A (trace attributes, events) pair per trace, in document order.
    """
    trace_attributes: dict[str, str] = {}
    events: list[dict[str, str]] = []
    current_event: dict[str, str] = {}
    in_trace = False
    in_event = False
    root: ET.Element | None = None

    for action, element in ET.iterparse(str(path), events=("start", "end")):
        if root is None:
            root = element
        tag = element.tag.rsplit("}", 1)[-1]

        if action == "start":
            if tag == "trace":
                in_trace, trace_attributes, events = True, {}, []
            elif tag == "event":
                in_event, current_event = True, {}
            continue

        if tag in ATTRIBUTE_TAGS:
            key = element.get("key")
            if key is None:
                continue
            value = element.get("value", "")
            if in_event:
                current_event[key] = value
            elif in_trace:
                trace_attributes[key] = value
        elif tag == "event":
            in_event = False
            events.append(current_event)
        elif tag == "trace":
            in_trace = False
            yield trace_attributes, events
            element.clear()
            if root is not None:
                root.clear()


def variant_signature(events: list[dict[str, str]]) -> str:
    """Return the hash of the activity sequence that defines a process variant."""
    activities = "|".join(event.get("concept:name", "") for event in events)
    return hashlib.sha256(activities.encode("utf-8")).hexdigest()[:16]


def build_index(path: Path) -> list[IndexEntry]:
    """Summarise every trace in the log so selection can sort by case id."""
    entries: list[IndexEntry] = []
    for attributes, events in iter_traces(path):
        case_id = attributes.get("concept:name")
        if case_id is None:
            raise FixtureError("Co trace khong co thuoc tinh concept:name lam case_id.")
        entries.append(IndexEntry(case_id, variant_signature(events), len(events)))
    if not entries:
        raise FixtureError(f"Khong doc duoc trace nao tu {path}")
    return entries


def select_cases(
    index: list[IndexEntry],
    target_events: int,
    *,
    variant_share: float = DEFAULT_VARIANT_SHARE,
) -> list[str]:
    """Choose whole cases up to the event budget, in two passes.

    The first pass spends variant_share of the budget on the first case of each
    variant not seen yet, so rare paths make it in. The second pass fills the
    remainder in case id order, which lets common variants repeat; without that
    second pass every variant would occur exactly once and frequency analysis
    would have nothing to measure.

    Args:
        index: one entry per trace in the source log.
        target_events: soft budget. A case is skipped when it would push the
            total past the budget, so the result never exceeds it and no case is
            ever truncated.
        variant_share: fraction of the budget reserved for variant coverage.

    Returns:
        The chosen case ids, in case id order.
    """
    ordered = sorted(index, key=lambda entry: entry.case_id)
    variant_budget = int(target_events * variant_share)
    chosen: dict[str, IndexEntry] = {}
    seen_variants: set[str] = set()
    total = 0

    for entry in ordered:
        if entry.variant_hash in seen_variants:
            continue
        if total + entry.event_count > variant_budget:
            continue
        seen_variants.add(entry.variant_hash)
        chosen[entry.case_id] = entry
        total += entry.event_count

    for entry in ordered:
        if entry.case_id in chosen:
            continue
        if total + entry.event_count > target_events:
            continue
        chosen[entry.case_id] = entry
        total += entry.event_count

    return sorted(chosen)


def extract_rows(path: Path, wanted: set[str]) -> list[dict[str, str]]:
    """Read the chosen cases back out of the log and flatten them to rows.

    Raises:
        FixtureError: the log carries an attribute the column map does not cover,
            which would silently drop data.
    """
    rows: list[dict[str, str]] = []
    remaining = set(wanted)
    for attributes, events in iter_traces(path):
        case_id = attributes.get("concept:name", "")
        if case_id not in remaining:
            continue
        remaining.discard(case_id)

        unknown_trace_keys = set(attributes) - set(TRACE_COLUMNS)
        if unknown_trace_keys:
            raise FixtureError(
                f"Case {case_id} co thuoc tinh chua duoc anh xa: {sorted(unknown_trace_keys)}"
            )
        case_values = {TRACE_COLUMNS[key]: value for key, value in attributes.items()}

        for sequence, event in enumerate(events):
            unknown_event_keys = set(event) - set(EVENT_COLUMNS)
            if unknown_event_keys:
                raise FixtureError(
                    f"Case {case_id} co thuoc tinh event chua duoc anh xa: "
                    f"{sorted(unknown_event_keys)}"
                )
            row: dict[str, str] = dict(case_values)
            row[SEQUENCE_COLUMN] = str(sequence)
            row.update({EVENT_COLUMNS[key]: value for key, value in event.items()})
            rows.append(row)

        if not remaining:
            break

    if remaining:
        raise FixtureError(f"Khong tim lai duoc cac case da chon: {sorted(remaining)}")
    return rows


def build_frame(rows: list[dict[str, str]]) -> pd.DataFrame:
    """Assemble the fixture frame with a fixed column order and row order."""
    frame = pd.DataFrame(rows, columns=list(COLUMN_ORDER), dtype=str)
    frame[SEQUENCE_COLUMN] = frame[SEQUENCE_COLUMN].astype(int)
    frame = frame.sort_values(["case_id", SEQUENCE_COLUMN], kind="stable")
    return frame.reset_index(drop=True)


def describe(frame: pd.DataFrame, source: Path, source_hash: str) -> str:
    """Write down what the fixture actually contains, as observation not judgement."""
    activities = collections.Counter(frame["activity"])
    variants = frame.groupby("case_id", sort=True)["activity"].apply(lambda s: "|".join(s))
    rework_cases = sum(
        1 for _, seq in variants.items() if len(set(seq.split("|"))) != len(seq.split("|"))
    )
    duplicate_timestamps = int(frame.duplicated(subset=["case_id", "timestamp"], keep=False).sum())
    same_resource_user = int((frame["resource"] == frame["user"]).sum())
    events_per_case = frame.groupby("case_id", sort=True).size()

    blank_counts = {
        column: int((frame[column].isna() | (frame[column].astype(str) == "")).sum())
        for column in frame.columns
    }
    blanks = {column: count for column, count in blank_counts.items() if count}
    none_literals = int((frame["resource"] == "NONE").sum())

    lines: list[str] = [
        "# FIXTURE — bpi19_slice.csv",
        "",
        "Tài liệu **quan sát**, không phải lỗi tự cài. Fixture cắt từ dữ liệu thật và",
        "bất biến kể từ khi commit; test đọc file đã commit, không cắt lại lúc chạy.",
        "",
        "## Nguồn",
        "",
        f"- File gốc: `{source.name}`",
        f"- SHA-256 file gốc: `{source_hash}`",
        "- Bộ dữ liệu: BPI Challenge 2019 (Purchase-to-Pay), 4TU.ResearchData",
        "- Trích dẫn bắt buộc: van Dongen, B.F., *Dataset BPI Challenge 2019*.",
        "  4TU.Centre for Research Data.",
        "  https://doi.org/10.4121/uuid:d06aff4b-79f0-45e6-8ec8-e19730c248f1",
        "",
        "## Quy tắc cắt",
        "",
        "Tất định tuyệt đối, không dùng random. Lấy nguyên case hoàn chỉnh — cắt giữa",
        "case sẽ làm process mining ra một quy trình chưa từng xảy ra.",
        "",
        "1. Sắp xếp toàn bộ case theo `case_id`.",
        "2. Lượt 1 — dùng 50% ngân sách: lấy case đầu tiên của **mỗi variant chưa gặp**,",
        "   để các đường đi hiếm cũng có mặt.",
        "3. Lượt 2 — 50% còn lại: lấp bằng các case còn lại theo thứ tự `case_id`,",
        "   nhờ đó variant phổ biến lặp lại nhiều lần và **tần suất variant có ý nghĩa**.",
        "4. Case nào làm vượt ngân sách thì bỏ qua, không cắt ngắn.",
        "",
        "## Quy mô",
        "",
        f"- Số case: **{len(events_per_case)}**",
        f"- Số event: **{len(frame)}**",
        f"- Số variant: **{variants.nunique()}**",
        f"- Số activity khác nhau: **{len(activities)}**",
        f"- Event/case: min {int(events_per_case.min())} · trung vị "
        f"{int(events_per_case.median())} · max {int(events_per_case.max())}",
        f"- Khoảng thời gian: {frame['timestamp'].min()} → {frame['timestamp'].max()}",
        "",
        "## Activity quan sát được",
        "",
        "| Activity | Số event |",
        "|---|---:|",
    ]
    lines.extend(f"| {name} | {count} |" for name, count in activities.most_common())

    lines.extend(
        [
            "",
            "## Vấn đề chất lượng quan sát được",
            "",
            "| Hiện tượng | Số lượng | Ghi chú |",
            "|---|---:|---|",
            f"| Event có `timestamp` trùng với event khác cùng case | {duplicate_timestamps} | "
            "Lý do `event_seq` phải tồn tại: timestamp một mình không xác định được thứ tự |",
            f"| `resource` mang giá trị chuỗi `NONE` | {none_literals} | "
            "Null giả dạng chuỗi, không phải giá trị thiếu thật |",
            f"| `resource` trùng hệt `user` | {same_resource_user}/{len(frame)} | "
            "Hai cột chở cùng một thông tin; giữ cả hai để A2 Profiler tự phát hiện |",
            f"| Case có activity lặp lại (rework) | {rework_cases} | "
            "Đầu vào cho phân tích rework ở Phase 4 |",
        ]
    )
    if blanks:
        for column, count in sorted(blanks.items()):
            lines.append(f"| Ô rỗng ở cột `{column}` | {count} | Giá trị thiếu thật |")
    else:
        lines.append("| Ô rỗng | 0 | Không có ô rỗng nào trong lát cắt này |")

    lines.extend(
        [
            "",
            "## Ánh xạ cột",
            "",
            "| Cột fixture | Nguồn trong XES |",
            "|---|---|",
            "| `case_id` | thuộc tính trace `concept:name` |",
            f"| `{SEQUENCE_COLUMN}` | **không có trong nguồn** — vị trí của event trong case, "
            "lấy theo thứ tự tài liệu XES |",
        ]
    )
    lines.extend(f"| `{name}` | thuộc tính event `{key}` |" for key, name in EVENT_COLUMNS.items())
    lines.extend(
        f"| `{name}` | thuộc tính trace `{key}` |"
        for key, name in TRACE_COLUMNS.items()
        if key != "concept:name"
    )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Build the fixture and its observation document."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="file XES goc")
    parser.add_argument("--out", type=Path, required=True, help="file CSV fixture")
    parser.add_argument("--target-events", type=int, default=DEFAULT_TARGET_EVENTS)
    args = parser.parse_args(argv)

    source: Path = args.source.expanduser()
    if not source.is_file():
        print(f"Khong tim thay file nguon: {source}", file=sys.stderr)
        return 1

    print(f"[1/4] Lap chi muc toan bo trace trong {source.name} ...", flush=True)
    index = build_index(source)
    print(f"      {len(index)} case, {sum(e.event_count for e in index)} event")

    print(f"[2/4] Chon case (ngan sach {args.target_events} event, phu variant truoc) ...")
    chosen = select_cases(index, args.target_events)
    print(f"      chon {len(chosen)} case")

    print("[3/4] Doc lai va lam phang cac case da chon ...", flush=True)
    frame = build_frame(extract_rows(source, set(chosen)))
    print(f"      {len(frame)} dong x {len(frame.columns)} cot")

    print("[4/4] Ghi fixture va FIXTURE.md ...")
    csv_text = frame.to_csv(index=False, lineterminator="\n")
    storage.write_text(csv_text, args.out)
    source_hash = storage.sha256_file(source)
    storage.write_text(describe(frame, source, source_hash), args.out.with_name("FIXTURE.md"))
    print(f"      {args.out}")
    print(f"      {args.out.with_name('FIXTURE.md')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
