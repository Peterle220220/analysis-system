"use client";

import Link from "next/link";
import { useRef, FormEvent, useState, type ReactNode } from "react";
import {
  CleanPayload, GlossaryPayload,
  DatasetPayload,
  DatasetStatusPayload,
  describeError,
  downloadFile,
  Gate,
  LONG_REQUEST_TIMEOUT_MS,
  newRequestId,
  RoundPayload,
  RoundStatusPayload,
  sendJson,
  TablePayload,
} from "@/lib/api";
import { clashes, duplicateMeanings, fillFromDraft, matchesQuery, rowsFromLines, sameRows, type GlossaryRow } from "@/lib/glossary";
import {
  ErrorNotice,
  LoadState,
  useResource,
  useStatusPolling,
  useUnsavedChanges,
} from "@/components/read-pages";

const pathPart = (value: string) => encodeURIComponent(value);

function errorMessage(reason: unknown, fallback: string): string {
  return describeError(reason, fallback);
}

function TableSummary({ table }: { table: TablePayload | null }) {
  if (!table) return <p className="muted">Chưa có bảng.</p>;
  return <p className="table-summary"><b>{table.rows.toLocaleString("vi-VN")}</b> dòng · <b>{table.columns.length}</b> cột</p>;
}

function TablePreview({ table }: { table: TablePayload | null }) {
  if (!table || table.preview.length === 0) return null;
  return (
    <div className="table-wrap">
      <table>
        <caption className="sr-only">Bản xem trước dữ liệu</caption>
        <thead><tr>{table.columns.map((column) => <th scope="col" key={column}>{column}</th>)}</tr></thead>
        <tbody>{table.preview.map((row, index) => <tr key={index}>{table.columns.map((column) => <td key={column}>{String(row[column] ?? "")}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

function StatusBadge({ state }: { state: { key: string; label: string } }) {
  return <span className={`state state-${state.key}`}>{state.label}</span>;
}

export function DatasetContent({ dataset }: { dataset: string }) {
  const resource = useResource<DatasetPayload>(`/api/datasets/${pathPart(dataset)}`);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [question, setQuestion] = useState("");
  const [askRequestId, setAskRequestId] = useState<string | null>(null);
  const [createdRoundId, setCreatedRoundId] = useState("");
  const [contextDraft, setContextDraft] = useState<string | null>(null);
  const [selectedRounds, setSelectedRounds] = useState<string[]>([]);
  const data = resource.data;
  const polling = data?.state.key === "running" || data?.state.key === "waiting";
  const statusError = useStatusPolling<DatasetStatusPayload>(`/api/datasets/${pathPart(dataset)}/status`, Boolean(polling), resource.retry);
  const contextValue = contextDraft ?? data?.context ?? "";
  const canAsk = data?.actions.can_ask ?? false;
  useUnsavedChanges(contextDraft !== null && contextDraft !== data?.context, "Bạn có bối cảnh chưa lưu. Rời trang sẽ bỏ thay đổi này?");

  if (resource.error && !data) return <LoadState error={resource.error} retry={resource.retry} />;
  if (!data) return <p className="status-line">Đang tải bộ dữ liệu…</p>;

  async function saveContext(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setMessage("");
    try {
      await sendJson(`/api/datasets/${pathPart(dataset)}/context`, "PUT", { context: contextValue });
      setContextDraft(null); setMessage("Đã lưu bối cảnh."); resource.retry();
    } catch (error) {
      setMessage(errorMessage(error, "Không lưu được bối cảnh."));
    } finally { setBusy(false); }
  }

  async function ask(event: FormEvent) {
    event.preventDefault();
    if (!question.trim() || busy || !canAsk) return;
    setBusy(true); setMessage(""); setCreatedRoundId("");
    const requestId = askRequestId ?? newRequestId();
    setAskRequestId(requestId);
    try {
      const result = await sendJson<{ round_id: string }>(`/api/datasets/${pathPart(dataset)}/ask`, "POST", { question: question.trim(), client_request_id: requestId }, LONG_REQUEST_TIMEOUT_MS);
      setQuestion(""); setAskRequestId(null); setCreatedRoundId(result.round_id); setMessage("Đã gửi câu hỏi; hệ thống đang xử lý."); resource.retry();
    } catch (error) {
      setMessage(errorMessage(error, "Không gửi được câu hỏi."));
    } finally { setBusy(false); }
  }

  async function deleteRounds() {
    if (busy || selectedRounds.length === 0) return;
    const count = selectedRounds.length;
    if (!window.confirm(`Xoá ${count} lượt hỏi đã chọn? Dữ liệu của các lượt này sẽ bị xoá.`)) return;
    setBusy(true); setMessage("");
    try {
      await sendJson(`/api/datasets/${pathPart(dataset)}/rounds/delete`, "POST", { round_ids: selectedRounds });
      setSelectedRounds([]); setMessage(`Đã xoá ${count} lượt hỏi.`); resource.retry();
    } catch (error) {
      setMessage(errorMessage(error, "Không xoá được phân tích."));
    } finally { setBusy(false); }
  }

  return (
    <>
      <div className="page-heading"><div><p className="eyebrow">BỘ DỮ LIỆU</p><h1>{data.dataset_id}</h1></div><StatusBadge state={data.state} /></div>
      {polling && <p className="status-line" aria-live="polite">Đang tự cập nhật tiến độ…</p>}
      {resource.error && <ErrorNotice error={`Nội dung hiển thị chưa cập nhật: ${resource.error}`} retry={resource.retry} />}
      {statusError && <ErrorNotice error={`Không đọc được trạng thái mới nhất: ${statusError}`} retry={resource.retry} />}
      {data.error && <div className="card err" role="alert"><b>Không đọc được tệp</b><p>{data.error}</p></div>}
      {message && <p className="notice notice-info" role="status">{message}{createdRoundId && <> <Link className="text-link" href={`/bo/${pathPart(dataset)}/pt/${pathPart(createdRoundId)}`}>Mở lượt hỏi {createdRoundId}</Link></>}</p>}

      <div className="cards two-column">
        <section className="card"><div className="section-heading"><h2>Nguồn dữ liệu</h2><span className="muted">Đã tải lên</span></div><TableSummary table={data.staged} /><TablePreview table={data.staged} /></section>
        <section className="card"><div className="section-heading"><h2>Dữ liệu sạch</h2><span className="muted">Sau khi duyệt</span></div><TableSummary table={data.clean} /><TablePreview table={data.clean} /><Link className="text-link" href={`/bo/${pathPart(dataset)}/sach`}>Mở trang dữ liệu sạch →</Link></section>
      </div>

      {data.gates.length > 0 && <section className="card action-card" aria-labelledby="pending-title"><p className="eyebrow">CẦN BẠN QUYẾT ĐỊNH</p><h2 id="pending-title">Đang chờ duyệt</h2><p className="muted">Chọn các thao tác được phép rồi bấm duyệt. Hệ thống sẽ tiếp tục từ trạng thái hiện tại.</p>{data.gates.map((gate) => <div className="gate" key={gate.gate_id}><h3>{gate.title}</h3><p>{gate.question}</p>{gate.examined.length > 0 && <p className="muted">Đã kiểm tra: {gate.examined.join("; ")}</p>}<GateForm dataset={dataset} gate={gate} onDone={resource.retry} /></div>)}</section>}

      <form className="card form-card" onSubmit={saveContext}><div className="section-heading"><div><h2>Bối cảnh và chú giải</h2><p className="muted">Thông tin bạn biết về dữ liệu sẽ được giữ nguyên khi đặt câu hỏi.</p></div><span className={contextDraft !== null && contextDraft !== data.context ? "dirty-label" : "muted"}>{contextDraft !== null && contextDraft !== data.context ? "Chưa lưu" : "Đã lưu"}</span></div><label htmlFor="dataset-context">Bối cảnh</label><textarea id="dataset-context" value={contextValue} onChange={(event) => setContextDraft(event.target.value)} rows={6} placeholder="Ví dụ: Khảo sát 40 nhà đầu tư cá nhân năm 2023, thu thập qua biểu mẫu trực tuyến." /><p className="muted">Chú giải cột nay lưu riêng trong bảng Chú giải cột ở trang dữ liệu sạch, không bị giới hạn độ dài như ô này. Những dòng tên cột = cách gọi đã viết ở đây vẫn được dùng, và sẽ được chuyển sang bảng khi bạn lưu bảng lần đầu.</p>{Array.isArray(data.glossary_unmatched) && data.glossary_unmatched.length > 0 && <div className="card warning-card" role="status"><b>Các dòng sau không trỏ tới cột nào nên chưa được dùng làm chú giải:</b><ul>{data.glossary_unmatched.map((line) => <li key={line}><code>{line}</code></li>)}</ul><p className="muted">Tên cột phải viết đúng như trong bảng (không phân biệt khoảng trắng thừa).</p></div>}<div className="form-actions"><button className="button-primary" type="submit" disabled={busy || contextDraft === null || contextDraft === data.context}>{busy ? "Đang lưu…" : "Lưu bối cảnh"}</button><Link className="text-link" href={`/bo/${pathPart(dataset)}/sach`}>Mở bảng chú giải cột</Link></div></form>

      <form className="card form-card" onSubmit={ask}><h2>Đặt câu hỏi</h2><label htmlFor="dataset-question">Bạn muốn biết điều gì từ dữ liệu sạch?</label><textarea id="dataset-question" value={question} onChange={(event) => { setQuestion(event.target.value); setAskRequestId(null); setCreatedRoundId(""); }} rows={3} placeholder="Ví dụ: Doanh thu thay đổi thế nào theo tháng?" /><div className="form-actions"><button className="button-primary" type="submit" disabled={busy || !question.trim() || !canAsk}>{busy ? "Đang gửi…" : "Gửi câu hỏi"}</button>{createdRoundId && <Link className="text-link" href={`/bo/${pathPart(dataset)}/pt/${pathPart(createdRoundId)}`}>Mở lượt hỏi mới →</Link>}</div>{!canAsk && <p className="muted">Chỉ có thể đặt câu hỏi khi bảng sạch đã sẵn sàng và không còn bước chờ duyệt.</p>}</form>

      <section className="card"><div className="section-heading"><h2>Phân tích</h2>{data.rounds.length > 0 && <span className="muted">Chọn để xoá</span>}</div>{data.rounds.length === 0 ? <p className="muted">Chưa có phân tích.</p> : <ul className="round-list">{data.rounds.map((round) => <li key={round.run.run_id}><input id={`round-${round.run.run_id}`} type="checkbox" checked={selectedRounds.includes(round.run.run_id)} onChange={(event) => setSelectedRounds((items) => event.target.checked ? [...items, round.run.run_id] : items.filter((item) => item !== round.run.run_id))} /><label htmlFor={`round-${round.run.run_id}`}><Link className="text-link" href={`/bo/${pathPart(dataset)}/pt/${pathPart(round.run.run_id)}`}>{round.question || round.run.run_id}</Link><StatusBadge state={round.detail} /></label></li>)}</ul>}{data.rounds.length > 0 && <button className="button-danger" type="button" onClick={deleteRounds} disabled={busy || selectedRounds.length === 0}>Xoá lượt đã chọn</button>}</section>
    </>
  );
}

function GateForm({ dataset, gate, onDone, runId }: { dataset: string; gate: Gate; onDone: () => void; runId?: string }) {
  const [chosen, setChosen] = useState<string[]>([]);
  const [addedRules, setAddedRules] = useState("");
  const [requestId, setRequestId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setError("");
    const clientRequestId = requestId ?? newRequestId();
    setRequestId(clientRequestId);
    try {
      const path = runId ? `/api/datasets/${pathPart(dataset)}/rounds/${pathPart(runId)}/approve` : `/api/datasets/${pathPart(dataset)}/approve`;
      await sendJson(path, "POST", { gate_id: gate.gate_id, chosen, added_rules: addedRules, client_request_id: clientRequestId }, LONG_REQUEST_TIMEOUT_MS);
      setRequestId(null); onDone();
    } catch (reason) {
      setError(errorMessage(reason, "Không duyệt được."));
    } finally { setBusy(false); }
  }

  // Tich tay tren mot bang 96 cot la 61 lan bam, va bo sot mot muc thi khong
  // ai biet - ke ca nguoi bam. Danh sach lay tu chinh gate, khong go tay.
  const everyId = gate.options.map((option) => option.option_id);
  const allChosen = everyId.length > 0 && everyId.every((id) => chosen.includes(id));
  return <form className="gate-form" onSubmit={submit}>{gate.options.length > 1 && <label className="choice choice-all" key="__all__"><input type="checkbox" checked={allChosen} onChange={(event) => { setRequestId(null); setChosen(event.target.checked ? everyId : []); }} /><span><b>{allChosen ? "Bỏ chọn tất cả" : `Chọn tất cả ${everyId.length} mục`}</b><small>Duyệt toàn bộ thay vì tích từng mục.</small></span></label>}{gate.options.map((option) => <label className="choice" key={option.option_id}><input type="checkbox" checked={chosen.includes(option.option_id)} onChange={(event) => { setRequestId(null); setChosen((items) => event.target.checked ? [...items, option.option_id] : items.filter((item) => item !== option.option_id)); }} /><span><b>{option.label}</b>{option.detail && <small>{option.detail}</small>}</span></label>)}{gate.agent_id === "a3_cleaner" && <><label htmlFor={`rules-${gate.gate_id}`}>Quy tắc bổ sung <span className="muted">(mỗi dòng: tên_luật:cột1,cột2)</span></label><textarea id={`rules-${gate.gate_id}`} value={addedRules} onChange={(event) => { setRequestId(null); setAddedRules(event.target.value); }} rows={3} placeholder="trim_whitespace:Customer name" /></>}<button className="button-primary" type="submit" disabled={busy}>{busy ? "Đang lưu…" : "Duyệt và chạy tiếp"}</button>{error && <p className="error" role="alert">{error}</p>}</form>;
}

/**
 * Bang chu giai cot: ten cot chi doc, nghia tieng Viet sua tai cho.
 *
 * Luu la THAY ca bang (PUT), khong noi them: noi them la cach hai lan soan sinh
 * ra "nghia cu; nghia moi" tren cung mot cot. Nut tao lai ban nhap nho va xam,
 * vi no la loi thoat, khong phai viec lam hang ngay.
 */
function GlossaryTable({ rows, busy, drafting, dirty, saved, canRegenerate, onChange, onSubmit, onRegenerate }: { rows: GlossaryRow[]; busy: boolean; drafting: boolean; dirty: boolean; saved: boolean; canRegenerate: boolean; onChange: (rows: GlossaryRow[]) => void; onSubmit: (event: FormEvent) => void; onRegenerate: () => void }) {
  const [query, setQuery] = useState("");
  const duplicates = duplicateMeanings(rows);
  const shown = rows.map((row, index) => ({ row, index })).filter(({ row }) => matchesQuery(row, query));
  const clashing = rows.filter((row) => clashes(row, duplicates)).length;
  const filled = rows.filter((row) => row.meaning.trim()).length;
  const label = dirty ? "Chưa lưu" : saved ? "Đã lưu" : "Chưa có chú giải";
  const hasCategories = rows.some((row) => (row.categories?.length ?? 0) > 0);

  function edit(index: number, meaning: string) {
    onChange(rows.map((item, at) => (at === index ? { ...item, meaning } : item)));
  }

  function editValues(index: number, values: string) {
    onChange(rows.map((item, at) => (at === index ? { ...item, values } : item)));
  }

  return (
    <form className="card form-card" onSubmit={onSubmit}>
      <div className="section-heading"><div><h2>Chú giải cột</h2><p className="muted">Sửa trực tiếp ở cột Nghĩa tiếng Việt. Để trống ô nào thì cột đó không có chú giải. Bấm Lưu là thay cả bảng đã lưu, không nối thêm, nên không sinh dòng trùng. Cột phân loại có thêm ô Nhãn giá trị để biểu đồ ghi bằng tiếng Việt: để trống thì dùng nhãn tự suy, muốn đổi thì ghi dạng 0 = Không; 1 = Có.</p></div><span className={dirty ? "dirty-label" : "muted"}>{label}</span></div>
      <label htmlFor="glossary-search">Tìm cột</label>
      <input id="glossary-search" type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Gõ tên cột tiếng Anh hoặc nghĩa tiếng Việt, có dấu hay không dấu đều được" />
      <p className="muted">Đang hiện {shown.length}/{rows.length} dòng, {filled} cột đã có nghĩa.{clashing > 0 ? ` Có ${clashing} dòng trùng cách gọi với dòng khác, được tô màu. Hãy sửa trước khi lưu.` : ""}</p>
      <div className="table-wrap">
        <table className="glossary-table">
          <thead><tr><th scope="col">Tên cột</th><th scope="col">Nghĩa tiếng Việt</th>{hasCategories && <th scope="col">Nhãn giá trị</th>}</tr></thead>
          <tbody>
            {shown.map(({ row, index }) => {
              const clash = clashes(row, duplicates);
              return (
                <tr key={row.column} className={clash ? "row-conflict" : undefined}>
                  <td className="col-name">{row.column}</td>
                  <td>
                    <input value={row.meaning} aria-label={`Nghĩa tiếng Việt cho ${row.column}`} onChange={(event) => edit(index, event.target.value)} />
                    {clash && <small className="conflict-tag">Trùng cách gọi với dòng khác</small>}
                  </td>
                  {hasCategories && (
                    <td>
                      {row.categories?.length ? (
                        <>
                          <input className="value-input" value={row.values ?? ""} placeholder={row.suggested || row.categories.map((value) => `${value} = ...`).join("; ")} aria-label={`Nhãn giá trị cho ${row.column}`} onChange={(event) => editValues(index, event.target.value)} />
                          <small className="value-hint">Giá trị trong dữ liệu: {row.categories.join(", ")}.{row.suggested && !(row.values ?? "").trim() ? " Đang dùng nhãn tự suy." : ""}</small>
                        </>
                      ) : null}
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {shown.length === 0 && <p className="muted">Không có dòng nào khớp từ khóa.</p>}
      <div className="form-actions">
        <button className="button-primary" type="submit" disabled={busy || !dirty}>{busy && !drafting ? "Đang lưu…" : "Lưu chú giải"}</button>
        <button className="button-quiet" type="button" onClick={onRegenerate} disabled={busy || !canRegenerate}>{drafting ? "Đang soạn… (có thể mất 1–2 phút)" : "Tạo lại bản nháp"}</button>
      </div>
    </form>
  );
}

export function CleanContent({ dataset }: { dataset: string }) {
  const resource = useResource<CleanPayload>(`/api/datasets/${pathPart(dataset)}/clean`);
  // Ban da luu doc tu backend moi lan mo trang. Truoc day trang khong doc lai
  // no: quay lai chi con nut soan nhap, va soan lai thi ban moi bi NOI vao ban
  // cu, hai dong cung mot cot gop thanh "nghia cu; nghia moi".
  const glossary = useResource<GlossaryPayload>(`/api/datasets/${pathPart(dataset)}/glossary`);
  const [edited, setEdited] = useState<GlossaryRow[] | null>(null);
  const [justSaved, setJustSaved] = useState<GlossaryRow[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [drafting, setDrafting] = useState(false);
  const [downloadBusy, setDownloadBusy] = useState(false);
  const [message, setMessage] = useState("");
  const data = resource.data;
  const polling = data?.state.key === "running" || data?.state.key === "waiting";
  const statusError = useStatusPolling<DatasetStatusPayload>(`/api/datasets/${pathPart(dataset)}/status`, Boolean(polling), resource.retry);
  const canDownloadClean = data?.actions.can_download_clean ?? false;
  const canGenerateGlossary = data?.actions.can_generate_glossary ?? false;
  const savedRows = justSaved ?? glossary.data?.rows ?? [];
  const saved = savedRows.some((row) => row.meaning.trim());
  const rows = edited ?? savedRows;
  const dirty = edited !== null && !sameRows(edited, savedRows);
  useUnsavedChanges(dirty, "Bạn có chú giải chưa lưu. Rời trang sẽ bỏ thay đổi này?");

  if (resource.error && !data) return <LoadState error={resource.error} retry={resource.retry} />;
  if (!data) return <p className="status-line">Đang tải dữ liệu sạch…</p>;

  async function makeDraft() {
    if (busy || !canGenerateGlossary || savedRows.length === 0) return;
    // Chi hoi lai khi co thu de mat: ban da luu, hoac thay doi chua luu.
    if ((saved || dirty) && !window.confirm("Tạo lại bản nháp sẽ thay toàn bộ nội dung đang hiện trong bảng bằng bản máy soạn mới. Bản đã lưu chỉ bị thay khi bạn bấm Lưu chú giải. Tiếp tục?")) return;
    setBusy(true); setDrafting(true); setMessage("");
    try {
      const result = await sendJson<{ lines: string[]; dropped: string[]; conflicts?: string[] }>(`/api/datasets/${pathPart(dataset)}/glossary-draft`, "POST", {}, LONG_REQUEST_TIMEOUT_MS);
      setEdited(fillFromDraft(savedRows, rowsFromLines(result.lines)));
      setMessage([result.conflicts?.length ? `Có ${result.conflicts.length} chỗ hai cột trùng cách gọi, sửa trước khi lưu: ${result.conflicts.join("; ")}.` : "", result.dropped.length ? `Đã bỏ ${result.dropped.length} dòng không khớp cột.` : "", "Bản nháp mới CHƯA được lưu. Sửa nếu cần rồi bấm Lưu chú giải."].filter(Boolean).join(" "));
    } catch (error) {
      setMessage(errorMessage(error, "Không soạn được chú giải."));
    } finally { setBusy(false); setDrafting(false); }
  }

  async function saveGlossary(event: FormEvent) {
    event.preventDefault();
    if (busy || !dirty || edited === null) return;
    setBusy(true); setMessage("");
    try {
      const result = await sendJson<GlossaryPayload>(`/api/datasets/${pathPart(dataset)}/glossary`, "PUT", { rows: edited });
      setJustSaved(result.rows); setEdited(null);
      const filled = result.rows.filter((row) => row.meaning.trim()).length;
      setMessage([`Đã lưu chú giải cho ${filled}/${result.rows.length} cột.`, result.moved ? `Đã chuyển ${result.moved} dòng chú giải cũ từ ô Bối cảnh sang bảng này.` : "", result.conflicts?.length ? `Còn ${result.conflicts.length} chỗ trùng cách gọi: ${result.conflicts.join("; ")}.` : ""].filter(Boolean).join(" "));
    } catch (error) {
      setMessage(errorMessage(error, "Không lưu được chú giải."));
    } finally { setBusy(false); }
  }

  let glossaryBlock: ReactNode;
  if (glossary.error && !glossary.data && !justSaved) glossaryBlock = <LoadState error={glossary.error} retry={glossary.retry} />;
  else if (!glossary.data && !justSaved) glossaryBlock = <p className="status-line">Đang tải chú giải đã lưu…</p>;
  // Chua co chu giai: hien nut, KHONG tu goi model. Mo trang chi de xem bang
  // hay tai CSV thi khong mat 1-2 phut va mot luot goi co phi.
  else if (!saved && edited === null) glossaryBlock = <section className="card"><h2>Chưa có chú giải cột</h2><p className="muted">Chú giải cho hệ thống biết nghĩa tiếng Việt của từng cột, để bạn hỏi bằng tiếng Việt mà hệ thống vẫn tìm đúng cột. Máy soạn nháp chỉ đọc TÊN cột, không đọc dòng dữ liệu nào, và mất khoảng 1–2 phút. Bản nháp chưa được lưu cho tới khi bạn bấm Lưu chú giải.</p><div className="form-actions"><button className="button-primary" type="button" onClick={makeDraft} disabled={busy || !canGenerateGlossary}>{drafting ? "Đang soạn… (có thể mất 1–2 phút)" : "Soạn nháp chú giải"}</button><button className="button-secondary" type="button" onClick={() => setEdited(savedRows)} disabled={busy}>Tự điền từ đầu</button></div></section>;
  else glossaryBlock = <GlossaryTable rows={rows} busy={busy} drafting={drafting} dirty={dirty} saved={saved} canRegenerate={canGenerateGlossary} onChange={setEdited} onSubmit={saveGlossary} onRegenerate={makeDraft} />;

  async function downloadCsv() {
    if (downloadBusy || !canDownloadClean) return;
    setDownloadBusy(true); setMessage("");
    try { await downloadFile(`/api/datasets/${pathPart(dataset)}/clean.csv`, `${data?.dataset_id ?? dataset}.csv`, "Không có bảng sạch để tải."); }
    catch (error) { setMessage(errorMessage(error, "Không tải được CSV.")); }
    finally { setDownloadBusy(false); }
  }

  // Ban sua cach doc ten cot khong quay lai sua nhung bang da nam tren dia.
  // Mot bang 96 cot lam sach tu truoc giu nguyen 95 cai ten co dau cach thua
  // o dau, roi cau hoi khong khop duoc cot - va khong co gi noi hai chuyen do
  // lai voi nhau. Da mat mot luot chan doan sai vi dung chuyen nay.
  const stale = typeof data.stale_columns === "number" ? data.stale_columns : 0;
  return <><div className="page-heading"><div><p className="eyebrow">DỮ LIỆU SẠCH</p><h1>{data.dataset_id}</h1></div><StatusBadge state={data.state} /></div>{stale > 0 && <div className="card warning-card" role="alert"><b>Bảng này được làm sạch bằng bản cũ.</b><p className="muted">Có {stale} tên cột mà bản hiện tại đã biết dọn, ví dụ dấu cách thừa ở đầu tên. Tên cột lệch một ký tự vô hình thì câu hỏi của bạn có thể không khớp được cột, mà không báo gì. <b>Tải lại đúng tệp đó một lần nữa</b> để hệ thống làm sạch lại bằng bản mới.</p></div>}{resource.error && <ErrorNotice error={`Nội dung hiển thị chưa cập nhật: ${resource.error}`} retry={resource.retry} />}{statusError && <ErrorNotice error={`Không đọc được trạng thái mới nhất: ${statusError}`} retry={resource.retry} />}<section className="card"><TableSummary table={data.table} /><TablePreview table={data.table} /><div className="form-actions"><button className="button-secondary" type="button" onClick={downloadCsv} disabled={downloadBusy || !data.actions.can_download_clean}>{downloadBusy ? "Đang chuẩn bị…" : "Tải CSV"}</button><Link className="text-link" href={`/bo/${pathPart(dataset)}`}>← Về bộ dữ liệu</Link></div>{!data.actions.can_download_clean && <p className="muted">Chưa thể tải hoặc soạn chú giải vì bảng sạch chưa sẵn sàng.</p>}</section>{message && <p className="notice notice-info" role="status">{message}</p>}{!data.table && <div className="empty-state"><h2>Chưa có bảng sạch</h2><p>Quay lại bộ dữ liệu để xem tiến độ hoặc duyệt bước làm sạch.</p></div>}{data.table && glossaryBlock}{data.examination.length > 0 && <details className="details-block"><summary>Hệ thống đã kiểm tra ({data.examination.length} ghi nhận)</summary><ul>{data.examination.map((line) => <li key={line}>{line}</li>)}</ul></details>}</>;
}

/**
 * Mot bieu do do backend ve, cong mot tooltip khi re chuot hoac tab toi.
 *
 * Bieu do van la HTML/SVG thuan (trang Python cu dung y nhu the, khong
 * JavaScript). O day chi them lop di chuot: moi cot, lat, diem mang
 * data-tip-label va data-tip-value; nhan dua vao bang JSX nen duoc escape,
 * khong bao gio thanh HTML. Tooltip chi LAM RO: con so van in tren cot.
 */
function ChartBlock({ html }: { html: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [tip, setTip] = useState<{ x: number; y: number; label: string; value: string } | null>(null);

  function show(target: EventTarget | null) {
    const box = ref.current;
    const mark = target instanceof Element ? target.closest<HTMLElement | SVGElement>("[data-tip-label]") : null;
    if (!box || !mark || !box.contains(mark)) { setTip(null); return; }
    const outer = box.getBoundingClientRect();
    const rect = mark.getBoundingClientRect();
    setTip({ x: rect.left - outer.left + rect.width / 2, y: rect.top - outer.top, label: mark.getAttribute("data-tip-label") ?? "", value: mark.getAttribute("data-tip-value") ?? "" });
  }

  return (
    <div className="chart-svg chart-host" ref={ref} onPointerOver={(event) => show(event.target)} onPointerLeave={() => setTip(null)} onFocus={(event) => show(event.target)} onBlur={() => setTip(null)}>
      <div dangerouslySetInnerHTML={{ __html: html }} />
      {tip && <div className="chart-tip" role="tooltip" style={{ left: tip.x, top: tip.y }}><b>{tip.value}</b><span>{tip.label}</span></div>}
    </div>
  );
}

function Evidence({ dataset, reference }: { dataset: string; reference: string }) {
  if (!reference) return null;
  return <p className="evidence"><span>Nguồn bằng chứng:</span> <code>{reference}</code>{reference.startsWith("mart://") && <Link className="text-link" href={`/bo/${pathPart(dataset)}/sach`}>Mở bảng sạch</Link>}</p>;
}

function MeasuredValues({ measured }: { measured: Record<string, number> }) {
  const entries = Object.entries(measured);
  if (!entries.length) return null;
  return <details className="details-block"><summary>Số đo đã dùng ({entries.length})</summary><div className="table-wrap"><table><caption className="sr-only">Các số đo dùng trong phân tích</caption><thead><tr><th scope="col">Chỉ số</th><th scope="col">Giá trị</th></tr></thead><tbody>{entries.map(([key, value]) => <tr key={key}><td><code>{key}</code></td><td>{value.toLocaleString("vi-VN", { maximumFractionDigits: 6 })}</td></tr>)}</tbody></table></div></details>;
}

export function RoundContent({ dataset, round }: { dataset: string; round: string }) {
  const resource = useResource<RoundPayload>(`/api/datasets/${pathPart(dataset)}/rounds/${pathPart(round)}`);
  const [downloadBusy, setDownloadBusy] = useState("");
  const [downloadError, setDownloadError] = useState("");
  const data = resource.data;
  const polling = Boolean(data?.running || data?.gates.length);
  const statusError = useStatusPolling<RoundStatusPayload>(`/api/datasets/${pathPart(dataset)}/rounds/${pathPart(round)}/status`, polling, resource.retry);
  const canExport = data?.actions.can_export ?? false;

  if (resource.error && !data) return <LoadState error={resource.error} retry={resource.retry} />;
  if (!data) return <p className="status-line">Đang tải kết quả…</p>;

  const answer = data.answer;
  const claims = Array.isArray(answer?.claims) ? answer.claims as Array<Record<string, unknown>> : [];
  const warnings = Array.isArray(answer?.warnings) ? answer.warnings as string[] : [];
  const unanswered = Array.isArray(answer?.unanswered) ? answer.unanswered as string[] : [];
  const blocked = Array.isArray(answer?.blocked) ? answer.blocked as string[] : [];
  const repaired = Array.isArray(answer?.repaired) ? answer.repaired as string[] : [];
  const needs = Array.isArray(answer?.needs) ? answer.needs as Array<Record<string, unknown>> : [];
  const summary = typeof answer?.summary === "string" ? answer.summary : "";
  // Ly do noi bang tieng nguoi, tinh o backend bang cung ham voi trang Python.
  // Truoc day o day lay thang blocked[0]: mot cau may, va co khi la ly do chan
  // MOT KET LUAN chu khong phai ly do vang cau tra loi thang - tuc la do loi nham.
  const rawReason = answer?.direct_reason;
  const directReason = typeof rawReason === "string" && rawReason
    ? rawReason
    : "Hệ thống không chốt được một câu trả lời trực tiếp cho câu hỏi này.";
  type Group = { title: string; explain: string; items: string[] };
  const hasGapGroups = Array.isArray(answer?.gap_groups);
  const gapGroups = Array.isArray(answer?.gap_groups) ? answer.gap_groups as Group[] : [];
  const blockedGroups = Array.isArray(answer?.blocked_groups) ? answer.blocked_groups as Group[] : [];
  const gapTotal = gapGroups.reduce((total, group) => total + group.items.length, 0);
  // SVG ve o backend bang cung ham voi trang Python; nhan da duoc html.escape
  // o do, nen chen thang vao duoc.
  const charts = Array.isArray(data.charts) ? data.charts : [];
  // Tap nao cac con so thuoc ve: do code doc tu cau SQL loc, khong tu loi model.
  const scopes = Array.isArray(data.scope) ? data.scope : [];

  async function download(kind: "excel" | "word") {
    if (downloadBusy || !canExport) return;
    setDownloadBusy(kind); setDownloadError("");
    const extension = kind === "excel" ? "xlsx" : "docx";
    try { await downloadFile(`/api/datasets/${pathPart(dataset)}/rounds/${pathPart(round)}/export/${kind}`, `${data?.round_id ?? round}.${extension}`, `Không tải được tệp ${kind}.`); }
    catch (error) { setDownloadError(errorMessage(error, `Không tải được tệp ${kind}.`)); }
    finally { setDownloadBusy(""); }
  }

  return <><div className="page-heading"><div><p className="eyebrow">KẾT QUẢ PHÂN TÍCH</p><h1>{data.question || data.round_id}</h1><p className="muted">{data.round_id}</p></div><StatusBadge state={data.state} /></div>{polling && <p className="status-line" aria-live="polite">Đang tự cập nhật kết quả…</p>}{resource.error && <ErrorNotice error={`Kết quả hiển thị chưa cập nhật: ${resource.error}`} retry={resource.retry} />}{statusError && <ErrorNotice error={`Không đọc được trạng thái mới nhất: ${statusError}`} retry={resource.retry} />}{data.stopped_reason && <div className="card err" role="alert"><b>Chưa hoàn tất lượt hỏi</b><p>{data.stopped_reason}</p></div>}{data.gates.length > 0 && <section className="card action-card"><p className="eyebrow">CẦN BẠN QUYẾT ĐỊNH</p><h2>Đang chờ duyệt</h2>{data.gates.map((gate) => <div className="gate" key={gate.gate_id}><h3>{gate.title}</h3><p>{gate.question}</p><GateForm dataset={dataset} runId={round} gate={gate} onDone={resource.retry} /></div>)}</section>}{answer ? <>{warnings.length > 0 && <section className="card warning-card" role="alert"><h2>Cảnh báo độ tin cậy</h2><ul>{warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></section>}<section className="card lead-card"><p className="eyebrow">TRẢ LỜI TRỰC TIẾP</p>{summary ? <p>{summary}</p> : <><p><b>Chưa có câu trả lời thẳng.</b></p><p className="muted">{directReason} Các kết luận bên dưới vẫn đầy đủ và vẫn dẫn nguồn được.</p></>}</section>{scopes.length > 0 && <section className="card scope-card" aria-label="Phạm vi dữ liệu"><p className="eyebrow">PHẠM VI DỮ LIỆU</p>{scopes.map((item, index) => <p key={index}>Các con số dưới đây tính trên <b>{item.rows.toLocaleString("vi-VN")}</b>{item.total ? ` / ${item.total.toLocaleString("vi-VN")}` : ""} dòng: các dòng thỏa điều kiện <code>{item.condition}</code>. Không phải toàn bộ dữ liệu.</p>)}</section>}{claims.length > 0 ? <section className="claims-section"><div className="section-heading"><h2>Kết luận có thể kiểm tra</h2><span className="muted">{claims.length} kết luận</span></div><div className="claims-grid">{claims.map((claim, index) => <article className="card claim-card" key={index}><p className="eyebrow">KẾT LUẬN {index + 1}</p><p className="claim-text">{String(claim.claim ?? "")}</p><Evidence dataset={dataset} reference={String(claim.evidence_ref ?? "")} />{charts[index] ? <ChartBlock html={charts[index]} /> : Boolean(claim.chart_ref) && <img className="chart" loading="lazy" src={`/api/charts/${pathPart(String(claim.chart_ref).split("/").pop() || "")}`} alt={`Biểu đồ cho kết luận ${index + 1}`} />}<FollowUpForm dataset={dataset} round={round} claim={String(claim.claim ?? "")} enabled={data.actions.can_follow_up} /></article>)}</div></section> : <div className="card"><h2>Không rút ra được kết luận</h2><p>Hệ thống không có kết luận đủ điều kiện để hiển thị từ dữ liệu này.</p></div>}{blocked.length > 0 && <details className="details-block blocked-block"><summary>Hệ thống đã chặn {blocked.length} kết luận{blockedGroups.length > 0 ? `: ${blockedGroups.map((group) => `${group.items.length} ${group.title}`).join(", ")}` : ""}</summary><p className="muted">Những câu này KHÔNG nằm trong câu trả lời ở trên. Chúng hiện ra ở đây để bạn biết chúng đã từng tồn tại.</p>{blockedGroups.length > 0 ? blockedGroups.map((group) => <div key={group.title}><h3>{group.title} ({group.items.length})</h3>{group.explain && <p className="muted">{group.explain}</p>}<ul>{group.items.map((item) => <li key={item}>{item}</li>)}</ul></div>) : <ul>{blocked.map((item) => <li key={item}>{item}</li>)}</ul>}</details>}{repaired.length > 0 && <details className="details-block"><summary>Kết luận đã được sửa và giữ lại ({repaired.length})</summary><ul>{repaired.map((item) => <li key={item}>{item}</li>)}</ul></details>}{hasGapGroups ? gapTotal > 0 && <details className="details-block"><summary>Hệ thống đã không kết luận {gapTotal} điều, xem vì sao</summary>{gapGroups.map((group) => <div key={group.title}><h3>{group.title}</h3>{group.explain && <p className="muted">{group.explain}</p>}<ul>{group.items.map((item) => <li key={item}>{item}</li>)}</ul></div>)}</details> : unanswered.length > 0 && <details className="details-block"><summary>Chưa thể kết luận ({unanswered.length})</summary><ul>{unanswered.map((item) => <li key={item}>{item}</li>)}</ul></details>}{needs.length > 0 && <section className="card"><h2>Cần thêm dữ liệu</h2><ul>{needs.map((item, index) => <li key={index}>{String(item.ask ?? item.reason ?? "")}</li>)}</ul></section>}<MeasuredValues measured={data.measured} />{data.forecast.length > 0 && <section className="card forecast-card"><h2>Ước lượng kỳ tới <span className="muted">(không phải số đo)</span></h2><p className="muted">Ước lượng được tách riêng khỏi kết luận và chỉ dựa trên đường xu hướng của số đo đã có.</p><ul>{data.forecast.map((item) => <li key={item.name}><b>{item.name}</b>: kỳ sau {item.last_period} khoảng <b>{item.low.toFixed(2)} – {item.high.toFixed(2)}</b><br /><span className="muted">R² {item.r2.toFixed(2)}, {item.periods} kỳ. {item.caveat}</span></li>)}</ul></section>}</> : <div className="card"><h2>Chưa có câu trả lời</h2><p>Lượt hỏi đang chạy hoặc đã dừng trước khi tạo kết quả.</p></div>}<section className="card export-card"><h2>Tải kết quả</h2><p className="muted">Tệp xuất giữ lại cảnh báo, nguồn và phần chưa thể kết luận.</p><div className="form-actions"><button className="button-secondary" type="button" onClick={() => void download("excel")} disabled={Boolean(downloadBusy) || !data.actions.can_export}>{downloadBusy === "excel" ? "Đang chuẩn bị…" : "Tải Excel"}</button><button className="button-secondary" type="button" onClick={() => void download("word")} disabled={Boolean(downloadBusy) || !data.actions.can_export}>{downloadBusy === "word" ? "Đang chuẩn bị…" : "Tải Word"}</button></div>{!data.actions.can_export && <p className="muted">Chưa có câu trả lời để xuất tệp.</p>}{downloadError && <p className="error" role="alert">{downloadError}</p>}</section></>;
}

function FollowUpForm({ dataset, round, claim, enabled }: { dataset: string; round: string; claim: string; enabled: boolean }) {
  const [question, setQuestion] = useState("");
  const [requestId, setRequestId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [createdRoundId, setCreatedRoundId] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || !question.trim() || !enabled) return;
    setBusy(true); setMessage(""); setCreatedRoundId("");
    const clientRequestId = requestId ?? newRequestId();
    setRequestId(clientRequestId);
    try {
      const response = await sendJson<{ round_id: string }>(`/api/datasets/${pathPart(dataset)}/ask`, "POST", { question: question.trim(), from: round, claim, client_request_id: clientRequestId }, LONG_REQUEST_TIMEOUT_MS);
      setQuestion(""); setRequestId(null); setCreatedRoundId(response.round_id); setMessage("Đã tạo lượt hỏi tiếp.");
    } catch (error) {
      setMessage(errorMessage(error, "Không gửi được câu hỏi tiếp."));
    } finally { setBusy(false); }
  }

  return <form className="follow-up" onSubmit={submit}><label htmlFor={`follow-${round}-${claim}`}>Hỏi tiếp về kết luận này</label><textarea id={`follow-${round}-${claim}`} value={question} onChange={(event) => { setQuestion(event.target.value); setRequestId(null); setCreatedRoundId(""); }} rows={2} placeholder="Ví dụ: chia kết luận này theo từng nhóm" disabled={!enabled} /><button className="button-secondary" type="submit" disabled={busy || !question.trim() || !enabled}>{busy ? "Đang gửi…" : "Hỏi tiếp"}</button>{!enabled && <p className="muted">Chưa thể hỏi tiếp khi kết quả chưa sẵn sàng.</p>}{message && <p className="muted" role="status">{message}{createdRoundId && <> <Link className="text-link" href={`/bo/${pathPart(dataset)}/pt/${pathPart(createdRoundId)}`}>Mở lượt mới →</Link></>}</p>}</form>;
}
