"use client";

import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  TouchSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type Active,
  type Announcements,
  type DragEndEvent,
  type KeyboardCoordinateGetter,
} from "@dnd-kit/core";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import BiChart from "@/components/bi-chart";
import PinButton from "@/components/pin-button";
import { GateForm } from "@/components/dataset-pages";
import { LoadState, useResource, useUploadStatus } from "@/components/read-pages";
import {
  describeError,
  MAX_UPLOAD_BYTES,
  newRequestId,
  sendJson,
  sendMultipart,
  uploadTimeoutMs,
  type DataPayload,
  type DatasetStatusPayload,
  type UploadPayload,
} from "@/lib/api";
import {
  AGGREGATIONS,
  CHARTS,
  chartLabel,
  drop,
  EMPTY_SPEC,
  formatNumber,
  groupDatasets,
  matchesText,
  present,
  refusal,
  remove,
  sanitizeState,
  setAggregation,
  setFilter,
  toQuery,
  usesLegend,
  ZONE_LABELS,
  zoneLabel,
  type Aggregation,
  type BiField,
  type BiResult,
  type Chart,
  type FilterSpec,
  type QueryJson,
  type SavedView,
  type Spec,
  type Zone,
} from "@/lib/bi";
import type { WidgetDraft } from "@/lib/dashboard";

const enc = (value: string) => encodeURIComponent(value);
const ACCEPTED = [".csv", ".xlsx", ".xls"];
const ZONE_ORDER: Zone[] = ["x", "y", "color", "filters"];

type SchemaPayload = { dataset_id: string; rows: number; fields: BiField[] };
type ViewsPayload = { dataset_id: string; views: SavedView[] };
type ValuesPayload =
  | { field: string; role: "dimension"; values: Array<{ value: string; count: number }>; more: boolean }
  | { field: string; role: "measure"; min: number | null; max: number | null };
type Folder = DataPayload["datasets"][number];

function fieldOf(active: Active | null): BiField | null {
  const found = active?.data.current?.field;
  return found ? (found as BiField) : null;
}

// Ban phim: phim mui ten nhay thang giua cac vung tha, thay vi dich tung vai chuc px.
const jumpBetweenZones: KeyboardCoordinateGetter = (event, { context, currentCoordinates }) => {
  const forward = event.code === "ArrowRight" || event.code === "ArrowDown";
  const backward = event.code === "ArrowLeft" || event.code === "ArrowUp";
  if (!forward && !backward) return undefined;
  event.preventDefault();
  const zones = ZONE_ORDER.filter((zone) => context.droppableRects.has(zone));
  const at = context.over ? zones.indexOf(context.over.id as Zone) : -1;
  const next = forward ? Math.min(zones.length - 1, at + 1) : Math.max(0, at - 1);
  const rect = context.droppableRects.get(zones[next]);
  return rect ? { x: rect.left + 12, y: rect.top + 12 } : currentCoordinates;
};

const nameOf = (active: Active) => fieldOf(active)?.name ?? "cột";
const zoneOf = (id: unknown) => ZONE_LABELS[id as Zone] ?? "vùng này";

const announcements: Announcements = {
  onDragStart: ({ active }) => `Đã nhấc cột ${nameOf(active)}. Dùng phím mũi tên để chọn vùng thả.`,
  onDragOver: ({ active, over }) => (over ? `Cột ${nameOf(active)} đang ở trên ${zoneOf(over.id)}.` : `Cột ${nameOf(active)} không ở trên vùng thả nào.`),
  onDragEnd: ({ active, over }) => (over ? `Đã thả cột ${nameOf(active)} vào ${zoneOf(over.id)}.` : `Đã thả cột ${nameOf(active)} ra ngoài, không đổi gì.`),
  onDragCancel: ({ active }) => `Đã huỷ kéo cột ${nameOf(active)}.`,
};

const screenReaderInstructions = {
  draggable: "Nhấn phím cách hoặc Enter để nhấc cột, phím mũi tên để chuyển giữa các vùng thả, phím cách hoặc Enter để thả, Esc để huỷ.",
};

function FieldIcon({ field }: { field: BiField }) {
  if (field.kind === "date") {
    return <span className="field-icon" aria-hidden="true"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M3 10h18M8 3v4M16 3v4" /></svg></span>;
  }
  const mark = field.role === "measure" ? "#" : field.kind === "boolean" ? "0/1" : "Abc";
  return <span className="field-icon" aria-hidden="true">{mark}</span>;
}

function FieldChip({ field }: { field: BiField }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: `field:${field.name}`, data: { field } });
  const role = field.role === "measure" ? "Measure" : "Dimension";
  return (
    <li>
      <button ref={setNodeRef} type="button" className={`field-chip field-${field.role}${isDragging ? " dragging" : ""}`} title={`${field.name} (${role}, ${field.distinct.toLocaleString("vi-VN")} giá trị khác nhau)`} {...listeners} {...attributes}>
        <FieldIcon field={field} />
        <span className="field-name">{field.name}</span>
      </button>
    </li>
  );
}

/**
 * Chi dung dung the dang keo, dat thang vao <body>: khong nam trong thanh ben
 * nen khong thua huong be ngang 100% hay kieu chu cua no.
 */
function DragGhost({ field }: { field: BiField | null }) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  if (!mounted) return null;
  return createPortal(
    <DragOverlay dropAnimation={null}>
      {field ? <span className={`field-chip drag-ghost field-${field.role}`}><FieldIcon field={field} /><span className="field-name">{field.name}</span></span> : null}
    </DragOverlay>,
    document.body,
  );
}

function DropZone({ zone, label, hint, children }: { zone: Zone; label: string; hint: string; children: ReactNode }) {
  const { setNodeRef, isOver, active } = useDroppable({ id: zone });
  const field = fieldOf(active);
  const refused = field ? refusal(zone, field) : "";
  const state = isOver ? (refused ? " over-refused" : " over") : field && !refused ? " can-drop" : "";
  return (
    <section ref={setNodeRef} className={`drop-zone${state}`} aria-label={label}>
      <h3>{label}</h3>
      {children ?? <p className="muted drop-hint">{hint}</p>}
    </section>
  );
}

function Placed({ name, onRemove, children }: { name: string; onRemove: () => void; children?: ReactNode }) {
  return (
    <span className="placed-chip">
      <span className="chip-name" title={name}>{name}</span>
      {children}
      <button type="button" className="chip-remove" aria-label={`Bỏ ${name}`} title={`Bỏ ${name}`} onClick={onRemove}>×</button>
    </span>
  );
}

function FilterEditor({ dataset, filter, onChange, onRemove }: { dataset: string; filter: FilterSpec; onChange: (patch: Partial<Pick<FilterSpec, "values" | "min" | "max">>) => void; onRemove: () => void }) {
  const values = useResource<ValuesPayload>(`/api/bi/${enc(dataset)}/values?field=${enc(filter.field)}`);
  const [search, setSearch] = useState("");
  const payload = values.data;
  const number = (text: string) => (text.trim() === "" ? null : Number(text));
  return (
    <div className="filter-card">
      <div className="filter-head"><b title={filter.field}>{filter.field}</b><button type="button" className="chip-remove" aria-label={`Bỏ bộ lọc ${filter.field}`} onClick={onRemove}>×</button></div>
      {values.error && <p className="error">{values.error}</p>}
      {!payload && !values.error && <p className="muted">Đang tải giá trị…</p>}
      {payload?.role === "measure" && (
        <div className="filter-range">
          <label>Từ<input type="number" inputMode="decimal" value={filter.min ?? ""} placeholder={payload.min === null ? "" : String(payload.min)} onChange={(event) => onChange({ min: number(event.target.value) })} /></label>
          <label>Đến<input type="number" inputMode="decimal" value={filter.max ?? ""} placeholder={payload.max === null ? "" : String(payload.max)} onChange={(event) => onChange({ max: number(event.target.value) })} /></label>
        </div>
      )}
      {payload?.role === "dimension" && (
        <>
          {payload.values.length > 8 && <input className="bi-search" type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Tìm giá trị" aria-label={`Tìm giá trị của ${filter.field}`} />}
          <p className="muted">{filter.values.length ? `Đã chọn ${filter.values.length} giá trị.` : "Chưa chọn giá trị nào, bộ lọc chưa có hiệu lực."}</p>
          <div className="filter-values">
            {payload.values.filter((item) => matchesText(item.value, search)).map((item) => (
              <label key={item.value} className="filter-value">
                <input type="checkbox" checked={filter.values.includes(item.value)} onChange={(event) => onChange({ values: event.target.checked ? [...filter.values, item.value] : filter.values.filter((value) => value !== item.value) })} />
                <span>{item.value}</span>
                <small>{item.count.toLocaleString("vi-VN")}</small>
              </label>
            ))}
          </div>
          {payload.more && <p className="muted">Chỉ hiện 200 giá trị phổ biến nhất.</p>}
        </>
      )}
    </div>
  );
}

function ChartSwitcher({ chart, onChange }: { chart: Chart; onChange: (chart: Chart) => void }) {
  return (
    <div className="chart-switcher" role="group" aria-label="Loại biểu đồ">
      {CHARTS.map((item) => (
        <button key={item.value} type="button" aria-pressed={chart === item.value} onClick={() => onChange(item.value)}>
          {item.value === "table" && <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M3 10h18M3 15h18M10 4v16" /></svg>}
          {item.label}
        </button>
      ))}
    </div>
  );
}

function ResultPanel({ query, result, chart, running, error, pin }: { query: QueryJson | null; result: BiResult | null; chart: Chart; running: boolean; error: string; pin: WidgetDraft | null }) {
  if (!query) {
    return <div className="empty-state"><h2>Kéo một cột vào Trục X hoặc Trục Y</h2><p>Một Dimension vào Trục X và một Measure vào Trục Y cho biểu đồ cột; hai Measure cho biểu đồ phân tán. Đổi phép gộp ngay trên cột ở Trục Y, đổi loại biểu đồ ở hàng nút phía trên.</p></div>;
  }
  return (
    <section className="card bi-result" aria-busy={running}>
      {error && <p className="notice notice-error" role="alert">{error}</p>}
      {result ? (
        <>
          <div className="section-heading"><h2>{result.title}</h2><div className="result-actions">{running && <span className="muted">Đang tính…</span>}{pin && <PinButton draft={pin} />}</div></div>
          <p className="muted">
            {result.rows_used === 0 ? "Không có dòng nào thỏa bộ lọc." : `Tính trên ${result.rows_used.toLocaleString("vi-VN")} dòng.`}
            {result.kind === "scatter" && typeof result.pairs === "number" ? ` Hệ số tương quan r = ${formatNumber(result.correlation)} trên ${result.pairs.toLocaleString("vi-VN")} cặp.` : ""}
            {result.sampled ? " Quá nhiều điểm nên chỉ vẽ một mẫu 5.000 điểm; hệ số tương quan vẫn tính trên mọi cặp." : ""}
            {result.dropped > 0 ? ` Chỉ vẽ ${result.categories.length} nhóm lớn nhất, bỏ ${result.dropped.toLocaleString("vi-VN")} nhóm còn lại.` : ""}
            {result.other_series ? " Các nhóm màu nhỏ được gộp thành “Khác”." : ""}
            {result.folded_x ? " Các lát nhỏ được gộp thành “Khác”." : ""}
          </p>
          {result.kind === "single" && chart !== "table" ? (
            <p className="bi-kpi"><b>{formatNumber(result.series[0]?.values[0])}</b><span>{result.value_label}</span></p>
          ) : (
            <BiChart result={result} chart={chart} />
          )}
          <details className="details-block">
            <summary>Câu lệnh đã chạy</summary>
            <pre className="bi-sql"><code>{result.sql}</code></pre>
            {result.params.length > 0 && <p className="muted">Tham số: {result.params.map(String).join(", ")}</p>}
          </details>
        </>
      ) : running ? <p className="status-line">Đang tính…</p> : null}
    </section>
  );
}

function SaveBar({ dataset, view, spec, chart, onSaved }: { dataset: string; view: SavedView | null; spec: Spec; chart: Chart; onSaved: (view: SavedView) => void }) {
  const [name, setName] = useState(view?.name ?? "");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function save(asNew: boolean) {
    if (busy) return;
    setBusy(true);
    setMessage("");
    try {
      const body = { id: asNew ? undefined : view?.id, name, state: { ...spec, chart } };
      const saved = await sendJson<SavedView>(`/api/bi/${enc(dataset)}/views`, "POST", body);
      setMessage(`Đã lưu “${saved.name}”.`);
      onSaved(saved);
    } catch (reason) {
      setMessage(describeError(reason, "Không lưu được bản phân tích."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="save-bar" onSubmit={(event) => { event.preventDefault(); void save(false); }}>
      <label htmlFor="bi-view-name" className="sr-only">Tên bản phân tích</label>
      <input id="bi-view-name" className="bi-search" value={name} onChange={(event) => setName(event.target.value)} placeholder="Đặt tên, ví dụ: Tỷ lệ nợ theo nhóm phá sản" maxLength={120} />
      <button className="button-primary" type="submit" disabled={busy || !name.trim()}>{busy ? "Đang lưu…" : view ? "Lưu thay đổi" : "Lưu phân tích"}</button>
      {view && <button className="button-secondary" type="button" onClick={() => void save(true)} disabled={busy || !name.trim()}>Lưu thành bản mới</button>}
      {message && <span className="muted" role="status">{message}</span>}
    </form>
  );
}

function Workspace({ dataset, viewId, onSaved }: { dataset: string; viewId: string | null; onSaved: (view: SavedView) => void }) {
  const schema = useResource<SchemaPayload>(`/api/bi/${enc(dataset)}/schema`);
  const views = useResource<ViewsPayload>(`/api/bi/${enc(dataset)}/views`);
  const [spec, setSpec] = useState<Spec>(EMPTY_SPEC);
  const [chart, setChart] = useState<Chart>("auto");
  const [restored, setRestored] = useState(false);
  const [active, setActive] = useState<BiField | null>(null);
  const [notice, setNotice] = useState("");
  const [search, setSearch] = useState("");
  // Ket qua kem dung cau hinh da tao ra no: tieu de dung tu cau hinh do, nen
  // khong lech voi bieu do dang hien trong luc nguoi dung keo tha tiep.
  const [answer, setAnswer] = useState<{ result: BiResult; source: QueryJson } | null>(null);
  const [error, setError] = useState("");
  const [running, setRunning] = useState(false);
  const version = useRef(0);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 150, tolerance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: jumpBetweenZones }),
  );
  const view = viewId ? views.data?.views.find((item) => item.id === viewId) ?? null : null;
  const query = useMemo(() => toQuery(spec, chart), [spec, chart]);
  const queryKey = JSON.stringify(query);

  // Mo mot ban da luu: dung lai cau hinh tren bang hien tai, mot lan.
  useEffect(() => {
    if (restored || !schema.data || (viewId && !views.data)) return;
    if (view) {
      const again = sanitizeState(view.state, schema.data.fields);
      setSpec(again.spec);
      setChart(again.chart);
      if (again.dropped.length) setNotice(`Bảng không còn cột: ${again.dropped.join(", ")}. Các cột đó đã được bỏ khỏi bản này.`);
    } else if (viewId && views.data) {
      setNotice("Không tìm thấy bản phân tích này; có thể nó đã bị xoá.");
    }
    setRestored(true);
  }, [restored, schema.data, views.data, view, viewId]);

  // Moi lan tha la mot lan hoi may chu, doi 200 ms cho nguoi dung tha xong.
  // Chi ket qua cua lan hoi moi nhat duoc hien.
  useEffect(() => {
    const mine = version.current + 1;
    version.current = mine;
    if (!query) {
      setAnswer(null);
      setError("");
      setRunning(false);
      return;
    }
    const asked = query;
    const timer = window.setTimeout(() => {
      setRunning(true);
      sendJson<BiResult>(`/api/bi/${enc(dataset)}/query`, "POST", asked)
        .then((value) => { if (version.current === mine) { setAnswer({ result: value, source: asked }); setError(""); } })
        .catch((reason: unknown) => { if (version.current === mine) setError(describeError(reason, "Không chạy được cấu hình này.")); })
        .finally(() => { if (version.current === mine) setRunning(false); });
    }, 200);
    return () => window.clearTimeout(timer);
  }, [queryKey, dataset]); // eslint-disable-line react-hooks/exhaustive-deps

  if (schema.error && !schema.data) return <LoadState error={schema.error} retry={schema.retry} />;
  if (!schema.data || (viewId && !views.data && !views.error)) return <p className="status-line">Đang đọc các cột…</p>;

  const fields = schema.data.fields;
  const yField = fields.find((field) => field.name === spec.y);
  const shownResult = answer ? present(answer.result, answer.source, chart) : null;
  const shown = (role: BiField["role"]) => fields.filter((field) => field.role === role && matchesText(field.name, search));
  const dimensions = shown("dimension");
  const measures = shown("measure");

  function onDragEnd(event: DragEndEvent) {
    const field = fieldOf(event.active);
    setActive(null);
    if (!field || !event.over) return;
    const zone = event.over.id as Zone;
    const why = refusal(zone, field);
    setNotice(why);
    if (!why) setSpec((current) => drop(current, zone, field));
  }

  return (
    <DndContext sensors={sensors} accessibility={{ announcements, screenReaderInstructions }} onDragStart={(event) => { setNotice(""); setActive(fieldOf(event.active)); }} onDragEnd={onDragEnd} onDragCancel={() => setActive(null)}>
      <div className="bi-layout">
        <aside className="bi-panel bi-fields" aria-label="Các cột của bảng">
          <p className="muted">{schema.data.rows.toLocaleString("vi-VN")} dòng · {fields.length} cột. Kéo cột sang các vùng bên phải.</p>
          <input className="bi-search" type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Tìm cột" aria-label="Tìm cột" />
          <h3>DIMENSIONS ({dimensions.length})</h3>
          <ul className="field-list">{dimensions.map((field) => <FieldChip key={field.name} field={field} />)}</ul>
          <h3>MEASURES ({measures.length})</h3>
          <ul className="field-list">{measures.map((field) => <FieldChip key={field.name} field={field} />)}</ul>
        </aside>
        <div className="bi-main">
          <SaveBar key={view?.id ?? "moi"} dataset={dataset} view={view} spec={spec} chart={chart} onSaved={(saved) => { views.retry(); onSaved(saved); }} />
          <ChartSwitcher chart={chart} onChange={setChart} />
          <div className="bi-zones">
            <DropZone zone="x" label={zoneLabel("x", chart)} hint="Thả một Dimension (chữ, ngày, cột 0/1), hoặc một Measure để vẽ phân tán.">
              {spec.x ? <div className="placed"><Placed name={spec.x} onRemove={() => setSpec((current) => remove(current, "x", spec.x ?? ""))} /></div> : null}
            </DropZone>
            <DropZone zone="y" label={zoneLabel("y", chart)} hint={spec.x ? "Chưa có cột: đang đếm số dòng mỗi nhóm." : "Thả một Measure (cột số)."}>
              {spec.y ? (
                <div className="placed">
                  <Placed name={spec.y} onRemove={() => setSpec((current) => remove(current, "y", spec.y ?? ""))}>
                    <select className="agg-select" aria-label="Phép gộp" value={spec.aggregation} onChange={(event) => setSpec((current) => setAggregation(current, event.target.value as Aggregation, yField))}>
                      {AGGREGATIONS.map((item) => <option key={item.value} value={item.value} disabled={item.numeric && yField?.role !== "measure"}>{item.label}</option>)}
                    </select>
                  </Placed>
                </div>
              ) : null}
            </DropZone>
            {usesLegend(chart) && (
              <DropZone zone="color" label={zoneLabel("color", chart)} hint="Thả một Dimension để tách mỗi nhóm một màu (cột chồng cần vùng này).">
                {spec.color ? <div className="placed"><Placed name={spec.color} onRemove={() => setSpec((current) => remove(current, "color", spec.color ?? ""))} /></div> : null}
              </DropZone>
            )}
            <DropZone zone="filters" label={zoneLabel("filters", chart)} hint="Thả cột bất kỳ để lọc dòng trước khi tính.">
              {spec.filters.length > 0 ? (
                <div className="filter-list">
                  {spec.filters.map((filter) => <FilterEditor key={filter.field} dataset={dataset} filter={filter} onChange={(patch) => setSpec((current) => setFilter(current, filter.field, patch))} onRemove={() => setSpec((current) => remove(current, "filters", filter.field))} />)}
                </div>
              ) : null}
            </DropZone>
          </div>
          {!usesLegend(chart) && spec.color && <p className="notice notice-info" role="status">{chartLabel(chart)} dùng một Measure nên không tách màu; cột “{spec.color}” ở Legend được giữ lại cho loại biểu đồ khác.</p>}
          {notice && <p className="notice notice-error" role="status">{notice}</p>}
          <ResultPanel
            query={query}
            result={shownResult}
            chart={chart}
            running={running}
            error={error}
            // Ghim giu cau hinh keo tha (khong giu so): Dashboard chay lai moi lan mo.
            pin={shownResult ? { kind: "bi", title: shownResult.title.slice(0, 200), bi: { dataset, state: { ...spec, chart } } } : null}
          />
        </div>
      </div>
      <DragGhost field={active} />
    </DndContext>
  );
}

function FileDrop({ onUploaded }: { onUploaded: (dataset: string) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function send(file: File) {
    const lower = file.name.toLowerCase();
    if (!ACCEPTED.some((ending) => lower.endsWith(ending))) {
      setError(`Chỉ nhận tệp ${ACCEPTED.join(", ")}.`);
      return;
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      setError(`Tệp nặng ${(file.size / 1048576).toFixed(1)} MB, vượt giới hạn ${MAX_UPLOAD_BYTES / 1048576} MB.`);
      return;
    }
    setBusy(true);
    setError("");
    const form = new FormData();
    form.append("tep", file);
    form.append("ten", "");
    form.append("client_request_id", newRequestId());
    // Ghi loi vao: bo nay duoc tai thang vao Tu phan tich, khong qua muc Du lieu.
    form.append("nguon", "tu_phan_tich");
    try {
      const result = await sendMultipart<UploadPayload>("/api/datasets", form, uploadTimeoutMs(file.size));
      onUploaded(result.dataset_id);
    } catch (reason) {
      setError(describeError(reason, "Không tải được tệp. Kiểm tra kết nối rồi thử lại."));
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  return (
    <section
      className={`file-drop${over ? " over" : ""}`}
      aria-label="Tải tệp dữ liệu mới"
      onDragOver={(event) => { event.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(event) => { event.preventDefault(); setOver(false); const file = event.dataTransfer.files?.[0]; if (file && !busy) void send(file); }}
    >
      <p><b>{busy ? "Đang tải lên…" : "Thả tệp CSV hoặc Excel vào đây"}</b></p>
      <button className="button-secondary" type="button" onClick={() => input.current?.click()} disabled={busy}>Chọn tệp</button>
      <input ref={input} type="file" accept={ACCEPTED.join(",")} hidden onChange={(event) => { const file = event.target.files?.[0]; if (file) void send(file); }} />
      <p className="muted">Tệp đi qua bước làm sạch hiện có. Bạn duyệt các thao tác làm sạch ngay bên dưới, rồi mới kéo thả được.</p>
      {error && <p className="error" role="alert">{error}</p>}
    </section>
  );
}

function UploadProgress({ dataset, status, error, onClose }: { dataset: string; status: DatasetStatusPayload | null; error: string; onClose: () => void }) {
  const settled = status && !status.running && !["running", "waiting", "ready"].includes(status.state.key);
  return (
    <section className="card progress-card" aria-live="polite">
      <h2>Đang xử lý {dataset}</h2>
      {error ? <p className="error">{error}</p> : <p>{status?.state.label ?? "Đang bắt đầu làm sạch…"}</p>}
      {status?.gates.map((gate) => (
        <div className="gate" key={gate.gate_id}>
          <h3>{gate.title}</h3>
          <p>{gate.question}</p>
          <GateForm dataset={dataset} gate={gate} onDone={() => undefined} />
        </div>
      ))}
      {settled && <button type="button" onClick={onClose}>Đóng</button>}
    </section>
  );
}

/** Mot nhom thu muc trong o chon: moi bo mot thu muc, cac ban da luu la tep con. */
function FolderGroup({ title, folders, dataset, viewId, expanded, onOpen, onForget }: { title: string; folders: Folder[]; dataset: string; viewId: string | null; expanded: boolean; onOpen: (dataset: string, viewId: string | null) => void; onForget: (dataset: string, id: string, name: string) => void }) {
  if (folders.length === 0) return null;
  return (
    <section className="picker-group" aria-label={title}>
      <h3>{title} ({folders.length})</h3>
      {folders.map((folder) => (
        <details className="tree-folder" key={folder.run_id} open={expanded || folder.run_id === dataset || undefined}>
          <summary><b>{folder.run_id}</b><span className="muted">{folder.views.length} bản</span></summary>
          <ul className="tree-children">
            <li><button type="button" className={`tree-link${folder.run_id === dataset && !viewId ? " here" : ""}`} onClick={() => onOpen(folder.run_id, null)}>[+] Tạo bản phân tích mới</button></li>
            {folder.views.map((view) => (
              <li key={view.id} className="tree-file">
                <button type="button" className={`tree-link${folder.run_id === dataset && view.id === viewId ? " here" : ""}`} onClick={() => onOpen(folder.run_id, view.id)} title={view.name}>{view.name}<small>{chartLabel(view.chart)}</small></button>
                <button type="button" className="chip-remove" aria-label={`Xoá ${view.name}`} title={`Xoá ${view.name}`} onClick={() => onForget(folder.run_id, view.id, view.name)}>×</button>
              </li>
            ))}
          </ul>
        </details>
      ))}
    </section>
  );
}

/**
 * O chon bo du lieu dang tha xuong: dong lai chi mot dong, mo ra la mot bang co
 * o tim va thanh cuon, nen 100 bo du lieu cung khong keo dai trang. Chia hai nhom
 * theo loi vao: tai thang vao Tu phan tich, va tu muc Du lieu.
 */
function DatasetPicker({ folders, dataset, viewId, onOpen, onDeleted }: { folders: Folder[]; dataset: string; viewId: string | null; onOpen: (dataset: string, viewId: string | null) => void; onDeleted: () => void }) {
  const [shown, setShown] = useState(false);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);

  // Bam ra ngoai hay nhan Esc thi dong; Esc tra tieu diem ve nut.
  useEffect(() => {
    if (!shown) return;
    const onPointer = (event: MouseEvent) => {
      if (root.current && !root.current.contains(event.target as Node)) setShown(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setShown(false);
        button.current?.focus();
      }
    };
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [shown]);

  const current = folders.find((folder) => folder.run_id === dataset);
  const currentView = current?.views.find((view) => view.id === viewId);
  const label = current ? `${current.run_id} › ${currentView ? currentView.name : "Bản phân tích mới"}` : "Chọn bộ dữ liệu…";
  const groups = groupDatasets(folders, query);
  const searching = query.trim() !== "";

  function choose(next: string, view: string | null) {
    setShown(false);
    onOpen(next, view);
  }

  async function forget(folder: string, id: string, name: string) {
    if (!window.confirm(`Xoá bản phân tích “${name}”?`)) return;
    setError("");
    try {
      await sendJson(`/api/bi/${enc(folder)}/views/${enc(id)}`, "DELETE", {});
      if (folder === dataset && id === viewId) onOpen(folder, null);
      onDeleted();
    } catch (reason) {
      setError(describeError(reason, "Không xoá được bản phân tích."));
    }
  }

  return (
    <div className="picker" ref={root}>
      <button ref={button} type="button" className="picker-button" aria-expanded={shown} aria-controls="bi-picker-panel" onClick={() => setShown((value) => !value)}>
        <span className="picker-label" title={label}>{label}</span>
        <span className="muted picker-count">{folders.length} bộ</span>
        <svg className="picker-chevron" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg>
      </button>
      {shown && (
        <div id="bi-picker-panel" className="picker-panel" role="dialog" aria-label="Chọn bộ dữ liệu hoặc bản phân tích đã lưu">
          <input className="bi-search" type="search" autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Tìm bộ dữ liệu hoặc bản đã lưu" aria-label="Tìm bộ dữ liệu hoặc bản đã lưu" />
          <div className="picker-scroll tree">
            <FolderGroup title="Tải thẳng vào Tự phân tích" folders={groups.direct} dataset={dataset} viewId={viewId} expanded={searching} onOpen={choose} onForget={(folder, id, name) => void forget(folder, id, name)} />
            <FolderGroup title="Từ mục Dữ liệu" folders={groups.library} dataset={dataset} viewId={viewId} expanded={searching} onOpen={choose} onForget={(folder, id, name) => void forget(folder, id, name)} />
            {groups.direct.length + groups.library.length === 0 && <p className="muted">Không có bộ dữ liệu hay bản đã lưu nào khớp “{query}”.</p>}
          </div>
          {error && <p className="error" role="alert">{error}</p>}
        </div>
      )}
    </div>
  );
}

/** Trang Tu phan tich: chon bang sach (hay tai tep moi), roi keo tha de ve. */
export default function BiBuilder() {
  const router = useRouter();
  const params = useSearchParams();
  const dataset = params.get("bo") ?? "";
  const viewId = params.get("ban");
  const data = useResource<DataPayload>("/api/data");
  const [uploading, setUploading] = useState<string | null>(null);
  const upload = useUploadStatus(uploading);
  const status = upload.status;
  // Moi bo DA CO BANG SACH deu keo tha duoc, ke ca bo dang cho duyet them hay
  // tung dung giua chung; loc theo trang thai "ready" thi giau mat nhung bo do.
  const all = data.data?.datasets ?? [];
  const ready = all.filter((item) => item.has_clean);
  const waiting = all.filter((item) => !item.has_clean);
  const retry = data.retry;

  // Moi lan bam trong cay la mot phien moi, ke ca bam lai "Tao ban moi" cua dung
  // bo dang mo: dia chi khong doi nen khoa cu se giu nguyen khung cu. Bo dem nay
  // buoc khung keo tha dung lai tu dau va doc lai schema cua dung bo vua chon.
  const [session, setSession] = useState(0);
  const go = (next: string, view: string | null) => {
    router.replace(`/tu-phan-tich?bo=${enc(next)}${view ? `&ban=${enc(view)}` : ""}`);
  };
  const open = (next: string, view: string | null) => {
    setSession((value) => value + 1);
    go(next, view);
  };

  // Lam sach xong (da duyet) thi mo thang bang vua tai.
  useEffect(() => {
    if (uploading && status?.state.key === "ready") {
      router.replace(`/tu-phan-tich?bo=${enc(uploading)}`);
      setUploading(null);
      retry();
    }
  }, [uploading, status, retry, router]);

  return (
    <>
      <div className="page-heading"><div><p className="eyebrow">TỰ PHÂN TÍCH</p><h1>Kéo thả để vẽ biểu đồ</h1><p className="muted">Chọn một bộ dữ liệu đã làm sạch (hoặc một bản đã lưu), hoặc tải tệp mới, rồi kéo cột vào các trục. Mọi con số tính thẳng từ dữ liệu, không qua AI.</p></div></div>
      <div className="bi-source">
        <section className="bi-panel">
          <h2>Bộ dữ liệu</h2>
          {data.error && !data.data && <LoadState error={data.error} retry={data.retry} />}
          {data.data && ready.length === 0 && <p className="muted">Chưa có bộ dữ liệu nào đã làm sạch. Tải một tệp ở bên cạnh.</p>}
          {ready.length > 0 && <DatasetPicker folders={ready} dataset={dataset} viewId={viewId} onOpen={open} onDeleted={retry} />}
          {waiting.length > 0 && <p className="muted">{waiting.length} bộ khác chưa có bảng sạch ({waiting.map((item) => `${item.run_id}: ${item.state.label}`).join("; ")}). Mở ở tab Dữ liệu để duyệt bước làm sạch.</p>}
        </section>
        <FileDrop onUploaded={(id) => setUploading(id)} />
      </div>
      {uploading && <UploadProgress dataset={uploading} status={status} error={upload.error} onClose={() => setUploading(null)} />}
      {dataset ? (
        <Workspace key={`${dataset}:${viewId ?? "moi"}:${session}`} dataset={dataset} viewId={viewId} onSaved={(saved) => { retry(); if (saved.id !== viewId) go(dataset, saved.id); }} />
      ) : (
        <div className="empty-state"><h2>Chưa chọn bộ dữ liệu</h2><p>Mở một thư mục ở trên và chọn “Bản phân tích mới” hoặc một bản đã lưu.</p></div>
      )}
    </>
  );
}
