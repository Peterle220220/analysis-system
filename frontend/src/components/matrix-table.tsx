"use client";

import { useEffect, useLayoutEffect, useMemo, useRef, useState, type UIEvent } from "react";
import { cellTone, formatNumber, matrixOf, type BiResult } from "@/lib/bi";
import { ROW_HEIGHT, visibleRange } from "@/lib/virtual-rows";

/**
 * Ket qua da gop nhom dang bang ma tran, cuon ao (chi dung cac dong trong khung
 * nhin). Mau nen: duong mot sac, am mot sac, dam theo do lon so voi o lon nhat
 * cung cot; chu van mang mau chu.
 */
export default function MatrixTable({ result }: { result: BiResult }) {
  const matrix = useMemo(() => matrixOf(result), [result]);
  const wrap = useRef<HTMLDivElement>(null);
  const frame = useRef(0);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewport, setViewport] = useState(400);
  const [rowHeight, setRowHeight] = useState(ROW_HEIGHT);
  const total = matrix.rows.length;

  useEffect(() => {
    const node = wrap.current;
    if (!node) return;
    const measure = () => setViewport(node.clientHeight);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  useEffect(() => () => cancelAnimationFrame(frame.current), []);

  useLayoutEffect(() => {
    const first = wrap.current?.querySelector<HTMLTableRowElement>("tbody tr[data-row]");
    const measured = first?.getBoundingClientRect().height ?? 0;
    if (measured > 0 && Math.abs(measured - rowHeight) > 0.5) setRowHeight(measured);
  });

  if (total === 0) return <p className="muted">Không có dòng nào để hiện.</p>;
  const range = visibleRange(scrollTop, viewport, total, rowHeight);
  const span = matrix.columns.length;
  const shown: number[] = [];
  for (let index = range.start; index < range.end; index += 1) shown.push(index);

  function onScroll(event: UIEvent<HTMLDivElement>) {
    const top = event.currentTarget.scrollTop;
    cancelAnimationFrame(frame.current);
    frame.current = requestAnimationFrame(() => setScrollTop(top));
  }

  return (
    <div ref={wrap} className="table-wrap vtable matrix" onScroll={onScroll} tabIndex={0} role="region" aria-label={`Bảng số liệu, ${total.toLocaleString("vi-VN")} dòng`}>
      <table aria-rowcount={total + 1}>
        <caption className="sr-only">{result.title}</caption>
        <thead><tr aria-rowindex={1}>{matrix.columns.map((column, index) => <th scope="col" key={`${index}-${column}`} title={column}>{column}</th>)}</tr></thead>
        <tbody>
          {range.start > 0 && <tr className="vspacer" aria-hidden="true"><td colSpan={span} style={{ height: range.start * rowHeight }} /></tr>}
          {shown.map((index) => {
            const row = matrix.rows[index];
            return (
              <tr key={index} data-row aria-rowindex={index + 2}>
                <th scope="row" title={row.label}>{row.label}</th>
                {row.values.map((value, column) => {
                  const tone = cellTone(value, matrix.largest[column] ?? 0);
                  const hue = tone.sign === "pos" ? "var(--series-1)" : "var(--series-8)";
                  const style = tone.sign === "none" ? undefined : { background: `color-mix(in srgb, ${hue} ${Math.round(8 + tone.strength * 32)}%, transparent)` };
                  return <td key={column} className="tone-cell" style={style}>{formatNumber(value)}</td>;
                })}
              </tr>
            );
          })}
          {range.end < total && <tr className="vspacer" aria-hidden="true"><td colSpan={span} style={{ height: (total - range.end) * rowHeight }} /></tr>}
        </tbody>
      </table>
    </div>
  );
}
