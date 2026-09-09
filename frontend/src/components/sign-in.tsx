"use client";

import { describeError } from "@/lib/api";
import { signIn } from "@/lib/session";
import { useState } from "react";

export default function SignInForm({ onSignedIn }: { onSignedIn: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      const result = await signIn(password);
      if (!result.signed_in) {
        setError(result.error ?? "Không đăng nhập được.");
      } else {
        onSignedIn();
      }
    } catch (reason) {
      setError(describeError(reason, "Máy chủ không trả lời. Kiểm tra kết nối rồi thử lại."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="sign-in-card" onSubmit={submit}>
      <h1>Analysis System</h1>
      <p className="status-line">Nhập mật khẩu để vào bảng điều khiển.</p>
      <label htmlFor="password">Mật khẩu</label>
      <input
        id="password"
        type="password"
        autoFocus
        value={password}
        disabled={busy}
        onChange={(event) => setPassword(event.target.value)}
      />
      <button type="submit" disabled={busy || password.length === 0}>
        {busy ? "Đang mở…" : "Đăng nhập"}
      </button>
      {error && <p className="error" role="alert">{error}</p>}
    </form>
  );
}
