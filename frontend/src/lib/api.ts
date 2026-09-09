export type ApiErrorBody = {
  error?: { code?: string; message?: string; hint?: string };
};

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { credentials: "same-origin" });
  let body: T | ApiErrorBody | undefined;
  try {
    body = (await response.json()) as T | ApiErrorBody;
  } catch {
    body = undefined;
  }
  if (!response.ok) {
    const error = body as ApiErrorBody | undefined;
    throw new ApiError(
      response.status,
      error?.error?.message ?? "Máy chủ không trả về dữ liệu hợp lệ.",
    );
  }
  return body as T;
}

export async function sendJson<T>(path: string, method: string, value: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(value),
  });
  let body: T | ApiErrorBody | undefined;
  try {
    body = (await response.json()) as T | ApiErrorBody;
  } catch {
    body = undefined;
  }
  if (!response.ok) {
    const error = body as ApiErrorBody | undefined;
    throw new ApiError(response.status, error?.error?.message ?? "Thao tác không thành công.");
  }
  return body as T;
}

export async function sendMultipart<T>(path: string, form: FormData): Promise<T> {
  const response = await fetch(path, { method: "POST", credentials: "same-origin", body: form });
  const body = (await response.json()) as T | ApiErrorBody;
  if (!response.ok) {
    const error = body as ApiErrorBody;
    throw new ApiError(response.status, error.error?.message ?? "Tải tệp không thành công.");
  }
  return body as T;
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

export type HomePayload = { runs: RunInfo[]; count: number; waiting: number };

export type DataPayload = {
  datasets: Array<RunInfo & { state: DatasetState; analyses: number }>;
};

export type DashboardPayload = {
  material: Array<{ dataset: string; answers: number }>;
};

export type SystemPayload = {
  ok: boolean;
  note: string;
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

export type TablePayload = { uri: string; rows: number; columns: string[] };

export type DatasetPayload = {
  dataset_id: string;
  context: string;
  state: DatasetState;
  staged: TablePayload | null;
  clean: TablePayload | null;
  examination: string[];
  gates: Gate[];
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
  state: DatasetState;
  table: TablePayload | null;
  examination: string[];
  gates: Gate[];
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
  answer: Record<string, unknown> | null;
  measured: Record<string, number>;
  tree: unknown;
};
