export type ChainKey = string;

export interface Chain {
  key: ChainKey;
  name: string;
  family: "evm" | "utxo" | "solana";
  fee_unit: string;
  fetch_latency_s: number;
  rpc_url: string;
  native_symbol: string;
  decimals: number;
  block_time_s: number;
  whale_threshold: number;
  rate_limit_rps: number;
  workers: number;
  explorer_url: string;
  enabled: boolean;
  autosync: boolean;
  sort_order: number;
}

export interface Dataset {
  id: number;
  name: string;
  source_type: "api" | "upload" | "sync";
  chains: ChainKey[];
  params: Record<string, unknown>;
  status: "pending" | "loading" | "ready" | "failed";
  row_count: number;
  first_block: number | null;
  last_block: number | null;
  time_from: string | null;
  time_to: string | null;
  created_at: string;
}

export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelling" | "cancelled";

export interface Job {
  id: number;
  type: "fetch" | "load_upload" | "analytics";
  status: JobStatus;
  dataset_id: number | null;
  run_id: number | null;
  params: Record<string, unknown>;
  progress: number;
  message: string;
  detail: Record<string, unknown>;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface Run {
  id: number;
  dataset_id: number | null;
  chains: ChainKey[];
  time_from: string | null;
  time_to: string | null;
  settings: { kmeans_k?: number; anomaly_z?: number };
  status: "queued" | "running" | "succeeded" | "failed";
  transactions: number;
  wallets: number;
  created_at: string;
  finished_at: string | null;
}

export interface ChainSummary {
  chain: ChainKey;
  transactions: number;
  blocks: number;
  value: number;
  contract_share: number;
  median_gas: number;
  time_from: string;
  time_to: string;
  wallets: number;
  anomalies: number;
}

export interface Summary {
  run: Run;
  chains: ChainKey[];
  per_chain: ChainSummary[];
  totals: {
    transactions: number;
    blocks: number;
    wallets: number;
    anomalies: number;
    time_from: string | null;
    time_to: string | null;
  };
}

export interface SeriesPoint {
  t: string;
  txs: number;
  blocks: number;
  value: number;
  contract_share: number;
  median_gas: number;
}

export interface SeriesResponse {
  bucket_seconds: number;
  series: { chain: ChainKey; points: SeriesPoint[] }[];
}

export interface TagRow {
  chain: ChainKey;
  tag: string;
  wallets: number;
}

export interface ClusterRow {
  chain: ChainKey;
  cluster: number;
  wallets: number;
  avg_tx_out: number;
  avg_tx_in: number;
  avg_volume: number;
  avg_receivers: number;
  avg_senders: number;
  avg_contract: number;
  avg_gas: number;
  avg_anomaly: number;
}

export interface WalletRow {
  chain: ChainKey;
  wallet: string;
  volume: number;
  native_sent: number;
  native_received: number;
  net_flow: number;
  tx_out: number;
  tx_in: number;
  uniq_receivers: number;
  uniq_senders: number;
  tx_per_block: number;
  contract_call_ratio: number;
  avg_gas_gwei: number;
  anomaly_score: number;
  is_anomaly: number | boolean;
  cluster: number;
  tags: string[];
  first_seen: string;
  last_seen: string;
}

export interface WalletsResponse {
  run_id: number;
  total: number;
  page: number;
  limit: number;
  rows: WalletRow[];
}

export interface WalletTx {
  tx_hash: string;
  block_number: number;
  block_time: string;
  from_addr: string;
  to_addr: string;
  value_native: number;
  gas_price_gwei: number;
  is_contract_call: number;
}

export interface PairRow {
  chain: ChainKey;
  a: string;
  b: string;
  txs: number;
  a_to_b: number;
  b_to_a: number;
  value_a_to_b: number;
  value_b_to_a: number;
  contract_calls: number;
  blocks: number;
  first_seen: string;
  last_seen: string;
  a_info: { tags: string[]; anomaly_score: number };
  b_info: { tags: string[]; anomaly_score: number };
}

export interface PairsResponse {
  run_id: number;
  total: number;
  page: number;
  limit: number;
  rows: PairRow[];
  computed: boolean;
}

export interface Counterparty {
  wallet: string;
  txs: number;
  sent: number;
  received: number;
  value_sent: number;
  value_received: number;
  contract_calls: number;
  last_seen: string;
}

export interface WalletDetail {
  counterparties: Counterparty[];
  chain: ChainKey;
  address: string;
  run_id: number;
  profile: WalletRow | null;
  explorer_url: string | null;
  native_symbol: string;
  fee_unit: string;
  family: "evm" | "utxo" | "solana";
  transactions: WalletTx[];
}

export interface UploadInfo {
  id: string;
  filename: string;
  size_bytes: number;
  format: string;
  columns: string[];
  preview: Record<string, string>[];
  suggested: { mapping: Record<string, string>; value_unit: "native" | "wei"; gas_unit: "gwei" | "wei" };
  estimated_rows: number;
}

export interface Health {
  postgres: string;
  clickhouse: string;
  nownodes_key: boolean;
  history_days: number;
}

export interface FetchRequest {
  chain: ChainKey;
  mode: "last_blocks" | "last_hours" | "range";
  blocks?: number;
  hours?: number;
  from_block?: number;
  to_block?: number;
  name?: string;
  run_analytics: boolean;
}

export interface FromUploadRequest {
  upload_id: string;
  name?: string;
  chain?: ChainKey;
  mapping: Record<string, string>;
  value_unit: "native" | "wei";
  gas_unit: "gwei" | "wei";
  run_analytics: boolean;
}
