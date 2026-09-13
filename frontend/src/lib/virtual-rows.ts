// Bang cuon ao: chi dung cac dong dang nam trong khung nhin, cong vai dong dem.
// Mot bang 6.819 dong ma dung ca 6.819 the <tr> thi trinh duyet treo; o day so
// the <tr> chi phu thuoc chieu cao khung nhin, khong phu thuoc do dai bang.
//
// Tach rieng thanh ham thuan, khong import gi, de test duoc bang Node tran.

/** Chieu cao mac dinh cua mot dong (px), khop voi 2rem trong CSS. */
export const ROW_HEIGHT = 32;
/** So dong dem moi phia, de cuon nhanh khong thay khoang trang. */
export const OVERSCAN = 8;
/** So dong moi lan xin tu may chu. */
export const BLOCK_SIZE = 200;

export type Range = { start: number; end: number };

/** Cac dong can dung: tu `start` toi truoc `end`. */
export function visibleRange(
  scrollTop: number,
  viewport: number,
  total: number,
  rowHeight: number = ROW_HEIGHT,
  overscan: number = OVERSCAN,
): Range {
  if (total <= 0 || rowHeight <= 0) return { start: 0, end: 0 };
  const first = Math.floor(Math.max(0, scrollTop) / rowHeight);
  const count = Math.ceil(Math.max(0, viewport) / rowHeight) + 1;
  const start = Math.max(0, Math.min(total - 1, first) - overscan);
  const end = Math.min(total, first + count + overscan);
  return { start, end: Math.max(start, end) };
}

/** Cac khoi (moi khoi `blockSize` dong) phai co trong tay de dung khoang nay. */
export function blocksFor(range: Range, blockSize: number = BLOCK_SIZE): number[] {
  if (range.end <= range.start || blockSize <= 0) return [];
  const first = Math.floor(range.start / blockSize);
  const last = Math.floor((range.end - 1) / blockSize);
  return Array.from({ length: last - first + 1 }, (_, index) => first + index);
}
