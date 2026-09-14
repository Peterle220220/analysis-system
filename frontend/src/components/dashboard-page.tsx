"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import ReactGridLayout, { useContainerWidth, verticalCompactor } from "react-grid-layout";
import "react-grid-layout/css/styles.css";
import "react-resizable/css/styles.css";
import BiChart from "@/components/bi-chart";
import { ChartBlock } from "@/components/dataset-pages";
import { LoadState, useResource } from "@/components/read-pages";
import { describeError, sendJson, type RoundPayload } from "@/lib/api";
import { formatNumber, present, toQuery, type BiResult } from "@/lib/bi";
import {
  applyLayout,
  formatText,
  GRID_COLUMNS,
  ROW_HEIGHT,
  TEXT_STYLES,
  toGrid,
  type BiSource,
  type ClaimSource,
  type Dashboard,
  type DashboardSummary,
  type Inline,
  type TextBody,
  type TextStyle,
  type Widget,
} from "@/lib/dashboard";

const enc = (value: string) => encodeURIComponent(value);
const SAVE_DELAY_MS = 600;

/** Widget Tu phan tich: chay lai cau hinh keo tha moi lan mo (widget "song"). */
function BiWidget({ source }: { source: BiSource }) {
  const [shown, setShown] = useState<{ result?: BiResult; error?: string }>({});
  const { chart, ...spec } = source.state;
  const key = JSON.stringify(source);

  useEffect(() => {
    let alive = true;
    const query = toQuery(spec, chart);
    if (!query) {
      setShown({ error: "Bản này chưa có cột nào ở trục." });
      return;
    }
    setShown({});
    sendJson<BiResult>(`/api/bi/${enc(source.dataset)}/query`, "POST", query)
      .then((result) => { if (alive) setShown({ result: present(result, query, chart) }); })
      .catch((reason: unknown) => { if (alive) setShown({ error: describeError(reason, "Không tính được biểu đồ này.") }); });
    return () => { alive = false; };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps

  if (shown.error) return <p className="widget-missing">{shown.error} <span className="muted">(bộ dữ liệu {source.dataset})</span></p>;
  if (!shown.result) return <p className="status-line">Đang tính…</p>;
  const result = shown.result;
  return (
    <div className="widget-content">
      <p className="widget-title">{result.title}</p>
      {result.kind === "single" && chart !== "table" ? (
        <p className="bi-kpi"><b>{formatNumber(result.series[0]?.values[0])}</b><span>{result.value_label}</span></p>
      ) : (
        <BiChart result={result} chart={chart} compact />
      )}
    </div>
  );
}

/** Widget ket luan AI: doc lai tu luot hoi goc moi lan mo. */
function ClaimWidget({ source }: { source: ClaimSource }) {
  const resource = useResource<RoundPayload>(`/api/datasets/${enc(source.dataset)}/rounds/${enc(source.round)}`);
  if (resource.error && !resource.data) return <p className="widget-missing">Không đọc được lượt hỏi {source.round}: {resource.error}</p>;
  if (!resource.data) return <p className="status-line">Đang tải kết luận…</p>;
  const answer = resource.data.answer;
  const claims = Array.isArray(answer?.claims) ? answer.claims as Array<Record<string, unknown>> : [];
  const claim = claims[source.index];
  if (!claim) return <p className="widget-missing">Kết luận này không còn trong lượt hỏi {source.round}.</p>;
  const chart = Array.isArray(resource.data.charts) ? resource.data.charts[source.index] : "";
  return (
    <div className="widget-content">
      {resource.data.question && <p className="muted widget-question">{resource.data.question}</p>}
      <p className="claim-text">{String(claim.claim ?? "")}</p>
      {chart ? <ChartBlock html={chart} /> : null}
      <Link className="text-link" href={`/bo/${enc(source.dataset)}/pt/${enc(source.round)}`}>Mở lượt hỏi →</Link>
    </div>
  );
}

function Pieces({ parts }: { parts: Inline[] }) {
  return <>{parts.map((part, index) => (part.bold ? <strong key={index}>{part.text}</strong> : part.italic ? <em key={index}>{part.text}</em> : <span key={index}>{part.text}</span>))}</>;
}

/** Hop van ban: tieu de lon, tieu de phu, doan van; **dam**, *nghieng*, gach dau dong. Khong bao gio thanh HTML. */
function TextWidget({ body, onChange }: { body: TextBody; onChange: (next: TextBody) => void }) {
  const [editing, setEditing] = useState(!body.text.trim());
  const [draft, setDraft] = useState(body);

  if (editing) {
    return (
      <div className="widget-text-edit">
        <select className="agg-select" aria-label="Kiểu chữ" value={draft.style} onChange={(event) => setDraft({ ...draft, style: event.target.value as TextStyle })}>
          {TEXT_STYLES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
        </select>
        <textarea className="widget-textarea" value={draft.text} onChange={(event) => setDraft({ ...draft, text: event.target.value })} placeholder={"Gõ tiêu đề hoặc đoạn tóm tắt.\n**chữ đậm**, *chữ nghiêng*, dòng bắt đầu bằng - thành gạch đầu dòng."} aria-label="Nội dung hộp văn bản" maxLength={5000} autoFocus />
        <div className="form-actions">
          <button className="button-primary" type="button" onClick={() => { onChange(draft); setEditing(false); }}>Xong</button>
          {body.text.trim() && <button className="button-secondary" type="button" onClick={() => { setDraft(body); setEditing(false); }}>Huỷ</button>}
        </div>
      </div>
    );
  }
  return (
    <div className={`widget-text text-${body.style}`} onDoubleClick={() => setEditing(true)}>
      {formatText(body.text).map((block, index) => block.kind === "list" ? (
        <ul key={index}>{block.items.map((item, at) => <li key={at}><Pieces parts={item} /></li>)}</ul>
      ) : (
        <p key={index}>{block.lines.map((line, at) => <span key={at}>{at > 0 && <br />}<Pieces parts={line} /></span>)}</p>
      ))}
      <button className="button-quiet widget-edit" type="button" onClick={() => setEditing(true)}>Sửa</button>
    </div>
  );
}

function widgetLabel(widget: Widget): string {
  if (widget.title) return widget.title;
  return widget.kind === "text" ? "Hộp văn bản" : widget.kind === "bi" ? "Tự phân tích" : "Kết luận";
}

function Frame({ widget, onRemove, children }: { widget: Widget; onRemove: () => void; children: ReactNode }) {
  return (
    <>
      <div className="widget-bar">
        <span className="widget-drag" title="Kéo để đổi chỗ">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="9" cy="6" r="1.6" /><circle cx="15" cy="6" r="1.6" /><circle cx="9" cy="12" r="1.6" /><circle cx="15" cy="12" r="1.6" /><circle cx="9" cy="18" r="1.6" /><circle cx="15" cy="18" r="1.6" /></svg>
          <span className="widget-label">{widgetLabel(widget)}</span>
        </span>
        <button type="button" className="chip-remove" aria-label={`Bỏ widget ${widgetLabel(widget)}`} title="Bỏ widget" onClick={onRemove}>×</button>
      </div>
      <div className="widget-body">{children}</div>
    </>
  );
}

/** Luoi 12 cot: keo bang thanh tieu de, keo goc de doi co, tu hit vao o. */
function Grid({ board, onWidgets }: { board: Dashboard; onWidgets: (widgets: Widget[]) => void }) {
  const { width, containerRef, mounted } = useContainerWidth();
  const layout = useMemo(() => toGrid(board.widgets), [board.widgets]);

  function remove(widget: Widget) {
    if (!window.confirm(`Bỏ widget “${widgetLabel(widget)}” khỏi Dashboard?`)) return;
    onWidgets(board.widgets.filter((item) => item.id !== widget.id));
  }

  function setText(widget: Widget, text: TextBody) {
    onWidgets(board.widgets.map((item) => (item.id === widget.id && item.kind === "text" ? { ...item, text } : item)));
  }

  return (
    <div ref={containerRef} className="board-canvas">
      {mounted && (
        <ReactGridLayout
          width={width}
          layout={layout}
          gridConfig={{ cols: GRID_COLUMNS, rowHeight: ROW_HEIGHT, margin: [12, 12] }}
          dragConfig={{ enabled: true, handle: ".widget-drag" }}
          resizeConfig={{ enabled: true }}
          compactor={verticalCompactor}
          onLayoutChange={(next: ReadonlyArray<{ i: string; x: number; y: number; w: number; h: number }>) => {
            const moved = applyLayout(board.widgets, [...next]);
            if (moved !== board.widgets) onWidgets(moved);
          }}
        >
          {board.widgets.map((widget) => (
            <div key={widget.id} className={`widget widget-${widget.kind}`}>
              <Frame widget={widget} onRemove={() => remove(widget)}>
                {widget.kind === "bi" ? <BiWidget source={widget.bi} /> : widget.kind === "claim" ? <ClaimWidget source={widget.claim} /> : <TextWidget body={widget.text} onChange={(text) => setText(widget, text)} />}
              </Frame>
            </div>
          ))}
        </ReactGridLayout>
      )}
    </div>
  );
}

function BoardEditor({ id, onChanged, onDeleted }: { id: string; onChanged: () => void; onDeleted: () => void }) {
  const resource = useResource<Dashboard>(`/api/dashboards/${enc(id)}`);
  const [board, setBoard] = useState<Dashboard | null>(null);
  const [name, setName] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const timer = useRef<number | undefined>(undefined);
  const latest = useRef<Dashboard | null>(null);

  useEffect(() => {
    if (resource.data && !board) {
      setBoard(resource.data);
      setName(resource.data.name);
      latest.current = resource.data;
    }
  }, [resource.data, board]);

  async function push(value: Dashboard) {
    try {
      await sendJson<Dashboard>(`/api/dashboards/${enc(id)}`, "PUT", { name: value.name, widgets: value.widgets });
      setStatus("Đã lưu");
      setError("");
      onChanged();
    } catch (reason) {
      setStatus("");
      setError(describeError(reason, "Không lưu được Dashboard."));
    }
  }

  // Doi xong 0,6 giay moi luu, de keo lien tay khong ban tung lan len may chu.
  function change(next: Dashboard) {
    setBoard(next);
    latest.current = next;
    setStatus("Đang lưu…");
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => { timer.current = undefined; void push(next); }, SAVE_DELAY_MS);
  }

  // Ban luu con cho phai day di truoc khi them widget (khong thi lan luu sau ghi
  // de mat widget vua them), va truoc khi roi trang.
  async function flush() {
    if (timer.current === undefined || !latest.current) return;
    window.clearTimeout(timer.current);
    timer.current = undefined;
    await push(latest.current);
  }

  useEffect(() => () => {
    if (timer.current !== undefined && latest.current) {
      window.clearTimeout(timer.current);
      const value = latest.current;
      void sendJson(`/api/dashboards/${enc(id)}`, "PUT", { name: value.name, widgets: value.widgets }).catch(() => undefined);
    }
  }, [id]);

  async function addText() {
    await flush();
    try {
      const updated = await sendJson<Dashboard>(`/api/dashboards/${enc(id)}/widgets`, "POST", { kind: "text", title: "", text: { style: "body", text: "" } });
      setBoard(updated);
      latest.current = updated;
      onChanged();
    } catch (reason) {
      setError(describeError(reason, "Không thêm được hộp văn bản."));
    }
  }

  async function forget() {
    if (!board || !window.confirm(`Xoá Dashboard “${board.name}”? Các widget trên đó mất theo; bản phân tích và lượt hỏi gốc vẫn còn.`)) return;
    window.clearTimeout(timer.current);
    timer.current = undefined;
    try {
      await sendJson(`/api/dashboards/${enc(id)}`, "DELETE", {});
      onDeleted();
    } catch (reason) {
      setError(describeError(reason, "Không xoá được Dashboard."));
    }
  }

  function rename(event: FormEvent) {
    event.preventDefault();
    if (board && name.trim() && name.trim() !== board.name) change({ ...board, name: name.trim() });
  }

  if (resource.error && !resource.data) return <LoadState error={resource.error} retry={resource.retry} />;
  if (!board) return <p className="status-line">Đang mở Dashboard…</p>;

  return (
    <>
      <div className="board-toolbar">
        <Link className="text-link" href="/bang-dieu-khieu">← Tất cả Dashboard</Link>
        <form className="board-name" onSubmit={rename}>
          <label htmlFor="board-name" className="sr-only">Tên Dashboard</label>
          <input id="board-name" className="bi-search" value={name} onChange={(event) => setName(event.target.value)} onBlur={rename} maxLength={120} />
        </form>
        <span className="muted" role="status">{status}</span>
        <button className="button-primary" type="button" onClick={() => void addText()}>Thêm hộp văn bản</button>
        <button className="button-danger" type="button" onClick={() => void forget()}>Xoá Dashboard</button>
      </div>
      {error && <p className="notice notice-error" role="alert">{error}</p>}
      {board.widgets.length === 0 ? (
        <div className="empty-state"><h2>Dashboard trống</h2><p>Bấm <b>Ghim</b> trên một thẻ kết luận (trang lượt hỏi) hoặc trên một biểu đồ ở Tự phân tích, rồi chọn Dashboard này. Hoặc thêm một hộp văn bản để viết tiêu đề và tóm tắt.</p></div>
      ) : (
        <Grid board={board} onWidgets={(widgets) => change({ ...board, widgets })} />
      )}
    </>
  );
}

function BoardList({ onOpen }: { onOpen: (id: string) => void }) {
  const list = useResource<{ dashboards: DashboardSummary[] }>("/api/dashboards");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function create(event: FormEvent) {
    event.preventDefault();
    if (busy || !name.trim()) return;
    setBusy(true);
    setError("");
    try {
      const created = await sendJson<Dashboard>("/api/dashboards", "POST", { name });
      onOpen(created.id);
    } catch (reason) {
      setError(describeError(reason, "Không tạo được Dashboard."));
    } finally {
      setBusy(false);
    }
  }

  if (list.error && !list.data) return <LoadState error={list.error} retry={list.retry} />;
  return (
    <>
      <form className="card form-card board-create" onSubmit={(event) => void create(event)}>
        <label htmlFor="new-board">Tạo Dashboard mới</label>
        <div className="save-bar">
          <input id="new-board" className="bi-search" value={name} onChange={(event) => setName(event.target.value)} placeholder="Ví dụ: Báo cáo tài chính quý 3" maxLength={120} />
          <button className="button-primary" type="submit" disabled={busy || !name.trim()}>{busy ? "Đang tạo…" : "Tạo"}</button>
        </div>
        {error && <p className="error" role="alert">{error}</p>}
      </form>
      {!list.data ? <p className="status-line">Đang tải…</p> : list.data.dashboards.length === 0 ? (
        <div className="empty-state"><h2>Chưa có Dashboard nào</h2><p>Tạo một Dashboard ở trên, hoặc bấm <b>Ghim</b> trên một thẻ kết luận hay một biểu đồ Tự phân tích: hộp thoại cho tạo Dashboard mới ngay lúc ghim.</p></div>
      ) : (
        <ul className="cards">
          {list.data.dashboards.map((board) => (
            <li className="card" key={board.id}>
              <Link className="card-title" href={`/bang-dieu-khieu?bang=${enc(board.id)}`}>{board.name}</Link>
              <span className="muted">{board.widgets} widget · sửa lúc {new Date(board.updated_at).toLocaleString("vi-VN")}</span>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

/** Trang Dashboard: danh sach cac Dashboard, hoac mot Dashboard mo ra thanh luoi widget. */
export default function DashboardPage() {
  const router = useRouter();
  const params = useSearchParams();
  const boardId = params.get("bang");
  const [refresh, setRefresh] = useState(0);
  return (
    <>
      <div className="page-heading"><div><p className="eyebrow">DASHBOARD</p><h1>Không gian trình bày</h1><p className="muted">Ghép kết luận của lượt hỏi AI, biểu đồ Tự phân tích và hộp văn bản trên một lưới. Số liệu được tính lại mỗi lần mở.</p></div></div>
      {boardId ? (
        <BoardEditor key={boardId} id={boardId} onChanged={() => setRefresh((value) => value + 1)} onDeleted={() => router.replace("/bang-dieu-khieu")} />
      ) : (
        <BoardList key={refresh} onOpen={(id) => router.push(`/bang-dieu-khieu?bang=${enc(id)}`)} />
      )}
    </>
  );
}
