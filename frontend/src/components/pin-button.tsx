"use client";

import Link from "next/link";
import { useId, useRef, useState, type FormEvent } from "react";
import { describeError, getJson, sendJson } from "@/lib/api";
import type { Dashboard, DashboardSummary, WidgetDraft } from "@/lib/dashboard";

const NEW = "__moi__";

function PinIcon() {
  return <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 17v5" /><path d="M9 10.8V5h6v5.8a2 2 0 0 0 .9 1.7L18 14v2H6v-2l2.1-1.5a2 2 0 0 0 .9-1.7Z" /><path d="M8 3h8" /></svg>;
}

/**
 * Nut Ghim dung chung cho hai luong (the ket luan AI, bieu do Tu phan tich).
 * Bam thi hoi "Lưu vào Dashboard nào?": chon mot Dashboard co san hoac tao moi.
 * Hop thoai la <dialog> goc cua trinh duyet: Esc de dong, giu tieu diem ben trong.
 */
export default function PinButton({ draft, label = "Ghim lên Dashboard" }: { draft: WidgetDraft; label?: string }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const heading = useId();
  const group = useId();
  const [boards, setBoards] = useState<DashboardSummary[] | null>(null);
  const [chosen, setChosen] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState<{ id: string; name: string } | null>(null);

  async function open() {
    setError("");
    setDone(null);
    setName("");
    setBoards(null);
    dialog.current?.showModal();
    try {
      const payload = await getJson<{ dashboards: DashboardSummary[] }>("/api/dashboards");
      setBoards(payload.dashboards);
      setChosen(payload.dashboards[0]?.id ?? NEW);
    } catch (reason) {
      setError(describeError(reason, "Không đọc được danh sách Dashboard."));
      setBoards([]);
      setChosen(NEW);
    }
  }

  async function pin(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      let target = boards?.find((board) => board.id === chosen) ?? null;
      if (chosen === NEW) {
        const created = await sendJson<Dashboard>("/api/dashboards", "POST", { name });
        target = { id: created.id, name: created.name, widgets: 0, updated_at: created.updated_at };
      }
      if (!target) throw new Error("chua chon Dashboard");
      await sendJson<Dashboard>(`/api/dashboards/${encodeURIComponent(target.id)}/widgets`, "POST", draft);
      setDone({ id: target.id, name: target.name });
    } catch (reason) {
      setError(describeError(reason, "Không ghim được. Kiểm tra kết nối rồi thử lại."));
    } finally {
      setBusy(false);
    }
  }

  const canPin = Boolean(boards) && !busy && (chosen !== NEW || name.trim() !== "");
  return (
    <>
      <button type="button" className="pin-button" onClick={() => void open()} title={label} aria-label={label}><PinIcon /><span>Ghim</span></button>
      <dialog ref={dialog} className="pin-dialog" aria-labelledby={heading}>
        <form onSubmit={(event) => void pin(event)}>
          <h2 id={heading}>Lưu vào Dashboard nào?</h2>
          {!boards ? <p className="muted">Đang tải danh sách Dashboard…</p> : (
            <fieldset className="pin-choices" disabled={Boolean(done)}>
              <legend className="sr-only">Chọn Dashboard</legend>
              {boards.map((board) => (
                <label key={board.id} className="choice">
                  <input type="radio" name={group} value={board.id} checked={chosen === board.id} onChange={() => setChosen(board.id)} />
                  <span><b>{board.name}</b><small>{board.widgets} widget</small></span>
                </label>
              ))}
              <label className="choice">
                <input type="radio" name={group} value={NEW} checked={chosen === NEW} onChange={() => setChosen(NEW)} />
                <span><b>Tạo Dashboard mới</b></span>
              </label>
              {chosen === NEW && <input className="bi-search" value={name} onChange={(event) => setName(event.target.value)} placeholder="Tên Dashboard, ví dụ: Báo cáo quý 3" aria-label="Tên Dashboard mới" maxLength={120} autoFocus />}
            </fieldset>
          )}
          {error && <p className="error" role="alert">{error}</p>}
          {done && <p className="notice notice-info" role="status"><span>Đã ghim vào “{done.name}”.</span><Link className="text-link" href={`/bang-dieu-khieu?bang=${encodeURIComponent(done.id)}`}>Mở Dashboard →</Link></p>}
          <div className="form-actions">
            <button type="button" className="button-secondary" onClick={() => dialog.current?.close()}>{done ? "Đóng" : "Huỷ"}</button>
            {!done && <button type="submit" className="button-primary" disabled={!canPin}>{busy ? "Đang ghim…" : "Ghim"}</button>}
          </div>
        </form>
      </dialog>
    </>
  );
}
