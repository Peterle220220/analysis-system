// Dashboard: kieu du lieu, dinh dang van ban gon, va ap bo cuc luoi. Ham thuan,
// chi import kieu, de test duoc bang Node tran.

import type { ViewState } from "./bi.ts";

export const GRID_COLUMNS = 12;
export const ROW_HEIGHT = 40;

export type Layout = { x: number; y: number; w: number; h: number };
export type TextStyle = "title" | "subtitle" | "body";

export type BiSource = { dataset: string; state: ViewState };
export type ClaimSource = { dataset: string; round: string; index: number };
export type TextBody = { style: TextStyle; text: string };

export type Widget =
  | { id: string; kind: "bi"; title: string; layout: Layout; bi: BiSource; claim?: null; text?: null }
  | { id: string; kind: "claim"; title: string; layout: Layout; claim: ClaimSource; bi?: null; text?: null }
  | { id: string; kind: "text"; title: string; layout: Layout; text: TextBody; bi?: null; claim?: null };

export type WidgetDraft =
  | { kind: "bi"; title: string; bi: BiSource }
  | { kind: "claim"; title: string; claim: ClaimSource }
  | { kind: "text"; title: string; text: TextBody };

export type Dashboard = { id: string; name: string; widgets: Widget[]; created_at: string; updated_at: string };
export type DashboardSummary = { id: string; name: string; widgets: number; updated_at: string };

export const TEXT_STYLES: ReadonlyArray<{ value: TextStyle; label: string }> = [
  { value: "title", label: "Tiêu đề lớn" },
  { value: "subtitle", label: "Tiêu đề phụ" },
  { value: "body", label: "Đoạn văn" },
];

/** Co nho nhat de widget con doc duoc: bieu do can rong, van ban thi hep duoc. */
export function minimumSize(widget: Widget): { minW: number; minH: number } {
  return widget.kind === "text" ? { minW: 2, minH: 1 } : { minW: 3, minH: 5 };
}

export type GridItem = { i: string; x: number; y: number; w: number; h: number; minW: number; minH: number };

export function toGrid(widgets: Widget[]): GridItem[] {
  return widgets.map((widget) => ({ i: widget.id, ...widget.layout, ...minimumSize(widget) }));
}

/**
 * Ap bo cuc luoi vua keo/doi co vao danh sach widget. Tra ve chinh danh sach cu
 * (cung tham chieu) khi khong co gi doi, de khong ghi lai may chu vo ich.
 */
export function applyLayout(widgets: Widget[], grid: Array<{ i: string; x: number; y: number; w: number; h: number }>): Widget[] {
  const placed = new Map(grid.map((item) => [item.i, item]));
  let changed = false;
  const next = widgets.map((widget) => {
    const item = placed.get(widget.id);
    if (!item) return widget;
    const layout = { x: item.x, y: item.y, w: item.w, h: item.h };
    const same = layout.x === widget.layout.x && layout.y === widget.layout.y && layout.w === widget.layout.w && layout.h === widget.layout.h;
    if (same) return widget;
    changed = true;
    return { ...widget, layout };
  });
  return changed ? next : widgets;
}

export type Inline = { text: string; bold: boolean; italic: boolean };
export type Block = { kind: "paragraph"; lines: Inline[][] } | { kind: "list"; items: Inline[][] };

const BULLET = /^\s*[-*]\s+/;

/** **dam** va *nghieng* trong mot dong; dau khong dong thi giu nguyen la chu. */
export function inline(line: string): Inline[] {
  const parts: Inline[] = [];
  const pattern = /\*\*([^*]+)\*\*|\*([^*]+)\*/g;
  let last = 0;
  for (const match of line.matchAll(pattern)) {
    const at = match.index ?? 0;
    if (at > last) parts.push({ text: line.slice(last, at), bold: false, italic: false });
    if (match[1] !== undefined) parts.push({ text: match[1], bold: true, italic: false });
    else parts.push({ text: match[2], bold: false, italic: true });
    last = at + match[0].length;
  }
  if (last < line.length) parts.push({ text: line.slice(last), bold: false, italic: false });
  return parts;
}

/**
 * Van ban go tay thanh cac khoi de ve bang phan tu React (khong bao gio thanh
 * HTML): dong trong ngan doan; dong bat dau "- " hay "* " lien nhau la mot danh sach.
 */
export function formatText(text: string): Block[] {
  const blocks: Block[] = [];
  let paragraph: Inline[][] = [];
  let list: Inline[][] = [];
  const flushParagraph = () => { if (paragraph.length) { blocks.push({ kind: "paragraph", lines: paragraph }); paragraph = []; } };
  const flushList = () => { if (list.length) { blocks.push({ kind: "list", items: list }); list = []; } };
  for (const raw of text.replace(/\r\n?/g, "\n").split("\n")) {
    if (!raw.trim()) { flushParagraph(); flushList(); continue; }
    if (BULLET.test(raw)) { flushParagraph(); list.push(inline(raw.replace(BULLET, ""))); continue; }
    flushList();
    paragraph.push(inline(raw.trim()));
  }
  flushParagraph();
  flushList();
  return blocks;
}
