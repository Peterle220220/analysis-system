/**
 * Bang ban nhap chu giai: tach, gom, tim va phat hien trung.
 *
 * Backend van doc o Boi canh dang van ban, moi dong "ten cot = nghia". Bang chi
 * doi cach NGUOI DUNG sua: ho sua tung o, con dau "=" do code dat vao luc gom,
 * nen khong ai con xoa nham no va lam hong dinh dang luu.
 */

/** Mot dong cua ban nhap: ten cot goc (chi doc) va nghia tieng Viet (sua duoc). */
export type GlossaryRow = { column: string; meaning: string };

const SEPARATOR = " = ";

// Nhieu cach goi cho mot cot: dau cham phay, hoac dau gach cheo CO dau cach hai
// ben. Cung luat voi backend (asked_columns.ALTERNATIVES): gach cheo dinh chu nhu
// trong "Net worth/Assets" khong phai dau tach.
const ALTERNATIVES = /\s*;\s*|\s+\/\s+/;

/** Tach cac dong "ten cot = nghia" backend tra ve thanh tung o. */
export function rowsFromLines(lines: string[]): GlossaryRow[] {
  const rows: GlossaryRow[] = [];
  for (const line of lines) {
    const at = line.indexOf(SEPARATOR);
    if (at <= 0) continue;
    const column = line.slice(0, at).trim();
    const meaning = line.slice(at + SEPARATOR.length).trim();
    if (column) rows.push({ column, meaning });
  }
  return rows;
}

/** Gom bang lai dung dinh dang backend doc. O de trong thi bo qua dong do. */
export function linesFromRows(rows: GlossaryRow[]): string {
  return rows
    .map((row) => ({ column: row.column.trim(), meaning: row.meaning.replace(/\s+/g, " ").trim() }))
    .filter((row) => row.column && row.meaning)
    .map((row) => `${row.column}${SEPARATOR}${row.meaning}`)
    .join("\n");
}

/** Chu thuong, bo dau, gom khoang trang: go co dau hay khong dau deu tim thay. */
export function foldText(text: string): string {
  return text
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[đĐ]/g, "d")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim();
}

/** Cac cach goi trong mot o, tach theo dung luat cua backend. */
export function alternatives(meaning: string): string[] {
  return meaning
    .split(ALTERNATIVES)
    .map((term) => term.trim())
    .filter(Boolean);
}

/** Dong nay co khop tu khoa khong, tim tren CA ten cot lan nghia tieng Viet. */
export function matchesQuery(row: GlossaryRow, query: string): boolean {
  const wanted = foldText(query);
  if (!wanted) return true;
  return foldText(row.column).includes(wanted) || foldText(row.meaning).includes(wanted);
}

/**
 * Nhung cach goi (da bo dau) xuat hien o hai cot tro len.
 *
 * Hai cot trung het cach goi thi hoi bang cach goi do ca hai cung khop, va khong
 * may nao tu phan xu duoc. To mau de nguoi duyet sua truoc khi luu.
 */
export function duplicateMeanings(rows: GlossaryRow[]): Set<string> {
  const counts = new Map<string, number>();
  for (const row of rows) {
    const seen = new Set(alternatives(row.meaning).map(foldText).filter(Boolean));
    for (const key of seen) counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return new Set(
    Array.from(counts)
      .filter(([, count]) => count > 1)
      .map(([key]) => key),
  );
}

/** Dong nay co cach goi nao trung voi dong khac khong. */
export function clashes(row: GlossaryRow, duplicates: Set<string>): boolean {
  return alternatives(row.meaning).some((term) => duplicates.has(foldText(term)));
}
