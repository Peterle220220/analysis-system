import assert from "node:assert/strict";
import { test } from "node:test";
import { groupDatasets } from "./bi.ts";
import { shownName } from "./dataset-name.ts";

test("ten hien thi la ten nguoi dung go, giu nguyen dau", () => {
  assert.equal(shownName("bao_cao_tai_chinh_mb", "Báo cáo tài chính MB"), "Báo cáo tài chính MB");
});

test("bo chua co ten thi hien ma bo", () => {
  assert.equal(shownName("bankruptcy"), "bankruptcy");
  assert.equal(shownName("bankruptcy", "   "), "bankruptcy");
  assert.equal(shownName("bankruptcy", null), "bankruptcy");
});

test("o tim bo du lieu tim ca theo ten hien thi, khong can go dau", () => {
  const folders = [
    { run_id: "bao_cao_tai_chinh_mb", label: "Báo cáo tài chính MB", views: [] },
    { run_id: "bankruptcy", views: [] },
  ];
  assert.deepEqual(groupDatasets(folders, "tài chính").library.map((item) => item.run_id), ["bao_cao_tai_chinh_mb"]);
  assert.deepEqual(groupDatasets(folders, "bank").library.map((item) => item.run_id), ["bankruptcy"]);
});
