"use client";

import { useEffect, useLayoutEffect, useRef, useState, type UIEvent } from "react";
import { describeError, getJson, type TablePayload } from "@/lib/api";
import { BLOCK_SIZE, blocksFor, ROW_HEIGHT, visibleRange } from "@/lib/virtual-rows";

type Row = Record<string, unknown>;
type Block = { offset: number; total: number; rows: Row[] };

/**
 * Toan bo bang, cuon duoc tu dong dau toi dong cuoi, nhung chi dung cac dong
 * dang nam trong khung nhin. Du lieu xin tu may chu theo tung khoi khi cuon
 * toi, nen mot bang hang trieu dong cung khong di qua mang mot lan.
 */
export default function DataTable({ dataset, which, table }: { dataset: string; which: "clean" | "staged"; table: TablePayload | null }) {
  const wrap = useRef<HTMLDivElement>(null);
  const pending = useRef(new Set<number>());
  const generation = useRef(0);
  const frame = useRef(0);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewport, setViewport] = useState(480);
  const [rowHeight, setRowHeight] = useState(ROW_HEIGHT);
  const [blocks, setBlocks] = useState<Map<number, Row[]>>(() => new Map());
  const [error, setError] = useState("");
  const total = table?.rows ?? 0;
  const columns = table?.columns ?? [];
  const uri = table?.uri ?? "";

  // Bang khac (hay bang vua lam sach lai) thi bo moi khoi da tai.
  useEffect(() => {
    generation.current += 1;
    pending.current.clear();
    setBlocks(new Map());
    setError("");
    setScrollTop(0);
    if (wrap.current) wrap.current.scrollTop = 0;
  }, [uri, total]);

  useEffect(() => {
    const node = wrap.current;
    if (!node) return;
    const measure = () => setViewport(node.clientHeight);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [uri]);

  useEffect(() => () => cancelAnimationFrame(frame.current), []);

  // Do chieu cao dong that (co chu, vien, phong to trinh duyet) thay vi tin con so mac dinh.
  useLayoutEffect(() => {
    const first = wrap.current?.querySelector<HTMLTableRowElement>("tbody tr[data-row]");
    const measured = first?.getBoundingClientRect().height ?? 0;
    if (measured > 0 && Math.abs(measured - rowHeight) > 0.5) setRowHeight(measured);
  });

  const range = visibleRange(scrollTop, viewport, total, rowHeight);

  useEffect(() => {
    if (!uri || error) return;
    for (const index of blocksFor(range)) {
      if (blocks.has(index) || pending.current.has(index)) continue;
      pending.current.add(index);
      const mine = generation.current;
      const query = `which=${which}&offset=${index * BLOCK_SIZE}&limit=${BLOCK_SIZE}`;
      getJson<Block>(`/api/datasets/${encodeURIComponent(dataset)}/rows?${query}`)
        .then((block) => { if (mine === generation.current) setBlocks((current) => new Map(current).set(index, block.rows)); })
        .catch((reason: unknown) => { if (mine === generation.current) setError(describeError(reason, "Không tải được các dòng này.")); })
        .finally(() => pending.current.delete(index));
    }
  }, [range.start, range.end, blocks, dataset, which, uri, error]);

  if (!table || total === 0 || columns.length === 0) return null;

  function onScroll(event: UIEvent<HTMLDivElement>) {
    const top = event.currentTarget.scrollTop;
    cancelAnimationFrame(frame.current);
    frame.current = requestAnimationFrame(() => setScrollTop(top));
  }

  function rowAt(index: number): Row | undefined {
    const block = blocks.get(Math.floor(index / BLOCK_SIZE));
    if (block) return block[index % BLOCK_SIZE];
    return index < table!.preview.length ? table!.preview[index] : undefined;
  }

  const shown: number[] = [];
  for (let index = range.start; index < range.end; index += 1) shown.push(index);
  const span = columns.length + 1;

  return (
    <>
      <div ref={wrap} className="table-wrap vtable" onScroll={onScroll} tabIndex={0} role="region" aria-label={`Bảng dữ liệu, ${total.toLocaleString("vi-VN")} dòng, cuộn để xem hết`}>
        <table aria-rowcount={total + 1}>
          <caption className="sr-only">Toàn bộ bảng dữ liệu</caption>
          <thead><tr aria-rowindex={1}><th scope="col" className="row-no">#</th>{columns.map((column) => <th scope="col" key={column} title={column}>{column}</th>)}</tr></thead>
          <tbody>
            {range.start > 0 && <tr className="vspacer" aria-hidden="true"><td colSpan={span} style={{ height: range.start * rowHeight }} /></tr>}
            {shown.map((index) => {
              const row = rowAt(index);
              return (
                <tr key={index} data-row aria-rowindex={index + 2}>
                  <td className="row-no">{(index + 1).toLocaleString("vi-VN")}</td>
                  {columns.map((column) => {
                    const text = row ? String(row[column] ?? "") : "…";
                    return <td key={column} title={text.length > 24 ? text : undefined}>{text}</td>;
                  })}
                </tr>
              );
            })}
            {range.end < total && <tr className="vspacer" aria-hidden="true"><td colSpan={span} style={{ height: (total - range.end) * rowHeight }} /></tr>}
          </tbody>
        </table>
      </div>
      {error && <p className="notice notice-error" role="alert">{error}<button type="button" onClick={() => setError("")}>Thử lại</button></p>}
    </>
  );
}
