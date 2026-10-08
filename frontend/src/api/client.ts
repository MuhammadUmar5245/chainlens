import type {
  Chain, ClusterRow, Dataset, FetchRequest, FromUploadRequest, Health, Job, PairsResponse, Run, SeriesResponse,
  Summary, TagRow, UploadInfo, WalletDetail, WalletsResponse,
} from "./types";

const BASE = "/api/v1";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

type Params = Record<string, string | number | boolean | null | undefined | string[]>;

export function qs(params: Params): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "" || v === false) continue;
    if (Array.isArray(v)) {
      if (v.length) sp.set(k, v.join(","));
    } else sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

async function errorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) return body.detail.map((d: { msg: string }) => d.msg).join("; ");
  } catch {
    /* not JSON */
  }
  return res.status >= 500 ? "The server could not complete the request. Check that the backend is running." : res.statusText;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(BASE + path, {
      ...init,
      headers: init?.body ? { "Content-Type": "application/json" } : undefined,
    });
  } catch {
    throw new ApiError(0, "Cannot reach the API. Start the backend (docker compose up) and try again.");
  }
  if (!res.ok) throw new ApiError(res.status, await errorMessage(res));
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export interface AnalyticsFilter {
  run?: number;
  chains?: string[];
}
const af = (f: AnalyticsFilter) => ({ run_id: f.run, chains: f.chains });

export interface WalletQuery extends AnalyticsFilter {
  tag?: string;
  q?: string;
  anomaliesOnly?: boolean;
  sort?: string;
  order?: "asc" | "desc";
  page?: number;
  limit?: number;
}
const wq = (f: WalletQuery) => ({
  ...af(f), tag: f.tag, q: f.q, anomalies_only: f.anomaliesOnly, sort: f.sort, order: f.order, page: f.page, limit: f.limit,
});

export const api = {
  health: () => request<Health>("/health"),
  chains: () => request<Chain[]>("/chains"),
  updateChain: (key: string, body: Partial<Chain>) =>
    request<Chain>(`/chains/${key}`, { method: "PATCH", body: JSON.stringify(body) }),

  datasets: () => request<Dataset[]>("/datasets"),
  fetchData: (body: FetchRequest) => post<Job>("/datasets/fetch", body),
  fromUpload: (body: FromUploadRequest) => post<Job>("/datasets/from-upload", body),
  deleteDataset: (id: number) => request<void>(`/datasets/${id}`, { method: "DELETE" }),

  jobs: () => request<Job[]>("/jobs?limit=100"),
  job: (id: number) => request<Job>(`/jobs/${id}`),
  cancelJob: (id: number) => post<Job>(`/jobs/${id}/cancel`),
  retryJob: (id: number) => post<Job>(`/jobs/${id}/retry`),

  runs: () => request<Run[]>("/analytics/runs"),
  startRun: (body: { chains: string[]; dataset_id?: number }) => post<Job>("/analytics/runs", body),
  summary: (f: AnalyticsFilter) => request<Summary>(`/analytics/summary${qs(af(f))}`),
  series: (f: AnalyticsFilter) => request<SeriesResponse>(`/analytics/series${qs(af(f))}`),
  tags: (f: AnalyticsFilter) => request<{ rows: TagRow[] }>(`/analytics/tags${qs(af(f))}`),
  clusters: (f: AnalyticsFilter) => request<{ rows: ClusterRow[] }>(`/analytics/clusters${qs(af(f))}`),
  pairs: (f: AnalyticsFilter & { minTxs?: number; twoWay?: boolean; transfersOnly?: boolean; q?: string; sort?: string; page?: number; limit?: number }) =>
    request<PairsResponse>(`/analytics/pairs${qs({
      ...af(f), min_txs: f.minTxs, two_way: f.twoWay, transfers_only: f.transfersOnly, q: f.q, sort: f.sort, page: f.page, limit: f.limit,
    })}`),
  distribution: (f: AnalyticsFilter) =>
    request<{ bin_width: number; bins: number; threshold: number; rows: { chain: string; bin: number; wallets: number }[] }>(
      `/analytics/distribution${qs(af(f))}`),

  wallets: (f: WalletQuery) => request<WalletsResponse>(`/wallets${qs(wq(f))}`),
  walletExportUrl: (f: WalletQuery) => `${BASE}/wallets/export${qs({ ...wq(f), page: undefined, limit: undefined })}`,
  wallet: (chain: string, address: string, run?: number) =>
    request<WalletDetail>(`/wallets/${chain}/${address}${qs({ run_id: run })}`),

  /** Upload with progress (fetch has no upload progress, so this uses XMLHttpRequest). */
  upload: (file: File, onProgress: (fraction: number) => void) =>
    new Promise<UploadInfo>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${BASE}/uploads`);
      xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
      xhr.onload = () => {
        let body: { detail?: string } & Partial<UploadInfo> = {};
        try {
          body = JSON.parse(xhr.responseText);
        } catch {
          /* ignore */
        }
        if (xhr.status >= 200 && xhr.status < 300) resolve(body as UploadInfo);
        else reject(new ApiError(xhr.status, typeof body.detail === "string" ? body.detail : `Upload failed (HTTP ${xhr.status}).`));
      };
      xhr.onerror = () => reject(new ApiError(0, "Upload failed: the API could not be reached."));
      const form = new FormData();
      form.append("file", file);
      xhr.send(form);
    }),
};
