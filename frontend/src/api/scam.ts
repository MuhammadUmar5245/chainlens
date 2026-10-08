/** Scam tracing API (separate from the existing client so nothing there changes). */
import { ApiError, qs } from "./client";
import type { Job } from "./types";

const BASE = "/api/v1";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(BASE + path, { ...init, headers: init?.body && typeof init.body === "string" ? { "Content-Type": "application/json" } : undefined });
  } catch {
    throw new ApiError(0, "Cannot reach the API. Start the backend (docker compose up) and try again.");
  }
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const b = await res.json();
      msg = typeof b.detail === "string" ? b.detail : Array.isArray(b.detail) ? b.detail.map((d: { msg: string }) => d.msg).join("; ") : msg;
    } catch { /* not JSON */ }
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}

export type Severity = "high" | "medium" | "low";

export interface Finding {
  id: string;
  chain: string;
  detector: string;
  wallet: string;
  related_wallets: string[];
  tx_hashes: string[];
  score: number;
  severity: Severity;
  reason: string;
  details: Record<string, unknown>;
}

export interface ScamSummary {
  run_id: number;
  chains: string[];
  evm_chains: string[];
  note: string;
  detectors: { id: string; name: string; findings: number; wallets: number; by_severity: Record<Severity, number> }[];
  wallets_by_severity: Record<Severity, number>;
  job: null | { id: number; status: string; message: string; progress: number; finished_at: string | null;
    detail: { chains?: Record<string, { transactions: number; token_transfers: number; approvals: number;
      detectors: Record<string, { status: string; findings: number; seconds?: number; error?: string }> }> } };
  test_labels_loaded: number;
  labels_total: number;
}

export interface RiskRow {
  chain: string;
  wallet: string;
  risk_score: number;
  severity: Severity;
  detectors_hit: string[];
  top_reasons: string[];
  labels: { label: string; category: string; source: string }[];
}

export interface Label { id: number; chain: string; address: string; label: string; category: string; source: string; added_at: string }

export interface TraceNode {
  id: string;
  level: number;
  degree?: number;
  hub?: string;
  labels: { label: string; category: string; source: string }[];
  exit: boolean;
  risk: { score: number; severity: Severity } | null;
}
export interface TraceEdge { source: string; target: string; asset: string; amount: number; count: number; first: string; last: string }

export interface Trace {
  chain: string;
  address: string;
  depth: number;
  direction: string;
  run_id: number | null;
  note: string;
  truncated: boolean;
  limits: { max_nodes: number; hub_degree_limit: number };
  profile: {
    transactions: number; first_seen: string; last_seen: string; native_in: number; native_out: number; sent: number; received: number;
    active_hours: number; contract_calls: number; behaviour: string; tags: string[]; anomaly_score: number | null;
    risk: { score: number; severity: Severity } | null; labels: TraceNode["labels"];
    tokens: { symbol: string; received: number; sent: number; transfers: number }[];
  };
  counterparties: { other: string; direction: string; transactions: number; native_amount: number; first: string; last: string; labels: TraceNode["labels"] }[];
  first_funder: null | { time: string; block: number; tx_hash: string; funder: string; amount: number; asset: string; labels: TraceNode["labels"] };
  exit_points: { address: string; labels: TraceNode["labels"]; via: string; asset: string; amount: number }[];
  graph: { nodes: TraceNode[]; edges: TraceEdge[] };
  timeline: { time: string; block: number; tx_hash: string; direction: "in" | "out"; counterparty: string; amount: number; asset: string }[];
  findings: Omit<Finding, "id" | "chain">[];
}

type F = { run?: number; chains?: string[] };
const af = (f: F) => ({ run_id: f.run, chains: f.chains });

export const scamApi = {
  summary: (f: F) => req<ScamSummary>(`/scam/summary${qs(af(f))}`),
  findings: (f: F & { detector?: string; severity?: string; wallet?: string; page?: number; limit?: number }) =>
    req<{ total: number; page: number; limit: number; note: string; rows: Finding[] }>(
      `/scam/findings${qs({ ...af(f), detector: f.detector, severity: f.severity, wallet: f.wallet, page: f.page, limit: f.limit })}`),
  risk: (f: F & { severity?: string; q?: string; page?: number; limit?: number }) =>
    req<{ total: number; page: number; limit: number; rows: RiskRow[] }>(
      `/scam/risk${qs({ ...af(f), severity: f.severity, q: f.q, page: f.page, limit: f.limit })}`),
  detect: (run: number) => req<Job>(`/scam/runs/${run}/detect`, { method: "POST" }),
  enrich: (body: { chain: string; dataset_id?: number; from_block?: number; to_block?: number }) =>
    req<Job>("/scam/enrich", { method: "POST", body: JSON.stringify(body) }),
  exportUrl: (f: F) => `${BASE}/scam/export.xlsx${qs(af(f))}`,
  labels: (p: { category?: string; source?: string; q?: string; page?: number }) =>
    req<{ total: number; categories: string[]; sources: { source: string; count: number }[]; rows: Label[] }>(`/labels${qs(p)}`),
  importLabels: (file: File, source: string, chain: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("source", source);
    form.append("chain", chain);
    return req<{ imported: number; rejected: number; errors: string[] }>("/labels/import", { method: "POST", body: form });
  },
  loadTestLabels: () => req<{ imported: number }>("/labels/test-set", { method: "POST" }),
  removeSource: (source: string) => req<{ removed: number }>(`/labels${qs({ source })}`, { method: "DELETE" }),
  trace: (chain: string, address: string, p: { depth?: number; direction?: string; run?: number }) =>
    req<Trace>(`/trace/${chain}/${address}${qs({ depth: p.depth, direction: p.direction, run_id: p.run })}`),
  traceExportUrl: (chain: string, address: string, p: { depth?: number; direction?: string; run?: number }) =>
    `${BASE}/trace/${chain}/${address}/export.xlsx${qs({ depth: p.depth, direction: p.direction, run_id: p.run })}`,
};
