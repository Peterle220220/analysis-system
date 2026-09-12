export type ApiErrorBody = {
  error?: { code?: string; message?: string; hint?: string };
};

export class ApiError extends Error {
  status: number;
  code: string;
  hint: string;

  constructor(status: number, message: string, code = "", hint = "") {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.hint = hint;
  }
}

function apiError(status: number, body: unknown, fallback: string): ApiError {
  const detail = body as ApiErrorBody | undefined;
  return new ApiError(
    status,
    detail?.error?.message ?? fallback,
    detail?.error?.code ?? "",
    detail?.error?.hint ?? "",
  );
}

export function describeError(reason: unknown, fallback: string): string {
  if (!(reason instanceof ApiError)) return fallback;
  return reason.hint ? `${reason.message} ${reason.hint}` : reason.message;
}

export function newRequestId(): string {
  const uuid = globalThis.crypto?.randomUUID?.();
  return uuid ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

const REQUEST_TIMEOUT_MS = 15_000;

// Thao tac chay lau - dat cau hoi, duyet roi chay tiep phan tich, soan nhap chu
// giai bang model - duoc cho toi 15 phut. Truoc day moi request chi duoc 15
// giay, nen cau hoi dau tien (mat 1-2 phut) bao "qua thoi gian cho" trong khi
// may chu van dang chay va van ra ket qua.
export const LONG_REQUEST_TIMEOUT_MS = 15 * 60_000;

// Gioi han kich thuoc tep tai len. Phai KHOP voi MAX_UPLOAD_BYTES o backend va
// middlewareClientMaxBodySize trong next.config.ts.
export const MAX_UPLOAD_BYTES = 200 * 1024 * 1024;

/** Thoi gian cho tai mot tep: 30 giay, cong 5 giay moi MB (~1,6 Mbit/s tro len). */
export function uploadTimeoutMs(bytes: number): number {
  return 30_000 + Math.ceil(bytes / (1024 * 1024)) * 5_000;
}

export async function fetchWithTimeout(
  input: RequestInfo | URL,
  init?: RequestInit,
  timeoutMs = REQUEST_TIMEOUT_MS,
): Promise<Response> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(input, { ...init, signal: controller.signal });
  } catch (reason) {
    if (reason && typeof reason === "object" && "name" in reason && reason.name === "AbortError") {
      throw new ApiError(408, "Yêu cầu quá thời gian chờ.", "request_timeout", "Kiểm tra máy chủ rồi thử lại.");
    }
    throw new ApiError(0, "Không kết nối được với máy chủ.", "network_error", "Kiểm tra kết nối rồi thử lại.");
  } finally {
    window.clearTimeout(timer);
  }
}

export async function getJson<T>(path: string): Promise<T> {
  const response = await fetchWithTimeout(path, { credentials: "same-origin" });
  let body: T | ApiErrorBody | undefined;
  try {
    body = (await response.json()) as T | ApiErrorBody;
  } catch {
    body = undefined;
  }
  if (!response.ok) {
    const error = body as ApiErrorBody | undefined;
    throw apiError(response.status, error, "Máy chủ không trả về dữ liệu hợp lệ.");
  }
  return body as T;
}

export async function sendJson<T>(
  path: string,
  method: string,
  value: unknown,
  timeoutMs = REQUEST_TIMEOUT_MS,
): Promise<T> {
  const response = await fetchWithTimeout(path, {
    method,
    credentials: "same-origin",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(value),
  }, timeoutMs);
  let body: T | ApiErrorBody | undefined;
  try {
    body = (await response.json()) as T | ApiErrorBody;
  } catch {
    body = undefined;
  }
  if (!response.ok) {
    const error = body as ApiErrorBody | undefined;
    throw apiError(response.status, error, "Thao tác không thành công.");
  }
  return body as T;
}

export async function sendMultipart<T>(
  path: string,
  form: FormData,
  timeoutMs = REQUEST_TIMEOUT_MS,
): Promise<T> {
  const response = await fetchWithTimeout(path, { method: "POST", credentials: "same-origin", body: form }, timeoutMs);
  let body: T | ApiErrorBody | undefined;
  try {
    body = (await response.json()) as T | ApiErrorBody;
  } catch {
    body = undefined;
  }
  if (!response.ok) {
    throw apiError(response.status, body, "Tải tệp không thành công.");
  }
  return body as T;
}

function downloadName(header: string | null, fallback: string): string {
  if (!header) return fallback;
  const encoded = header.match(/filename\*\s*=\s*UTF-8''([^;]+)/i)?.[1];
  const quoted = header.match(/filename\s*=\s*"([^"]+)"/i)?.[1];
  const plain = header.match(/filename\s*=\s*([^;]+)/i)?.[1]?.trim();
  let candidate = quoted ?? plain;
  if (encoded) {
    try {
      candidate = decodeURIComponent(encoded);
    } catch {
      candidate = quoted ?? plain;
    }
  }
  return candidate?.split(/[\\/]/).pop()?.trim() || fallback;
}

export async function downloadFile(path: string, fallbackName: string, fallbackError: string): Promise<void> {
  const response = await fetchWithTimeout(path, { credentials: "same-origin" });
  if (!response.ok) {
    let body: ApiErrorBody | undefined;
    try {
      body = (await response.json()) as ApiErrorBody;
    } catch {
      body = undefined;
    }
    throw apiError(response.status, body, fallbackError);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = downloadName(response.headers.get("content-disposition"), fallbackName);
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export type RunInfo = {
  run_id: string;
  started: string;
  phase: string;
  tasks: number;
  files: number;
  bytes_used: number;
  age_days: number;
};

export type DatasetState = { key: string; label: string };

export type DatasetActions = {
  can_ask: boolean;
  can_download_clean: boolean;
  can_approve: boolean;
};

export type CleanActions = {
  can_download_clean: boolean;
  can_generate_glossary: boolean;
};

// Bang chu giai luu rieng: moi cot mot dong, theo thu tu cua bang.
export type GlossaryPayload = {
  dataset_id: string;
  rows: Array<{ column: string; meaning: string; values?: string; categories?: string[]; suggested?: string }>;
  saved: boolean;
  moved?: number;
  conflicts?: string[];
};

export type RoundActions = {
  can_export: boolean;
  can_follow_up: boolean;
  can_approve: boolean;
};

export type HomePayload = { runs: RunInfo[]; count: number; waiting: number };

export type UploadPayload = { dataset_id: string; status: string; running: boolean };

export type DatasetStatusPayload = {
  dataset_id: string;
  phase: string;
  running: boolean;
  state: DatasetState;
  gates: Gate[];
  error?: string | null;
};

export type DataPayload = {
  datasets: Array<RunInfo & { state: DatasetState; analyses: number }>;
};

export type DashboardPayload = {
  material: Array<{ dataset: string; answers: number }>;
};

export type SystemPayload = {
  ok: boolean;
  note: string;
  stale?: string;
  version: {
    sha: string;
    subject: string;
    when: string;
    branch: string;
    dirty: boolean;
  };
  update: { behind: number; available: boolean; problem: string; commits: string[] };
};

export type Gate = {
  gate_id: string;
  task_id: string;
  agent_id: string;
  title: string;
  question: string;
  options: Array<{ option_id: string; label: string; detail: string }>;
  examined: string[];
};

export type TablePayload = {
  uri: string;
  rows: number;
  columns: string[];
  preview: Array<Record<string, unknown>>;
};

export type DatasetPayload = {
  dataset_id: string;
  context: string;
  state: DatasetState;
  staged: TablePayload | null;
  clean: TablePayload | null;
  examination: string[];
  stale_columns?: number;
  gates: Gate[];
  glossary_unmatched?: string[];
  actions: DatasetActions;
  rounds: Array<{
    run: RunInfo;
    question: string;
    state: string;
    detail: { key: string; label: string };
  }>;
  tree: unknown;
  error?: string;
};

export type CleanPayload = {
  dataset_id: string;
  context: string;
  state: DatasetState;
  table: TablePayload | null;
  examination: string[];
  stale_columns?: number;
  gates: Gate[];
  actions: CleanActions;
  tree: unknown;
};

export type RoundPayload = {
  dataset_id: string;
  round_id: string;
  question: string;
  state: { key: string; label: string };
  running: boolean;
  stopped_reason: string;
  gates: Gate[];
  actions: RoundActions;
  answer: Record<string, unknown> | null;
  measured: Record<string, number>;
  charts?: string[];
  scope?: Array<{ rows: number; total: number | null; condition: string }>;
  forecast: Array<{
    name: string;
    last_period: string;
    low: number;
    high: number;
    r2: number;
    periods: number;
    caveat: string;
  }>;
  tree: unknown;
};

export type RoundStatusPayload = {
  dataset_id: string;
  round_id: string;
  state: DatasetState;
  running: boolean;
  gates: Gate[];
};
