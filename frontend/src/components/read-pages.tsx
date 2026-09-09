"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import {
  DatasetStatusPayload,
  DashboardPayload,
  DataPayload,
  describeError,
  getJson,
  HomePayload,
  newRequestId,
  sendMultipart,
  sendJson,
  SystemPayload,
  UploadPayload,
} from "@/lib/api";

export function LoadState({ error, retry }: { error: string; retry: () => void }) {
  return (
    <div className="card err" role="alert">
      <p>{error}</p>
      <button type="button" onClick={retry}>Thử lại</button>
    </div>
  );
}

export function ErrorNotice({ error, retry }: { error: string; retry: () => void }) {
  return <div className="notice notice-error" role="alert"><span>{error}</span><button type="button" onClick={retry}>Thử lại</button></div>;
}

export function useResource<T>(path: string) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const loadedPath = useRef<string | null>(null);
  const inFlight = useRef(false);
  const requestVersion = useRef(0);

  useEffect(() => {
    let alive = true;
    const version = requestVersion.current + 1;
    requestVersion.current = version;
    inFlight.current = true;
    if (loadedPath.current !== path) {
      loadedPath.current = path;
      setData(null);
    }
    setError("");
    getJson<T>(path)
      .then((value) => alive && setData(value))
      .catch((reason: unknown) => {
        if (!alive) return;
        setError(describeError(reason, "Máy chủ không trả lời. Kiểm tra kết nối rồi thử lại."));
      })
      .finally(() => {
        if (requestVersion.current === version) inFlight.current = false;
      });
    return () => {
      alive = false;
      if (requestVersion.current === version) inFlight.current = false;
    };
  }, [path, attempt]);

  const retry = useCallback(() => {
    if (!inFlight.current) setAttempt((value) => value + 1);
  }, []);
  return { data, error, retry };
}

export function usePolling(retry: () => void, enabled: boolean, key: string) {
  useEffect(() => {
    if (!enabled) return;
    const timer = window.setInterval(retry, 5000);
    return () => window.clearInterval(timer);
  }, [enabled, key, retry]);
}

type StatusLike = {
  running?: boolean;
  state?: { key?: string };
  gates?: Array<{ gate_id: string }>;
};

/** Poll a small status response and refresh the large page only on a change. */
export function useStatusPolling<T extends StatusLike>(
  path: string,
  enabled: boolean,
  onChange: () => void,
) {
  const [error, setError] = useState("");
  const onChangeRef = useRef(onChange);
  useEffect(() => { onChangeRef.current = onChange; }, [onChange]);

  useEffect(() => {
    if (!enabled) {
      setError("");
      return;
    }
    let alive = true;
    let timer: number | undefined;
    let previous = "";

    async function check() {
      try {
        const status = await getJson<T>(path);
        if (!alive) return;
        setError("");
        const signature = JSON.stringify({
          running: status.running,
          state: status.state?.key,
          gates: status.gates?.map((gate) => gate.gate_id) ?? [],
        });
        // Refresh once even when the first status response is already terminal.
        // Otherwise a page loaded during a completed job can keep stale data
        // forever because polling correctly stops after that first response.
        if (!previous || previous !== signature) onChangeRef.current();
        previous = signature;
        const active = Boolean(
          status.running || status.state?.key === "running" || status.state?.key === "waiting" || status.gates?.length,
        );
        if (alive && active) timer = window.setTimeout(check, 5000);
      } catch (reason) {
        if (!alive) return;
        setError(describeError(reason, "Không đọc được trạng thái mới nhất."));
        timer = window.setTimeout(check, 5000);
      }
    }

    void check();
    return () => {
      alive = false;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [enabled, path]);

  return error;
}

/** Warn before a form with unsaved content is abandoned, including Next links. */
export function useUnsavedChanges(dirty: boolean, message: string) {
  const router = useRouter();
  useEffect(() => {
    if (!dirty) return;
    let lastUrl = window.location.href;
    const beforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = message;
    };
    const onClick = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const target = event.target instanceof Element ? event.target.closest("a[href]") : null;
      if (!(target instanceof HTMLAnchorElement) || target.target === "_blank" || target.hasAttribute("download")) return;
      const url = new URL(target.href, window.location.href);
      if (url.origin !== window.location.origin || url.pathname.startsWith("/api/")) return;
      if (!window.confirm(message)) {
        event.preventDefault();
        event.stopPropagation();
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      router.push(`${url.pathname}${url.search}${url.hash}`);
    };
    const onPopState = () => {
      const destination = window.location.href;
      if (!window.confirm(message)) {
        history.pushState(history.state, "", lastUrl);
        return;
      }
      lastUrl = destination;
      window.removeEventListener("popstate", onPopState);
      const url = new URL(destination);
      router.push(`${url.pathname}${url.search}${url.hash}`);
    };
    const onBeforeNavigation = (event: Event) => {
      if (!window.confirm(message)) event.preventDefault();
    };
    window.addEventListener("beforeunload", beforeUnload);
    document.addEventListener("click", onClick, true);
    window.addEventListener("popstate", onPopState);
    window.addEventListener("asys:before-navigation", onBeforeNavigation);
    return () => {
      window.removeEventListener("beforeunload", beforeUnload);
      document.removeEventListener("click", onClick, true);
      window.removeEventListener("popstate", onPopState);
      window.removeEventListener("asys:before-navigation", onBeforeNavigation);
    };
  }, [dirty, message, router]);
}

export function useUploadStatus(datasetId: string | null) {
  const [status, setStatus] = useState<DatasetStatusPayload | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!datasetId) {
      setStatus(null);
      setError("");
      return;
    }
    const id = datasetId;
    let alive = true;
    let timer: number | undefined;

    async function check() {
      try {
        const next = await getJson<DatasetStatusPayload>(`/api/datasets/${encodeURIComponent(id)}/status`);
        if (!alive) return;
        setStatus(next);
        setError("");
        if (next.running || next.state.key === "running" || next.state.key === "waiting") {
          timer = window.setTimeout(check, 5000);
        }
      } catch (reason) {
        if (!alive) return;
        setError(describeError(reason, "Không đọc được tiến độ tải lên."));
        timer = window.setTimeout(check, 5000);
      }
    }

    void check();
    return () => {
      alive = false;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [datasetId]);

  return { status, error };
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
  const [uploadingDataset, setUploadingDataset] = useState<string | null>(null);
  const [fileInputKey, setFileInputKey] = useState(0);
  const uploadStatus = useUploadStatus(uploadingDataset);
  const uploadResult = uploadStatus.status;
  useEffect(() => {
    if (uploadResult && !uploadResult.running && uploadResult.state.key !== "running") {
      resource.retry();
    }
  }, [resource.retry, uploadResult]);
  if (resource.error && !resource.data) return <LoadState error={resource.error} retry={resource.retry} />;
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
      const result = await sendMultipart<UploadPayload>("/api/datasets", form);
      setFile(null);
      setName("");
      setUploadRequestId(null);
      setUploadingDataset(result.dataset_id);
      setFileInputKey((value) => value + 1);
      setUploadError("");
      resource.retry();
    } catch (reason) {
      setUploadError(describeError(reason, "Không tải được tệp. Kiểm tra kết nối rồi thử lại."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h1>Trang chủ</h1>
      <p className="status-line">{resource.data.count} bộ dữ liệu · {resource.data.waiting} bộ chờ duyệt.</p>
      {resource.error && <ErrorNotice error={`Danh sách chưa cập nhật: ${resource.error}`} retry={resource.retry} />}
      <form className="card form-card upload-card" onSubmit={upload}>
        <h2>Đưa dữ liệu vào</h2>
        <label htmlFor="dataset-file">Tệp dữ liệu</label>
        <input id="dataset-file" key={fileInputKey} type="file" onChange={(event) => { setFile(event.target.files?.[0] ?? null); setUploadRequestId(null); }} disabled={busy} />
        <label htmlFor="dataset-name">Tên bộ dữ liệu <span className="muted">(không bắt buộc)</span></label>
        <input id="dataset-name" value={name} onChange={(event) => { setName(event.target.value); setUploadRequestId(null); }} placeholder="Ví dụ: doanh_thu_2025" disabled={busy} />
        <button className="button-primary" type="submit" disabled={busy || !file}>{busy ? "Đang tải…" : "Tải lên"}</button>
        {uploadError && <p className="error" role="alert">{uploadError}</p>}
      </form>
      {uploadingDataset && (
        <section className="card progress-card" aria-live="polite">
          <h2>Đang xử lý {uploadingDataset}</h2>
          {uploadStatus.error ? <p className="error">{uploadStatus.error}</p> : <p>{uploadResult?.state.label ?? "Đang bắt đầu làm sạch…"}</p>}
          <Link className="text-link" href={`/bo/${encodeURIComponent(uploadingDataset)}`}>Mở bộ dữ liệu</Link>
          {uploadResult && !uploadResult.running && uploadResult.state.key !== "running" && <button type="button" onClick={() => setUploadingDataset(null)}>Đóng thông báo</button>}
        </section>
      )}
      {resource.data.runs.length === 0 ? (
        <div className="empty-state"><h2>Chưa có bộ dữ liệu nào</h2><p>Tải lên một tệp để bắt đầu làm sạch và đặt câu hỏi.</p></div>
      ) : (
        <ul className="cards">
          {resource.data.runs.map((run) => (
            <li className="card" key={run.run_id}>
              <Link className="card-title" href={`/bo/${encodeURIComponent(run.run_id)}`}>{run.run_id}</Link>
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
  const polling = resource.data?.datasets.some((dataset) => ["running", "waiting"].includes(dataset.state.key));
  usePolling(resource.retry, Boolean(polling), `data:${polling ? "active" : "done"}`);
  if (resource.error && !resource.data) return <LoadState error={resource.error} retry={resource.retry} />;
  if (!resource.data) return <Loading />;
  return (
    <>
      <h1>Dữ liệu</h1>
      {resource.error && <ErrorNotice error={`Danh sách chưa cập nhật: ${resource.error}`} retry={resource.retry} />}
      {resource.data.datasets.length === 0 && <div className="empty-state"><h2>Chưa có dữ liệu</h2><p>Các tệp đã tải lên sẽ xuất hiện ở đây.</p></div>}
      <ul className="cards">
        {resource.data.datasets.map((dataset) => (
          <li className="card" key={dataset.run_id}>
            <Link className="card-title" href={`/bo/${encodeURIComponent(dataset.run_id)}`}>{dataset.run_id}</Link>
            <span className={`state state-${dataset.state.key}`}>{dataset.state.label}</span>
            <span className="muted">{dataset.analyses} phân tích</span>
          </li>
        ))}
      </ul>
    </>
  );
}

export function DashboardContent() {
  const resource = useResource<DashboardPayload>("/api/dashboard");
  if (resource.error && !resource.data) return <LoadState error={resource.error} retry={resource.retry} />;
  if (!resource.data) return <Loading />;
  return (
    <>
      <h1>Dashboard</h1>
      {resource.error && <ErrorNotice error={`Dashboard chưa cập nhật: ${resource.error}`} retry={resource.retry} />}
      {resource.data.material.length === 0 ? (
        <div className="empty-state"><h2>Chưa có kết luận để ghép báo cáo</h2><p>Hãy hoàn tất ít nhất một lượt hỏi trước.</p></div>
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
  if (resource.error && !resource.data) return <LoadState error={resource.error} retry={resource.retry} />;
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
      setMessage(describeError(reason, "Không thực hiện được thao tác. Kiểm tra kết nối rồi thử lại."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h1>Hệ thống</h1>
      {resource.error && <ErrorNotice error={`Thông tin hệ thống chưa cập nhật: ${resource.error}`} retry={resource.retry} />}
      <div className="card">
        <p><b>Phiên bản:</b> {version.sha || "không xác định"}</p>
        <p>{version.subject || "Chưa có mô tả phiên bản."}</p>
        <p className="muted">Nhánh {version.branch || "?"}{version.dirty ? " · có thay đổi cục bộ" : ""}</p>
      </div>
      <div className="card">
        {resource.data.note && <p className="status-line">{resource.data.note}</p>}
        {update.problem ? <p className="error" role="alert">{update.problem}</p> : <p>{update.available ? `Có ${update.behind} bản cập nhật.` : "Đang ở phiên bản mới nhất."}</p>}
        <button className="button-secondary" type="button" disabled={busy} onClick={() => updateSystem("/api/system/check")}>Kiểm tra cập nhật</button>{" "}
        {update.available && <button className="button-danger" type="button" disabled={busy} onClick={() => { if (window.confirm("Cập nhật sẽ thay đổi code đang chạy. Bạn chắc chắn muốn tiếp tục?")) void updateSystem("/api/system/apply"); }}>Cập nhật</button>}
        {message && <p className="status-line">{message}</p>}
      </div>
    </>
  );
}
