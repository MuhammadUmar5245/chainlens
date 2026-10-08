import { useRef, useState, type DragEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { Chain, FetchRequest, Job, UploadInfo } from "../api/types";
import { ChainName, ErrorNotice, Panel, Progress, Status } from "../components/ui";
import { unitWord, useChains } from "../lib/chains";
import { bytes, duration, int } from "../lib/format";

type Tab = "api" | "upload" | "db";

export default function DataSources() {
  const [sp, setSp] = useSearchParams();
  const tab = (sp.get("tab") as Tab) || "api";
  const [job, setJob] = useState<Job | null>(null);

  return (
    <>
      <div className="page-head">
        <div className="meta">
          <h1>Data sources</h1>
          <p className="sub">Load transactions into the database. Analytics run automatically when loading finishes.</p>
        </div>
      </div>
      <div className="tabs" role="tablist">
        {([["api", "Fetch from API"], ["upload", "Upload a data dump"], ["db", "Import from a database"]] as [Tab, string][]).map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => { setJob(null); setSp({ tab: k }); }}>{label}</button>
        ))}
      </div>
      {job && <JobCard jobId={job.id} />}
      {tab === "api" && <FetchForm onStarted={setJob} />}
      {tab === "upload" && <UploadFlow onStarted={setJob} />}
      {tab === "db" && (
        <Panel title="Import from a database">
          <p className="sub" style={{ maxWidth: "65ch" }}>
            Connect a PostgreSQL or MySQL database, write a read-only SELECT, and import the result as a dataset.
            This is planned for phase 5 of the roadmap. Until then, export the table to CSV or Parquet and use
            “Upload a data dump”.
          </p>
        </Panel>
      )}
    </>
  );
}

/** Live progress for the job just started (and the analytics job it triggers). */
function JobCard({ jobId }: { jobId: number }) {
  const q = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api.job(jobId),
    refetchInterval: (query) => (["queued", "running", "cancelling"].includes(query.state.data?.status ?? "queued") ? 1500 : false),
  });
  const j = q.data;
  if (!j) return null;
  return (
    <Panel title={<div className="row"><h2>Job #{j.id}</h2><Status value={j.status} /></div>} aside={<Link to="/jobs">All jobs →</Link>}>
      <Progress value={j.progress} status={j.status} />
      <p className="sub">{j.message || "Waiting for a worker…"}</p>
      {j.error && <ErrorNotice error={j.error} title="The job failed" />}
      {j.status === "succeeded" && (
        <p className="sub">
          Data is loaded and an analytics run has been queued. Follow it on <Link to="/jobs">Datasets &amp; jobs</Link>;
          results appear on the <Link to="/">Overview</Link> when it finishes.
        </p>
      )}
    </Panel>
  );
}

function FetchForm({ onStarted }: { onStarted: (j: Job) => void }) {
  const { data: chains } = useChains();
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });
  const qc = useQueryClient();
  const enabled = (chains ?? []).filter((c) => c.enabled);
  const [chainKey, setChainKey] = useState("");
  const [mode, setMode] = useState<FetchRequest["mode"]>("last_blocks");
  const [blocks, setBlocks] = useState(50);
  const [hours, setHours] = useState(1);
  const [fromBlock, setFromBlock] = useState("");
  const [toBlock, setToBlock] = useState("");
  const [analyse, setAnalyse] = useState(true);
  const chain: Chain | undefined = enabled.find((c) => c.key === chainKey) ?? enabled[0];
  const historyDays = health.data?.history_days ?? 30;

  const nBlocks = !chain ? 0
    : mode === "last_blocks" ? blocks
    : mode === "last_hours" ? Math.round((hours * 3600) / chain.block_time_s)
    : Math.max(0, Number(toBlock) - Number(fromBlock) + 1);
  // each request takes fetch_latency_s and runs `workers` at a time, capped by the rate limit
  const perBlock = chain ? Math.max(chain.fetch_latency_s / Math.max(chain.workers, 1), 1 / chain.rate_limit_rps) : 0;
  const seconds = nBlocks * perBlock;
  const unit = unitWord(chain?.family);
  const Unit = unit[0].toUpperCase() + unit.slice(1);

  const start = useMutation({
    mutationFn: () => api.fetchData({
      chain: chain!.key, mode, run_analytics: analyse,
      blocks: mode === "last_blocks" ? blocks : undefined,
      hours: mode === "last_hours" ? hours : undefined,
      from_block: mode === "range" ? Number(fromBlock) : undefined,
      to_block: mode === "range" ? Number(toBlock) : undefined,
    }),
    onSuccess: (job) => { onStarted(job); qc.invalidateQueries({ queryKey: ["jobs"] }); },
  });

  return (
    <Panel title="Fetch from NOWNodes">
      {health.data && !health.data.nownodes_key && (
        <div className="notice warn"><strong>No NOWNodes key on the server</strong>Add NOWNODES_API_KEY to the .env file and restart the stack.</div>
      )}
      <div className="form-grid">
        <label className="field">Chain
          <select value={chain?.key ?? ""} onChange={(e) => setChainKey(e.target.value)}>
            {enabled.map((c) => <option key={c.key} value={c.key}>{c.name}</option>)}
          </select>
        </label>
        <label className="field">What to fetch
          <select value={mode} onChange={(e) => setMode(e.target.value as FetchRequest["mode"])}>
            <option value="last_blocks">Latest N {unit}</option>
            <option value="last_hours">Last N hours</option>
            <option value="range">{Unit.slice(0, -1)} range</option>
          </select>
        </label>
        {mode === "last_blocks" && (
          <label className="field">{Unit}
            <input type="number" min={1} value={blocks} onChange={(e) => setBlocks(Math.max(1, Number(e.target.value)))} />
          </label>
        )}
        {mode === "last_hours" && (
          <label className="field">Hours (max {historyDays * 24})
            <input type="number" min={1} max={historyDays * 24} value={hours}
              onChange={(e) => setHours(Math.min(historyDays * 24, Math.max(1, Number(e.target.value))))} />
          </label>
        )}
        {mode === "range" && (
          <>
            <label className="field">From {unit.slice(0, -1)}<input type="number" min={0} value={fromBlock} onChange={(e) => setFromBlock(e.target.value)} /></label>
            <label className="field">To {unit.slice(0, -1)}<input type="number" min={0} value={toBlock} onChange={(e) => setToBlock(e.target.value)} /></label>
          </>
        )}
      </div>
      {chain && (
        <div className="notice">
          <span>
            <ChainName chainKey={chain.key} name={chain.name} />: about <strong>{int(nBlocks)} {unit}</strong>, which is {int(nBlocks)} API
            calls and roughly <strong>{duration(seconds)}</strong> ({chain.workers} in parallel, ~{chain.fetch_latency_s}s per {unit.slice(0, -1)} request,
            at most {chain.rate_limit_rps} requests per second).
          </span>
          {(seconds > 3600 || (mode === "last_hours" && hours >= 24)) && (
            <span>A new {unit.slice(0, -1)} arrives every ~{chain.block_time_s}s on {chain.name}, so long ranges take many API calls. Check your NOWNodes plan first{chain.family === "solana" ? "; for Solana history, a data dump is usually more practical" : ""}.</span>
          )}
        </div>
      )}
      <label className="check"><input type="checkbox" checked={analyse} onChange={(e) => setAnalyse(e.target.checked)} /> Run analytics when the fetch finishes</label>
      {start.error && <ErrorNotice error={start.error} title="Could not start the fetch" />}
      <div><button className="btn primary" disabled={!chain || nBlocks < 1 || start.isPending} onClick={() => start.mutate()}>
        {start.isPending ? "Starting…" : "Start fetch"}
      </button></div>
    </Panel>
  );
}

const FIELD_LABELS: [string, string, boolean][] = [
  ["tx_hash", "Transaction hash", true], ["timestamp", "Timestamp", true], ["from", "From address", true],
  ["to", "To address", true], ["value", "Value", true], ["block_number", "Block number", false],
  ["gas_price", "Gas price", false], ["gas_limit", "Gas limit", false], ["is_contract_call", "Is contract call", false],
  ["input", "Input data", false], ["nonce", "Nonce", false], ["chain", "Chain column", false],
];

function UploadFlow({ onStarted }: { onStarted: (j: Job) => void }) {
  const { data: chains } = useChains();
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [info, setInfo] = useState<UploadInfo | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [chainMode, setChainMode] = useState<"one" | "column">("one");
  const [chainKey, setChainKey] = useState("eth");
  const [valueUnit, setValueUnit] = useState<"native" | "wei">("native");
  const [gasUnit, setGasUnit] = useState<"gwei" | "wei">("gwei");
  const [analyse, setAnalyse] = useState(true);

  async function send(file: File) {
    setError(null); setInfo(null); setProgress(0);
    try {
      const up = await api.upload(file, setProgress);
      setInfo(up);
      setMapping(up.suggested.mapping);
      setValueUnit(up.suggested.value_unit);
      setGasUnit(up.suggested.gas_unit);
      setChainMode(up.suggested.mapping.chain ? "column" : "one");
    } catch (e) {
      setError(e);
    } finally {
      setProgress(null);
    }
  }

  const start = useMutation({
    mutationFn: () => api.fromUpload({
      upload_id: info!.id,
      chain: chainMode === "one" ? chainKey : undefined,
      mapping: Object.fromEntries(Object.entries(mapping).filter(([k, v]) => v && (chainMode === "column" || k !== "chain"))),
      value_unit: valueUnit, gas_unit: gasUnit, run_analytics: analyse,
    }),
    onSuccess: (job) => { onStarted(job); qc.invalidateQueries({ queryKey: ["jobs"] }); },
  });

  const onDrop = (e: DragEvent) => {
    e.preventDefault(); setOver(false);
    const f = e.dataTransfer.files?.[0];
    if (f) send(f);
  };
  const missing = FIELD_LABELS.filter(([k, , req]) => req && !mapping[k]).map(([, l]) => l);

  return (
    <>
      <Panel title="1 · Choose a file">
        <div className={`dropzone ${over ? "over" : ""}`} role="button" tabIndex={0}
          onClick={() => input.current?.click()} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)} onDrop={onDrop}>
          <strong>Drop a file here or click to choose</strong>
          <span className="sub">CSV, Parquet, JSON Lines or Excel, up to 5 GB. For millions of rows use CSV or Parquet: an Excel sheet stops at 1,048,576 rows.</span>
          <input ref={input} type="file" hidden accept=".csv,.parquet,.jsonl,.ndjson,.json,.xlsx"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) send(f); e.target.value = ""; }} />
        </div>
        {progress !== null && <div className="stack"><Progress value={progress} status="running" /><span className="sub">Uploading… {Math.round(progress * 100)}%</span></div>}
        {error != null && <ErrorNotice error={error} title="Upload failed" />}
      </Panel>

      {info && (
        <Panel title="2 · Map the columns" aside={`${info.filename} · ${bytes(info.size_bytes)} · about ${int(info.estimated_rows)} rows`}>
          <div className="form-grid">
            {FIELD_LABELS.filter(([k]) => k !== "chain" || chainMode === "column").map(([k, label, req]) => (
              <label className="field" key={k}>{label}{req ? " *" : ""}
                <select value={mapping[k] ?? ""} onChange={(e) => setMapping({ ...mapping, [k]: e.target.value })}>
                  <option value="">{req ? "Choose a column" : "Not in file"}</option>
                  {info.columns.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </label>
            ))}
          </div>
          <div className="form-grid">
            <label className="field">Chain
              <select value={chainMode} onChange={(e) => setChainMode(e.target.value as "one" | "column")}>
                <option value="one">One chain for the whole file</option>
                <option value="column">The file has a chain column</option>
              </select>
            </label>
            {chainMode === "one" && (
              <label className="field">Which chain
                <select value={chainKey} onChange={(e) => setChainKey(e.target.value)}>
                  {(chains ?? []).filter((c) => c.enabled).map((c) => <option key={c.key} value={c.key}>{c.name}</option>)}
                </select>
              </label>
            )}
            <label className="field">Value is in
              <select value={valueUnit} onChange={(e) => setValueUnit(e.target.value as "native" | "wei")}>
                <option value="native">Whole coins (e.g. 1.5 ETH, 0.2 BTC)</option>
                <option value="wei">Smallest unit (wei, satoshi, lamport)</option>
              </select>
            </label>
            <label className="field">Gas price is in
              <select value={gasUnit} onChange={(e) => setGasUnit(e.target.value as "gwei" | "wei")}>
                <option value="gwei">Gwei</option>
                <option value="wei">Wei</option>
              </select>
            </label>
          </div>
          <h3>First rows of the file</h3>
          <div className="scroll">
            <table>
              <thead><tr>{info.columns.map((c) => <th key={c} className="txt">{c}</th>)}</tr></thead>
              <tbody>
                {info.preview.slice(0, 5).map((row, i) => (
                  <tr key={i}>{info.columns.map((c) => <td key={c} className="txt mono">{String(row[c] ?? "").slice(0, 28)}</td>)}</tr>
                ))}
              </tbody>
            </table>
          </div>
          <label className="check"><input type="checkbox" checked={analyse} onChange={(e) => setAnalyse(e.target.checked)} /> Run analytics when loading finishes</label>
          {missing.length > 0 && <p className="sub">Still needed: {missing.join(", ")}.</p>}
          {start.error && <ErrorNotice error={start.error} title="Could not start loading" />}
          <div><button className="btn primary" disabled={missing.length > 0 || start.isPending} onClick={() => start.mutate()}>
            {start.isPending ? "Starting…" : "Load into database"}
          </button></div>
          <p className="sub">Rows that fail checks (missing hash, bad timestamp, unknown chain) are skipped and listed in a rejects file; the job shows how many.</p>
        </Panel>
      )}
    </>
  );
}
