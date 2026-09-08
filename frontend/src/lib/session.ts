/**
 * Noi chuyen voi /api/session — kenh JSON cung cookie, cung Guard voi form
 * HTML cu (xem app.py). Next rewrite /api/* sang FastAPI nen trinh duyet chi
 * thay mot origin: khong can CORS, cookie tu dong di kem moi request.
 */

export interface SessionPayload {
  signed_in: boolean;
  error?: string;
}

/** Trang thai hien tai: dang nhap chua? (GET /api/session, khong redirect.) */
export async function getSession(): Promise<SessionPayload> {
  const answer = await fetch("/api/session", {
    method: "GET",
    credentials: "same-origin",
  });
  return (await answer.json()) as SessionPayload;
}

/** Dang nhap: dung thi co cookie `asys_session`, sai thi 401 + loi. */
export async function signIn(password: string): Promise<SessionPayload> {
  const answer = await fetch("/api/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify({ password }),
  });
  return (await answer.json()) as SessionPayload;
}

/** Dang xuat: xoa phien trong bo nho FastAPI va cookie tren trinh duyet. */
export async function signOut(): Promise<SessionPayload> {
  const answer = await fetch("/api/session", {
    method: "DELETE",
    credentials: "same-origin",
  });
  return (await answer.json()) as SessionPayload;
}
