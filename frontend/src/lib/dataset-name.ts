/**
 * Ten bo du lieu de hien thi: ten nguoi dung go khi tai len (giu dau, giu khoang
 * trang). Bo tai len truoc khi co ten thi hien ma bo. Ma bo van la thu di vao
 * duong dan va lien ket.
 */
export function shownName(id: string, label?: string | null): string {
  const tidy = (label ?? "").trim();
  return tidy || id;
}
