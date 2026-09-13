import assert from "node:assert/strict";
import { test } from "node:test";
import { blocksFor, ROW_HEIGHT, visibleRange } from "./virtual-rows.ts";

test("mot bang 6.819 dong chi dung vai chuc dong luc mo", () => {
  const range = visibleRange(0, 480, 6819);
  assert.equal(range.start, 0);
  assert.ok(range.end - range.start <= 40, `dung ${range.end - range.start} dong`);
});

test("cuon toi giua bang thi khung nhin nam tron trong khoang dung", () => {
  const range = visibleRange(3000 * ROW_HEIGHT, 480, 6819);
  assert.ok(range.start <= 3000);
  assert.ok(range.end >= 3000 + 480 / ROW_HEIGHT);
  assert.ok(range.end - range.start <= 40);
});

test("cuon toi cuoi bang thi dung dung cac dong cuoi", () => {
  const range = visibleRange(6819 * ROW_HEIGHT, 480, 6819);
  assert.equal(range.end, 6819);
  assert.ok(range.start > 6700);
});

test("chieu cao dong do duoc thay cho mac dinh", () => {
  assert.deepEqual(visibleRange(330, 330, 1000, 33, 0), { start: 10, end: 21 });
});

test("bang rong khong dung gi, so am van ra khoang hop le", () => {
  assert.deepEqual(visibleRange(0, 480, 0), { start: 0, end: 0 });
  const range = visibleRange(-50, -10, 100);
  assert.equal(range.start, 0);
  assert.ok(range.end > 0 && range.end <= 100);
});

test("khoi can tai phu dung khoang dang hien, ke ca khi vat qua ranh gioi", () => {
  assert.deepEqual(blocksFor({ start: 0, end: 24 }), [0]);
  assert.deepEqual(blocksFor({ start: 190, end: 230 }), [0, 1]);
  assert.deepEqual(blocksFor({ start: 6792, end: 6819 }), [33, 34]);
  assert.deepEqual(blocksFor({ start: 5, end: 5 }), []);
});
