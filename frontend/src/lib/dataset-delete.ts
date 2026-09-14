/** Xoa han mot bo du lieu: duong API va cau hoi xac nhan noi ro cai gi se mat. */

export function datasetPath(dataset: string): string {
  return `/api/datasets/${encodeURIComponent(dataset)}`;
}

/**
 * Cau hoi truoc khi xoa. Noi ten bo va nhung gi mat theo, vi xoa khong khoi phuc
 * duoc; so ban tu phan tich khong biet (undefined) thi noi chung "neu co".
 */
export function deletePrompt(dataset: string, rounds: number, views?: number): string {
  const parts = ["tệp gốc", "bảng sạch"];
  if (rounds > 0) parts.push(`${rounds} lượt hỏi`);
  if (views === undefined) parts.push("các bản tự phân tích (nếu có)");
  else if (views > 0) parts.push(`${views} bản tự phân tích`);
  return (
    `Xoá hẳn bộ dữ liệu "${dataset}"?\n\n` +
    `Sẽ mất: ${parts.join(", ")}. Không khôi phục được.\n` +
    "Widget trên Dashboard lấy từ bộ này sẽ báo mất nguồn."
  );
}
