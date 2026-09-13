import assert from "node:assert/strict";
import { test } from "node:test";
import { otherTheme, readTheme, THEME_BOOT_SCRIPT, THEME_STORAGE_KEY } from "./theme.ts";

test("mac dinh la toi, chi 'light' da luu moi ra giao dien sang", () => {
  assert.equal(readTheme(null), "dark");
  assert.equal(readTheme(undefined), "dark");
  assert.equal(readTheme("gi-do-khac"), "dark");
  assert.equal(readTheme("light"), "light");
  assert.equal(readTheme("dark"), "dark");
});

test("nut chuyen doi qua lai giua hai giao dien", () => {
  assert.equal(otherTheme("dark"), "light");
  assert.equal(otherTheme("light"), "dark");
});

type FakeDocument = { documentElement: { dataset: Record<string, string> } };

function boot(storage: { getItem: (key: string) => string | null }): string | undefined {
  const doc: FakeDocument = { documentElement: { dataset: {} } };
  new Function("document", "localStorage", THEME_BOOT_SCRIPT)(doc, storage);
  return doc.documentElement.dataset.theme;
}

test("doan script dau trang dat giao dien truoc khi ve", () => {
  assert.equal(boot({ getItem: () => null }), "dark");
  assert.equal(boot({ getItem: (key) => (key === THEME_STORAGE_KEY ? "light" : null) }), "light");
});

test("khong doc duoc bo nho trinh duyet thi van la toi", () => {
  const blocked = { getItem: (): string | null => { throw new Error("bi chan"); } };
  assert.equal(boot(blocked), "dark");
});
