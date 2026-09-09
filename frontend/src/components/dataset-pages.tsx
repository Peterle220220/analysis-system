"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import {
  ApiError,
  CleanPayload,
  DatasetPayload,
  Gate,
  newRequestId,
  RoundPayload,
  sendJson,
} from "@/lib/api";
import { LoadState, usePolling, useResource } from "@/components/read-pages";

function TableSummary({ table }: { table: DatasetPayload["clean"] }) {
  if (!table) return <p className="muted">Chưa có bảng.</p>;
  return <p>{table.rows} dòng · {table.columns.length} cột</p>;
}

function TablePreview({ table }: { table: DatasetPayload["clean"] }) {
  if (!table || table.preview.length === 0) return null;
  return <div className="table-wrap"><table><thead><tr>{table.columns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>
    {table.preview.map((row, index) => <tr key={index}>{table.columns.map((column) => <td key={column}>{String(row[column] ?? "")}</td>)}</tr>)}
  </tbody></table></div>;
}

export function DatasetContent({ dataset }: { dataset: string }) {
  const resource = useResource<DatasetPayload>(`/api/datasets/${encodeURIComponent(dataset)}`);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [question, setQuestion] = useState("");
  const [askRequestId, setAskRequestId] = useState<string | null>(null);
  const [context, setContext] = useState<string | null>(null);
  const [selectedRounds, setSelectedRounds] = useState<string[]>([]);
  const polling = resource.data?.state.key === "running" || resource.data?.state.key === "waiting";
  usePolling(resource.retry, Boolean(polling), `${dataset}:${resource.data?.state.key ?? "loading"}`);

  if (resource.error) return <LoadState error={resource.error} retry={resource.retry} />;
  if (!resource.data) return <p className="status-line">Đang tải bộ dữ liệu…</p>;
  const data = resource.data;

  async function saveContext(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      await sendJson(`/api/datasets/${encodeURIComponent(dataset)}/context`, "PUT", { context });
      setMessage("Đã lưu bối cảnh.");
      resource.retry();
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "Không lưu được bối cảnh.");
    } finally {
      setBusy(false);
    }
  }

  async function ask(event: FormEvent) {
    event.preventDefault();
    if (!question.trim() || busy) return;
    setBusy(true);
    setMessage("");
    const requestId = askRequestId ?? newRequestId();
    setAskRequestId(requestId);
    try {
      await sendJson(`/api/datasets/${encodeURIComponent(dataset)}/ask`, "POST", {
        question,
        client_request_id: requestId,
      });
      setQuestion("");
      setAskRequestId(null);
      setMessage("Đã gửi câu hỏi; hệ thống đang xử lý.");
      resource.retry();
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "Không gửi được câu hỏi.");
    } finally {
      setBusy(false);
    }
  }

  async function deleteRounds() {
    if (busy || selectedRounds.length === 0) return;
    setBusy(true);
    setMessage("");
    try {
      await sendJson(`/api/datasets/${encodeURIComponent(dataset)}/rounds/delete`, "POST", { round_ids: selectedRounds });
      setSelectedRounds([]);
      setMessage("Đã xoá các phân tích đã chọn.");
      resource.retry();
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "Không xoá được phân tích.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h1>{data.dataset_id}</h1>
      <p className="status-line">{data.state.label}{polling ? " · đang tự cập nhật" : ""}</p>
      {data.error && <div className="card err">{data.error}</div>}
      {message && <p className="status-line">{message}</p>}
      <div className="cards">
        <section className="card">
          <h2>Nguồn dữ liệu</h2>
          <TableSummary table={data.staged} />
          <TablePreview table={data.staged} />
        </section>
        <section className="card">
          <h2>Dữ liệu sạch</h2>
          <TableSummary table={data.clean} />
          <TablePreview table={data.clean} />
          <Link href={`/bo/${encodeURIComponent(dataset)}/sach`}>Mở trang dữ liệu sạch</Link>
        </section>
      </div>
      {data.gates.length > 0 && (
        <section className="card">
          <h2>Đang chờ duyệt</h2>
          {data.gates.map((gate) => (
            <div key={gate.gate_id}>
              <h3>{gate.title}</h3>
              <p>{gate.question}</p>
              {gate.examined.length > 0 && <p className="muted">Đã xem: {gate.examined.join("; ")}</p>}
              <p className="muted">Duyệt gate này ở phiên bản API hiện tại bằng các lựa chọn bên dưới.</p>
              <GateForm dataset={dataset} gate={gate} onDone={resource.retry} />
            </div>
          ))}
        </section>
      )}
      <form className="card" onSubmit={saveContext}>
        <h2>Bối cảnh</h2>
        <textarea value={context ?? data.context} onChange={(event) => setContext(event.target.value)} rows={4} />
        <button type="submit" disabled={busy}>Lưu bối cảnh</button>
      </form>
      <form className="card" onSubmit={ask}>
        <h2>Đặt câu hỏi</h2>
        <textarea value={question} onChange={(event) => { setQuestion(event.target.value); setAskRequestId(null); }} rows={3} placeholder="Bạn muốn biết điều gì từ dữ liệu sạch?" />
        <button type="submit" disabled={busy || !question.trim()}>Gửi câu hỏi</button>
      </form>
      <section className="card">
        <h2>Phân tích</h2>
        {data.rounds.length === 0 ? <p className="muted">Chưa có phân tích.</p> : (
          <ul>
            {data.rounds.map((round) => (
              <li key={round.run.run_id}>
                <input
                  type="checkbox"
                  checked={selectedRounds.includes(round.run.run_id)}
                  onChange={(event) => setSelectedRounds((items) => event.target.checked
                    ? [...items, round.run.run_id]
                    : items.filter((item) => item !== round.run.run_id))}
                />{" "}
                <Link href={`/bo/${encodeURIComponent(dataset)}/pt/${encodeURIComponent(round.run.run_id)}`}>
                  {round.question || round.run.run_id}
                </Link>{" "}— {round.detail.label}
              </li>
            ))}
          </ul>
        )}
        {data.rounds.length > 0 && <button type="button" onClick={deleteRounds} disabled={busy || selectedRounds.length === 0}>Xoá phân tích đã chọn</button>}
      </section>
    </>
  );
}

function GateForm({ dataset, gate, onDone, runId }: { dataset: string; gate: Gate; onDone: () => void; runId?: string }) {
  const [chosen, setChosen] = useState<string[]>([]);
  const [addedRules, setAddedRules] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const path = runId
        ? `/api/datasets/${encodeURIComponent(dataset)}/rounds/${encodeURIComponent(runId)}/approve`
        : `/api/datasets/${encodeURIComponent(dataset)}/approve`;
      await sendJson(path, "POST", { gate_id: gate.gate_id, chosen, added_rules: addedRules });
      onDone();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Không duyệt được.");
    } finally {
      setBusy(false);
    }
  }

  return <form onSubmit={submit}>
    {gate.options.map((option) => <label key={option.option_id}>
      <input type="checkbox" checked={chosen.includes(option.option_id)} onChange={(event) => setChosen((items) => event.target.checked ? [...items, option.option_id] : items.filter((item) => item !== option.option_id))} />
      {option.label} {option.detail && <span className="muted">{option.detail}</span>}
    </label>)}
    {gate.agent_id === "a3_cleaner" && <textarea value={addedRules} onChange={(event) => setAddedRules(event.target.value)} rows={3} placeholder="Thêm quy tắc, mỗi dòng dạng ten_luat:cot1,cot2" />}
    <button type="submit" disabled={busy}>{busy ? "Đang lưu…" : "Duyệt và chạy tiếp"}</button>
    {error && <p className="error">{error}</p>}
  </form>;
}

export function CleanContent({ dataset }: { dataset: string }) {
  const resource = useResource<CleanPayload>(`/api/datasets/${encodeURIComponent(dataset)}/clean`);
  const [draft, setDraft] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  if (resource.error) return <LoadState error={resource.error} retry={resource.retry} />;
  if (!resource.data) return <p className="status-line">Đang tải dữ liệu sạch…</p>;
  const data = resource.data;

  async function makeDraft() {
    if (busy) return;
    setBusy(true);
    setMessage("");
    try {
      const result = await sendJson<{ lines: string[]; dropped: string[] }>(`/api/datasets/${encodeURIComponent(dataset)}/glossary-draft`, "POST", {});
      setDraft(result.lines);
      setMessage(result.dropped.length ? `Đã bỏ ${result.dropped.length} dòng không khớp cột.` : "Đã tạo bản nháp chú giải.");
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "Không soạn được chú giải.");
    } finally {
      setBusy(false);
    }
  }

  return <>
    <h1>Dữ liệu sạch</h1>
    <p className="status-line">{data.state.label}</p>
    <div className="card"><TableSummary table={data.table} /><TablePreview table={data.table} />
      <a href={`/api/datasets/${encodeURIComponent(dataset)}/clean.csv`}>Tải CSV</a>
      <p><button type="button" onClick={makeDraft} disabled={busy}>{busy ? "Đang soạn…" : "Soạn nháp chú giải cột"}</button></p>
      {message && <p className="muted">{message}</p>}
    </div>
    {draft.length > 0 && <div className="card"><h2>Bản nháp chú giải</h2><textarea value={draft.join("\n")} onChange={(event) => setDraft(event.target.value.split("\n"))} rows={Math.min(12, Math.max(3, draft.length + 1))} /><p className="muted">Kiểm tra và lưu phần đã sửa trong ô Bối cảnh ở trang bộ dữ liệu.</p></div>}
    {data.examination.length > 0 && <div className="card"><h2>Đã kiểm tra</h2><ul>{data.examination.map((line) => <li key={line}>{line}</li>)}</ul></div>}
  </>;
}

export function RoundContent({ dataset, round }: { dataset: string; round: string }) {
  const resource = useResource<RoundPayload>(`/api/datasets/${encodeURIComponent(dataset)}/rounds/${encodeURIComponent(round)}`);
  const polling = resource.data?.running || resource.data?.gates.length ? true : false;
  usePolling(resource.retry, polling, `${dataset}:${round}:${resource.data?.state.key ?? "loading"}`);
  if (resource.error) return <LoadState error={resource.error} retry={resource.retry} />;
  if (!resource.data) return <p className="status-line">Đang tải kết quả…</p>;
  const data = resource.data;
  const answer = data.answer;
  const claims = Array.isArray(answer?.claims) ? answer.claims as Array<Record<string, unknown>> : [];
  const warnings = Array.isArray(answer?.warnings) ? answer.warnings as string[] : [];
  const unanswered = Array.isArray(answer?.unanswered) ? answer.unanswered as string[] : [];
  return <>
    <h1>{data.question || data.round_id}</h1>
    <p className="status-line">{data.state.label}{polling ? " · đang tự cập nhật" : ""}</p>
    {data.stopped_reason && <div className="card err">{data.stopped_reason}</div>}
    {data.gates.length > 0 && <section className="card"><h2>Đang chờ duyệt</h2>{data.gates.map((gate) => <div key={gate.gate_id}>
      <h3>{gate.title}</h3><p>{gate.question}</p><GateForm dataset={dataset} runId={round} gate={gate} onDone={resource.retry} />
    </div>)}</section>}
    {answer ? <>
      {typeof answer.summary === "string" && answer.summary && <div className="card"><h2>Kết luận chung</h2><p>{answer.summary}</p></div>}
      {warnings.length > 0 && <div className="card err"><h2>Cảnh báo độ tin cậy</h2><ul>{warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div>}
      {claims.length > 0 && <section className="cards"><h2>Kết luận</h2>{claims.map((claim, index) => <article className="card" key={index}>
        <p>{String(claim.claim ?? "")}</p>
        {!!claim.evidence_ref && <p className="muted">Nguồn: {String(claim.evidence_ref)}</p>}
        {!!claim.chart_ref && <img src={`/api/charts/${encodeURIComponent(String(claim.chart_ref))}`} alt="Biểu đồ cho kết luận" />}
        <FollowUpForm dataset={dataset} round={round} claim={String(claim.claim ?? "")} />
      </article>)}</section>}
      {unanswered.length > 0 && <div className="card"><h2>Chưa thể kết luận</h2><ul>{unanswered.map((item) => <li key={item}>{item}</li>)}</ul></div>}
    </> : <div className="card">Chưa có câu trả lời.</div>}
    <p><a href={`/api/datasets/${encodeURIComponent(dataset)}/rounds/${encodeURIComponent(round)}/export/excel`}>Tải Excel</a> · <a href={`/api/datasets/${encodeURIComponent(dataset)}/rounds/${encodeURIComponent(round)}/export/word`}>Tải Word</a></p>
  </>;
}

function FollowUpForm({ dataset, round, claim }: { dataset: string; round: string; claim: string }) {
  const [question, setQuestion] = useState("");
  const [requestId, setRequestId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || !question.trim()) return;
    setBusy(true);
    setMessage("");
    const clientRequestId = requestId ?? newRequestId();
    setRequestId(clientRequestId);
    try {
      const response = await sendJson<{ round_id: string }>(`/api/datasets/${encodeURIComponent(dataset)}/ask`, "POST", {
        question,
        from: round,
        claim,
        client_request_id: clientRequestId,
      });
      setQuestion("");
      setRequestId(null);
      setMessage(`Đã tạo lượt hỏi tiếp: ${response.round_id}`);
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "Không gửi được câu hỏi tiếp.");
    } finally {
      setBusy(false);
    }
  }

  return <form onSubmit={submit}>
    <textarea value={question} onChange={(event) => { setQuestion(event.target.value); setRequestId(null); }} rows={2} placeholder="Hỏi tiếp về kết luận này" />
    <button type="submit" disabled={busy || !question.trim()}>{busy ? "Đang gửi…" : "Hỏi tiếp"}</button>
    {message && <p className="muted">{message}</p>}
  </form>;
}
