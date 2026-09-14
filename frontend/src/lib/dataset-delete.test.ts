import assert from "node:assert/strict";
import { test } from "node:test";
import { datasetPath, deletePrompt } from "./dataset-delete.ts";

test("duong API ma hoa ten bo, khong de ten thanh duong dan", () => {
  assert.equal(datasetPath("bao cao/1"), "/api/datasets/bao%20cao%2F1");
});

test("cau hoi xac nhan noi ro ten bo va nhung gi mat theo", () => {
  const text = deletePrompt("don_hang", 3, 2);
  assert.match(text, /"don_hang"/);
  assert.match(text, /3 lượt hỏi/);
  assert.match(text, /2 bản tự phân tích/);
  assert.match(text, /Không khôi phục được/);
});

test("khong noi '0 luot hoi'; khong biet so ban tu phan tich thi noi 'neu co'", () => {
  const unknown = deletePrompt("hong", 0);
  assert.doesNotMatch(unknown, /0 lượt hỏi/);
  assert.match(unknown, /nếu có/);
  assert.doesNotMatch(deletePrompt("hong", 0, 0), /bản tự phân tích/);
});
