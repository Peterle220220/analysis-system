"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  ApiError,
  DashboardPayload,
  DataPayload,
  getJson,
  HomePayload,
  newRequestId,
  sendMultipart,
  sendJson,
  SystemPayload,
} from "@/lib/api";

export function LoadState({ error, retry }: { error: string; retry: () => void }) {
  return (
    <div className="card err">
      <p>{error}</p>
      <button type="button" onClick={retry}>Thử lại</button>
    </div>
  );
}

export function useResource<T>(path: string) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let alive = true;
    setData(null);
    setError("");
    getJson<T>(path)
      .then((value) => alive && setData(value))
      .catch((reason: unknown) => {
        if (!alive) return;
        setError(reason instanceof ApiError ? reason.message : "Máy chủ không trả lời.");
      });
    return () => {
      alive = false;
    };
  }, [path, attempt]);

  const retry = useCallback(() => setAttempt((value) => value + 1), []);
  return { data, error, retry };
}

function Loading() {
  return <p className="status-line">Đang tải dữ liệu…</p>;
}

export function HomeContent() {
  const resource = useResource<HomePayload>("/api/home");
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [uploadRequestId, setUploadRequestId] = useState<string | null>(null);
  if (resource.error) return <LoadState error={resource.error} retry={resource.retry} />;
  if (!resource.data) return <Loading />;

  async function upload(event: FormEvent) {
    event.preventDefault();
    if (!file || busy) return;
    setBusy(true);
    setUploadError("");
    const form = new FormData();
    form.append("tep", file);
    form.append("ten", name);
    const requestId = uploadRequestId ?? newRequestId();
    setUploadRequestId(requestId);
    form.append("client_request_id", requestId);
    try {
      await sendMultipart("/api/datasets", form);
      setFile(null);
      setName("");
      setUploadRequestId(null);
      resource.retry();
    } catch (reason) {
      setUploadError(reason instanceof ApiError ? reason.message : "Không tải được tệp.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h1>Trang chủ</h1>
      <p className="status-line">{resource.data.count} bộ dữ liệu · {resource.data.waiting} bộ chờ duyệt.</p>
      <form className="card" onSubmit={upload}>
        <h2>Đưa dữ liệu vào</h2>
        <input type="file" onChange={(event) => { setFile(event.target.files?.[0] ?? null); setUploadRequestId(null); }} disabled={busy} />
        <input value={name} onChange={(event) => { setName(event.target.value); setUploadRequestId(null); }} placeholder="Tên bộ dữ liệu (không bắt buộc)" disabled={busy} />
        <button type="submit" disabled={busy || !file}>{busy ? "Đang tải…" : "Tải lên"}</button>
        {uploadError && <p className="error">{uploadError}</p>}
      </form>
      {resource.data.runs.length === 0 ? (
        <div className="card">Chưa có bộ dữ liệu nào.</div>
      ) : (
        <ul className="cards">
          {resource.data.runs.map((run) => (
            <li className="card" key={run.run_id}>
              <Link href={`/bo/${run.run_id}`}>{run.run_id}</Link>
              <span className="muted">{run.phase} · {run.files} tệp</span>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

export function DataContent() {
  const resource = useResource<DataPayload>("/api/data");
  if (resource.error) return <LoadState error={resource.error} retry={resource.retry} />;
  if (!resource.data) return <Loading />;
  return (
    <>
      <h1>Dữ liệu</h1>
      <ul className="cards">
        {resource.data.datasets.map((dataset) => (
          <li className="card" key={dataset.run_id}>
            <Link href={`/bo/${dataset.run_id}`}>{dataset.run_id}</Link>
            <span>{dataset.state.label} · {dataset.analyses} phân tích</span>
          </li>
        ))}
      </ul>
    </>
  );
}

export function DashboardContent() {
  const resource = useResource<DashboardPayload>("/api/dashboard");
  if (resource.error) return <LoadState error={resource.error} retry={resource.retry} />;
  if (!resource.data) return <Loading />;
  return (
    <>
      <h1>Dashboard</h1>
      {resource.data.material.length === 0 ? (
        <p className="status-line">Chưa có kết luận nào để ghép báo cáo.</p>
      ) : (
        <ul className="cards">
          {resource.data.material.map((item) => (
            <li className="card" key={item.dataset}>
              <Link href={`/bo/${item.dataset}`}>{item.dataset}</Link>
              <span>{item.answers} câu trả lời</span>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

export function SystemContent() {
  const resource = useResource<SystemPayload>("/api/system");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  if (resource.error) return <LoadState error={resource.error} retry={resource.retry} />;
  if (!resource.data) return <Loading />;
  const { version, update } = resource.data;

  async function updateSystem(path: string) {
    if (busy) return;
    setBusy(true);
    setMessage("");
    try {
      await sendJson(path, "POST", {});
      setMessage(path.endsWith("/check") ? "Đã kiểm tra cập nhật." : "Đã áp dụng cập nhật; cần khởi động lại service.");
      resource.retry();
    } catch (reason) {
      setMessage(reason instanceof ApiError ? reason.message : "Không thực hiện được thao tác.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h1>Hệ thống</h1>
      <div className="card">
        <p><b>Phiên bản:</b> {version.sha || "không xác định"}</p>
        <p>{version.subject || "Chưa có mô tả phiên bản."}</p>
        <p className="muted">Nhánh {version.branch || "?"}{version.dirty ? " · có thay đổi cục bộ" : ""}</p>
      </div>
      <div className="card">
        {update.problem ? <p className="error">{update.problem}</p> : <p>{update.available ? `Có ${update.behind} bản cập nhật.` : "Đang ở phiên bản mới nhất."}</p>}
        <button type="button" disabled={busy} onClick={() => updateSystem("/api/system/check")}>Kiểm tra cập nhật</button>{" "}
        {update.available && <button type="button" disabled={busy} onClick={() => updateSystem("/api/system/apply")}>Cập nhật</button>}
        {message && <p className="status-line">{message}</p>}
      </div>
    </>
  );
}
