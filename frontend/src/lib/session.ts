/**
 * Noi chuyen voi /api/session — kenh JSON cung cookie, cung Guard voi form
 * HTML cu (xem app.py). Next rewrite /api/* sang FastAPI nen trinh duyet chi
 * thay mot origin: khong can CORS, cookie tu dong di kem moi request.
 */

import { ApiError, fetchWithTimeout } from "@/lib/api";

export interface SessionPayload {
  signed_in: boolean;
  error?: string;
}

/** Trang thai hien tai: dang nhap chua? (GET /api/session, khong redirect.) */
export async function getSession(): Promise<SessionPayload> {
  const answer = await fetchWithTimeout("/api/session", {
    method: "GET",
    credentials: "same-origin",
  });
  if (!answer.ok) throw new ApiError(answer.status, "Không đọc được trạng thái phiên.");
  return (await answer.json()) as SessionPayload;
}

/** Dang nhap: dung thi co cookie `asys_session`, sai thi 401 + loi. */
export async function signIn(password: string): Promise<SessionPayload> {
  const answer = await fetchWithTimeout("/api/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify({ password }),
  });
  return (await answer.json()) as SessionPayload;
}

/** Dang xuat: xoa phien trong bo nho FastAPI va cookie tren trinh duyet. */
export async function signOut(): Promise<SessionPayload> {
  const answer = await fetchWithTimeout("/api/session", {
    method: "DELETE",
    credentials: "same-origin",
  });
  const payload = (await answer.json()) as SessionPayload;
  if (!answer.ok) throw new ApiError(answer.status, payload.error ?? "Không đăng xuất được.");
  return payload;
}
