import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Job } from "../api/types";
import { ChainName, ErrorNotice, Panel, Progress, Status } from "../components/ui";
import { chainMap, useChains } from "../lib/chains";
import { int, utcTime } from "../lib/format";

const ACTIVE = ["queued", "running", "cancelling"];
const JOB_TYPE: Record<string, string> = { fetch: "Fetch from API", load_upload: "Load data dump", analytics: "Analytics run",
  enrich_tokens: "Load token data", scam_detect: "Scam detectors" };
const SOURCE: Record<string, string> = { api: "API fetch", upload: "Data dump", sync: "Live sync" };

export default function Jobs() {
  const qc = useQueryClient();
  const jobs = useQuery({
    queryKey: ["jobs"], queryFn: api.jobs,
    refetchInterval: (q) => ((q.state.data ?? []).some((j: Job) => ACTIVE.includes(j.status)) ? 2000 : 10_000),
  });
  const anyActive = (jobs.data ?? []).some((j) => ACTIVE.includes(j.status));
  const datasets = useQuery({ queryKey: ["datasets"], queryFn: api.datasets, refetchInterval: anyActive ? 3000 : false });
  const runs = useQuery({ queryKey: ["runs"], queryFn: api.runs, refetchInterval: anyActive ? 3000 : false });
  const { data: chains } = useChains();
  const byKey = chainMap(chains);
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null);

  const refresh = () => ["jobs", "datasets", "runs"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  const cancel = useMutation({ mutationFn: api.cancelJob, onSuccess: refresh });
  const retry = useMutation({ mutationFn: api.retryJob, onSuccess: refresh });
  const analyse = useMutation({ mutationFn: api.startRun, onSuccess: refresh });
  const remove = useMutation({ mutationFn: api.deleteDataset, onSuccess: () => { setConfirmDelete(null); refresh(); } });
  const actionError = cancel.error || retry.error || analyse.error || remove.error;

  return (
    <>
      <div className="page-head">
        <div className="meta">
          <h1>Datasets &amp; jobs</h1>
          <p className="sub">Everything loaded into the database, every analytics run, and the jobs that produced them.</p>
        </div>
        <Link className="btn primary" to="/data">Add data</Link>
      </div>
      {actionError && <ErrorNotice error={actionError} title="That action did not work" />}

      <Panel title="Jobs" aside={anyActive ? "updating live" : undefined}>
        {jobs.error && <ErrorNotice error={jobs.error} />}
        <div className="scroll">
          <table>
            <thead><tr><th>Job</th><th className="txt">Type</th><th className="txt">Status</th><th className="txt">Progress</th><th className="txt">Details</th><th className="txt">Started</th><th /></tr></thead>
            <tbody>
              {(jobs.data ?? []).map((j) => (
                <tr key={j.id}>
                  <td>#{j.id}</td>
                  <td className="txt">{JOB_TYPE[j.type] ?? j.type}</td>
                  <td className="txt"><Status value={j.status} /></td>
                  <td className="txt" style={{ minWidth: 140 }}><Progress value={j.progress} status={j.status} /></td>
                  <td className="txt wrap">
                    {j.error ? <span style={{ color: "var(--critical)" }}>{j.error}</span> : j.message}
                  </td>
                  <td className="txt">{utcTime(j.started_at ?? j.created_at)}</td>
                  <td>
                    {ACTIVE.includes(j.status) && j.status !== "cancelling" && <button className="btn small" onClick={() => cancel.mutate(j.id)}>Cancel</button>}
                    {(j.status === "failed" || j.status === "cancelled") && <button className="btn small" onClick={() => retry.mutate(j.id)}>Retry</button>}
                  </td>
                </tr>
              ))}
              {jobs.data?.length === 0 && <tr><td colSpan={7} className="muted" style={{ textAlign: "left" }}>No jobs yet. <Link to="/data">Add data</Link> to start one.</td></tr>}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel title="Datasets">
        <div className="scroll">
          <table>
            <thead><tr><th>Dataset</th><th className="txt">Source</th><th className="txt">Chains</th><th>Transactions</th><th>Blocks</th><th className="txt">Time range (UTC)</th><th className="txt">Status</th><th /></tr></thead>
            <tbody>
              {(datasets.data ?? []).map((d) => (
                <tr key={d.id}>
                  <td className="txt">#{d.id} {d.name}</td>
                  <td className="txt">{SOURCE[d.source_type] ?? d.source_type}</td>
                  <td className="txt">{d.chains.map((c) => <span key={c} style={{ marginRight: 10 }}><ChainName chainKey={c} name={byKey[c]?.name} /></span>)}</td>
                  <td>{int(d.row_count)}</td>
                  <td>{d.first_block != null ? `${int(d.first_block)} – ${int(d.last_block)}` : "–"}</td>
                  <td className="txt">{d.time_from ? `${utcTime(d.time_from)} → ${utcTime(d.time_to)}` : "–"}</td>
                  <td className="txt"><Status value={d.status} /></td>
                  <td>
                    <div className="row" style={{ justifyContent: "flex-end", flexWrap: "nowrap" }}>
                      <button className="btn small" disabled={d.status !== "ready" || !d.chains.length || analyse.isPending}
                        onClick={() => analyse.mutate({ chains: d.chains, dataset_id: d.id })}>Run analytics</button>
                      {confirmDelete === d.id ? (
                        <>
                          <button className="btn small danger" onClick={() => remove.mutate(d.id)}>Delete {int(d.row_count)} rows</button>
                          <button className="btn small" onClick={() => setConfirmDelete(null)}>Keep</button>
                        </>
                      ) : (
                        <button className="btn small" onClick={() => setConfirmDelete(d.id)}>Delete</button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
              {datasets.data?.length === 0 && <tr><td colSpan={8} className="muted" style={{ textAlign: "left" }}>No datasets yet.</td></tr>}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel title="Analytics runs">
        <div className="scroll">
          <table>
            <thead><tr><th>Run</th><th className="txt">Chains</th><th className="txt">Scope</th><th>Transactions</th><th>Wallets</th><th className="txt">Status</th><th className="txt">Created</th><th /></tr></thead>
            <tbody>
              {(runs.data ?? []).map((r) => (
                <tr key={r.id}>
                  <td>#{r.id}</td>
                  <td className="txt">{r.chains.map((c) => <span key={c} style={{ marginRight: 10 }}><ChainName chainKey={c} name={byKey[c]?.name} /></span>)}</td>
                  <td className="txt">{r.dataset_id ? `Dataset #${r.dataset_id}` : r.time_from ? `${utcTime(r.time_from)} → ${utcTime(r.time_to)}` : "All stored data"}</td>
                  <td>{int(r.transactions)}</td>
                  <td>{int(r.wallets)}</td>
                  <td className="txt"><Status value={r.status} /></td>
                  <td className="txt">{utcTime(r.created_at)}</td>
                  <td>{r.status === "succeeded" && <Link className="btn small" to={`/?run=${r.id}`}>View</Link>}</td>
                </tr>
              ))}
              {runs.data?.length === 0 && <tr><td colSpan={8} className="muted" style={{ textAlign: "left" }}>No analytics runs yet.</td></tr>}
            </tbody>
          </table>
        </div>
      </Panel>
    </>
  );
}
