import assert from "node:assert/strict";
import { test } from "node:test";
import { applyLayout, formatText, inline, toGrid, type Widget } from "./dashboard.ts";

const widgets: Widget[] = [
  { id: "a".repeat(12), kind: "text", title: "", layout: { x: 0, y: 0, w: 12, h: 2 }, text: { style: "title", text: "BÁO CÁO" } },
  { id: "b".repeat(12), kind: "bi", title: "", layout: { x: 0, y: 2, w: 6, h: 9 }, bi: { dataset: "bankruptcy", state: { x: "Bankrupt?", y: "Debt ratio %", aggregation: "mean", color: null, filters: [], chart: "auto" } } },
];

test("luoi: moi widget mot o, bieu do co co nho nhat lon hon van ban", () => {
  const grid = toGrid(widgets);
  assert.deepEqual(grid[0], { i: "a".repeat(12), x: 0, y: 0, w: 12, h: 2, minW: 2, minH: 1 });
  assert.equal(grid[1].minW, 3);
  assert.equal(grid[1].minH, 5);
});

test("keo doi cho chi doi widget da di chuyen; khong doi gi thi giu nguyen tham chieu", () => {
  assert.equal(applyLayout(widgets, toGrid(widgets)), widgets);
  const moved = applyLayout(widgets, [{ i: "b".repeat(12), x: 6, y: 0, w: 6, h: 12 }]);
  assert.notEqual(moved, widgets);
  assert.deepEqual(moved[1].layout, { x: 6, y: 0, w: 6, h: 12 });
  assert.equal(moved[0], widgets[0]);
});

test("dam, nghieng, va dau khong dong thi giu nguyen la chu", () => {
  assert.deepEqual(inline("Doanh thu **tăng 12%** so với *quý 2*"), [
    { text: "Doanh thu ", bold: false, italic: false },
    { text: "tăng 12%", bold: true, italic: false },
    { text: " so với ", bold: false, italic: false },
    { text: "quý 2", bold: false, italic: true },
  ]);
  assert.deepEqual(inline("2 * 3 = 6"), [{ text: "2 * 3 = 6", bold: false, italic: false }]);
});

test("dong trong ngan doan, gach dau dong lien nhau thanh danh sach", () => {
  const blocks = formatText("Tóm tắt điều hành\nQuý 3 khả quan.\n\n- Doanh thu tăng\n- Chi phí giảm\nKết luận cuối");
  assert.deepEqual(blocks.map((block) => block.kind), ["paragraph", "list", "paragraph"]);
  assert.equal(blocks[0].kind === "paragraph" && blocks[0].lines.length, 2);
  assert.equal(blocks[1].kind === "list" && blocks[1].items.length, 2);
});

test("chu go tay khong bao gio thanh the HTML", () => {
  const blocks = formatText("<script>alert(1)</script>");
  assert.deepEqual(blocks, [{ kind: "paragraph", lines: [[{ text: "<script>alert(1)</script>", bold: false, italic: false }]] }]);
  assert.deepEqual(formatText("  \n \n"), []);
});
