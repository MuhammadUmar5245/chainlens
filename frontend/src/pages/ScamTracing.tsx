import { useRef, useState, type ReactNode } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ApiError, api } from "../api/client";
import { scamApi, type Finding, type Label, type Severity } from "../api/scam";
import ChainTicker, { RunSelect } from "../components/ChainTicker";
import { Card, Coin, Empty, ErrorNotice, Progress, Status } from "../components/ui";
import { useFilters } from "../lib/filters";
import { int, shortAddr, shortHash } from "../lib/format";
import "./scam.css";

type Tab = "findings" | "risk" | "tokens" | "labels";
const SEV: Severity[] = ["high", "medium", "low"];
const DANGER = new Set(["sanctioned", "scam_reported", "mixer"]);

export function LabelChips({ labels }: { labels: { label: string; category: string; source: string }[] }) {
  return (
    <>
      {labels.map((l, i) => (
        <span key={i} title={`${l.category} · ${l.source}`}
          className={`labelchip ${l.source.startsWith("TEST") ? "test" : DANGER.has(l.category) ? "danger" : ""}`}>{l.label}</span>
      ))}
    </>
  );
}

export function SevChip({ s }: { s: Severity }) {
  return <span className={`sevchip ${s}`}>{s === "high" ? "▲ " : ""}{s}</span>;
}

export const traceLink = (chain: string, wallet: string, run?: number) => `/trace/${chain}/${wallet}${run ? `?run=${run}` : ""}`;

export default function ScamTracing() {
  const flt = useFilters();
  const f = { run: flt.run, chains: flt.chains };
  const tab = (flt.get("tab") as Tab) || "findings";
  const detector = flt.get("detector");
  const qc = useQueryClient();

  const base = useQuery({ queryKey: ["summary", f], queryFn: () => api.summary(f), retry: false });
  const summary = useQuery({
    queryKey: ["scam-summary", f], queryFn: () => scamApi.summary(f), enabled: base.isSuccess,
    refetchInterval: (q) => (["queued", "running"].includes(q.state.data?.job?.status ?? "") ? 2000 : false),
  });
  const rerun = useMutation({
    mutationFn: () => scamApi.detect(summary.data!.run_id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["scam-summary"] }); qc.invalidateQueries({ queryKey: ["jobs"] }); },
  });
  const removeTest = useMutation({
    mutationFn: () => scamApi.removeSource("TEST-sample"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["scam-summary"] }),
  });

  if (base.error instanceof ApiError && base.error.status === 404) {
    return (<><Head /><Card><Empty title="No analytics yet"><Link className="btn primary" to="/data">Add data</Link></Empty></Card></>);
  }
  const s = summary.data;
  const job = s?.job;
  const failed = Object.values(job?.detail?.chains ?? {}).flatMap((c) => Object.entries(c.detectors).filter(([, d]) => d.status === "failed").map(([k, d]) => `${k}: ${d.error}`));

  return (
    <>
      <Head actions={
        <div className="row">
          <RunSelect />
          {s && <a className="btn" href={scamApi.exportUrl(f)}>Export Excel</a>}
          {s && s.scam_chains.length > 0 && (
            <button className="btn" disabled={rerun.isPending || ["queued", "running"].includes(job?.status ?? "")} onClick={() => rerun.mutate()}>
              Run detectors again
            </button>
          )}
        </div>
      } />
      {base.data && <ChainTicker runChains={base.data.run.chains} stats={base.data.per_chain} />}
      <div className="indicator-note" role="note">
        <b>Indicators, not proof.</b>
        <span>Every result here is a pattern that is often seen in scams. It can also have an innocent explanation. Check before acting.</span>
      </div>
      {s && s.test_labels_loaded > 0 && (
        <div className="notice warn">
          <strong>{s.test_labels_loaded} TEST labels are loaded</strong>
          <span>They come from the sample data for trying the MVP and are not real reports. Replace them with your own lists under Labels.</span>
          <div><button className="btn small" onClick={() => removeTest.mutate()} disabled={removeTest.isPending}>Remove TEST labels</button></div>
        </div>
      )}
      {s && s.scam_chains.length === 0 && (
        <div className="notice">None of the selected chains is supported by the scam detectors.</div>
      )}
      {rerun.error && <ErrorNotice error={rerun.error} title="Could not start the detectors" />}
      {job && ["queued", "running"].includes(job.status) && (
        <Card title={<div className="row"><h2>Detectors running</h2><Status value={job.status} /></div>}>
          <Progress value={job.progress} status={job.status as "running"} />
          <span className="sub">{job.message}</span>
        </Card>
      )}
      {failed.length > 0 && <ErrorNotice error={failed.join(" · ")} title="Some detectors failed (the others completed)" />}

      {s && (
        <section className="det-grid" aria-label="Detectors">
          {s.detectors.map((d) => {
            const per = Object.entries(job?.detail?.chains ?? {}).map(([chain, c]) => ({ chain, ...(c.detectors[d.id] ?? { status: "" }) }));
            const st = per.map((x) => x.status);
            const skipped = per.filter((x) => x.status === "skipped");
            const total = Math.max(1, d.findings);
            return (
              <button key={d.id} type="button" className={`det ${st.includes("failed") ? "failed" : ""}`} aria-pressed={detector === d.id}
                onClick={() => flt.set({ detector: detector === d.id ? undefined : d.id, tab: "findings" })}>
                <span className="id">{d.id}</span>
                <span className="name">{d.name}</span>
                <span className="count">{int(d.findings)}</span>
                <span className="sub">{int(d.wallets)} wallets</span>
                {skipped.length > 0 && (
                  <span className="muted" style={{ fontSize: 11.5 }} title={skipped.map((x) => `${x.chain}: ${(x as { reason?: string }).reason ?? ""}`).join("\n")}>
                    not applicable on {skipped.map((x) => x.chain.toUpperCase()).join(", ")}
                  </span>
                )}
                <span className="sevbar">{SEV.map((v) => <i key={v} className={`sev-${v}`} style={{ width: `${(d.by_severity[v] / total) * 100}%` }} />)}</span>
              </button>
            );
          })}
        </section>
      )}

      <div className="subtabs" role="tablist">
        {([["findings", "Findings"], ["risk", "Wallet risk"], ["tokens", "Token data"], ["labels", "Labels"]] as [Tab, string][]).map(([k, l]) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => flt.set({ tab: k === "findings" ? undefined : k })}>{l}</button>
        ))}
      </div>
      {tab === "findings" && <FindingsTab f={f} detector={detector} names={Object.fromEntries((s?.detectors ?? []).map((d) => [d.id, d.name]))} />}
      {tab === "risk" && <RiskTab f={f} wallets={s?.wallets_by_severity} />}
      {tab === "tokens" && <TokensTab />}
      {tab === "labels" && <LabelsTab />}
    </>
  );
}

function Head({ actions }: { actions?: ReactNode }) {
  return (
    <div className="page-head">
      <div className="meta">
        <span className="eyebrow">Scam tracing</span>
        <h1>Suspicious activity</h1>
        <p className="sub">Ten detectors look for patterns often seen in scams. Each wallet gets a risk score with its top reasons.</p>
      </div>
      {actions}
    </div>
  );
}

function FindingsTab({ f, detector, names }: { f: { run?: number; chains?: string[] }; detector?: string; names: Record<string, string> }) {
  const flt = useFilters();
  const severity = flt.get("severity");
  const page = Number(flt.get("page")) || 1;
  const [wallet, setWallet] = useState("");
  const q = useQuery({
    queryKey: ["findings", f, detector, severity, flt.get("wallet"), page],
    queryFn: () => scamApi.findings({ ...f, detector, severity, wallet: flt.get("wallet"), page, limit: 50 }),
    placeholderData: keepPreviousData,
  });
  const pages = q.data ? Math.max(1, Math.ceil(q.data.total / q.data.limit)) : 1;
  return (
    <Card title={detector ? `${detector} · ${names[detector] ?? ""}` : "All findings"} hint={q.data ? `${int(q.data.total)} findings` : ""}
      actions={
        <div className="row">
          <div className="tabs" role="group" aria-label="Severity">
            {[undefined, ...SEV].map((v) => (
              <button key={v ?? "all"} type="button" aria-pressed={severity === v} onClick={() => flt.set({ severity: v })}>{v ?? "All"}</button>
            ))}
          </div>
          <input type="search" placeholder="Wallet address" aria-label="Filter by wallet" value={wallet}
            onChange={(e) => setWallet(e.target.value)} onKeyDown={(e) => e.key === "Enter" && flt.set({ wallet: wallet || undefined })}
            onBlur={() => flt.set({ wallet: wallet || undefined })} />
          {detector && <button className="btn small" onClick={() => flt.set({ detector: undefined })}>Show all detectors</button>}
        </div>
      }>
      {q.error && <ErrorNotice error={q.error} />}
      <div className="scroll">
        <table>
          <thead><tr><th className="txt">Severity</th><th className="txt">Detector</th><th className="txt">Wallet</th><th className="txt">Indicator</th><th>Score</th><th className="txt">Evidence</th></tr></thead>
          <tbody>
            {q.data?.rows.map((r: Finding) => (
              <tr key={r.id}>
                <td className="txt"><SevChip s={r.severity} /></td>
                <td className="txt"><span className="mono">{r.detector}</span> <span className="muted">{names[r.detector]}</span></td>
                <td><span className="row" style={{ gap: 6, flexWrap: "nowrap" }}><Coin chainKey={r.chain} />
                  <Link className="mono" to={traceLink(r.chain, r.wallet, f.run)} title={`Trace ${r.wallet}`}>{shortAddr(r.wallet)}</Link></span></td>
                <td className="wrap">{r.reason}</td>
                <td>{r.score}</td>
                <td className="txt" title={r.tx_hashes.join("\n")}>
                  <span className="mono">{r.tx_hashes.slice(0, 2).map(shortHash).join(", ")}</span>
                  {r.tx_hashes.length > 2 && <span className="muted"> +{r.tx_hashes.length - 2}</span>}
                  {r.related_wallets.length > 0 && <div className="muted" style={{ fontSize: 11.5 }}>{r.related_wallets.length} related wallet{r.related_wallets.length > 1 ? "s" : ""}</div>}
                </td>
              </tr>
            ))}
            {q.data?.rows.length === 0 && <tr><td colSpan={6} className="txt muted" style={{ padding: 16 }}>No findings for this filter.</td></tr>}
          </tbody>
        </table>
      </div>
      <div className="pager">
        <span className="muted">Page {int(page)} of {int(pages)}</span>
        <button className="btn small" disabled={page <= 1} onClick={() => flt.set({ page: page - 1 }, false)}>← Previous</button>
        <button className="btn small" disabled={page >= pages} onClick={() => flt.set({ page: page + 1 }, false)}>Next →</button>
      </div>
    </Card>
  );
}

function RiskTab({ f, wallets }: { f: { run?: number; chains?: string[] }; wallets?: Record<Severity, number> }) {
  const flt = useFilters();
  const severity = flt.get("rsev");
  const page = Number(flt.get("page")) || 1;
  const q = useQuery({ queryKey: ["risk", f, severity, page], queryFn: () => scamApi.risk({ ...f, severity, page, limit: 50 }), placeholderData: keepPreviousData });
  const pages = q.data ? Math.max(1, Math.ceil(q.data.total / q.data.limit)) : 1;
  return (
    <Card title="Wallet risk leaderboard" hint="0–100, from the strongest finding of each detector"
      actions={
        <div className="tabs" role="group" aria-label="Risk level">
          {[undefined, ...SEV].map((v) => (
            <button key={v ?? "all"} type="button" aria-pressed={severity === v} onClick={() => flt.set({ rsev: v })}>
              {v ?? "All"}{v && wallets ? ` · ${int(wallets[v])}` : ""}
            </button>
          ))}
        </div>
      }>
      {q.error && <ErrorNotice error={q.error} />}
      <div className="scroll">
        <table>
          <thead><tr><th>#</th><th className="txt">Wallet</th><th>Risk</th><th className="txt">Detectors</th><th className="txt">Top reasons</th><th className="txt">Labels</th></tr></thead>
          <tbody>
            {q.data?.rows.map((r, i) => (
              <tr key={`${r.chain}-${r.wallet}`}>
                <td>{(page - 1) * 50 + i + 1}</td>
                <td><span className="row" style={{ gap: 6, flexWrap: "nowrap" }}><Coin chainKey={r.chain} />
                  <Link className="mono" to={traceLink(r.chain, r.wallet, f.run)}>{shortAddr(r.wallet)}</Link></span></td>
                <td style={{ whiteSpace: "nowrap" }}><b>{r.risk_score}</b><span className="riskbar"><i style={{ width: `${r.risk_score}%` }} /></span> <SevChip s={r.severity} /></td>
                <td className="txt">{r.detectors_hit.map((d) => <span key={d} className="chip">{d}</span>)}</td>
                <td className="txt"><ol className="reasons">{r.top_reasons.map((x, j) => <li key={j}>{x}</li>)}</ol></td>
                <td className="txt"><LabelChips labels={r.labels} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="pager">
        <span className="muted">Page {int(page)} of {int(pages)}</span>
        <button className="btn small" disabled={page <= 1} onClick={() => flt.set({ page: page - 1 }, false)}>← Previous</button>
        <button className="btn small" disabled={page >= pages} onClick={() => flt.set({ page: page + 1 }, false)}>Next →</button>
      </div>
    </Card>
  );
}

function TokensTab() {
  const qc = useQueryClient();
  const datasets = useQuery({ queryKey: ["datasets"], queryFn: api.datasets });
  const jobs = useQuery({ queryKey: ["jobs"], queryFn: api.jobs, refetchInterval: 3000 });
  const enrich = useMutation({ mutationFn: (d: { chain: string; id: number }) => scamApi.enrich({ chain: d.chain, dataset_id: d.id }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }) });
  const evm = new Set(["eth", "ethw", "etc"]);
  const rows = (datasets.data ?? []).filter((d) => d.status === "ready" && d.chains.some((c) => evm.has(c)));
  const enrichJobs = (jobs.data ?? []).filter((j) => (j.type as string) === "enrich_tokens");      // new job type, not in the existing Job union
  return (
    <Card title="Token data (ERC-20 transfers and approvals)" hint="loaded automatically after each EVM fetch">
      <p className="sub" style={{ maxWidth: "70ch" }}>
        Most scams move USDT or USDC, which normal transactions show only as zero-value contract calls. Loading token data reads the
        Transfer and Approval logs for the dataset's blocks from NOWNodes. Run the detectors again afterwards.
      </p>
      {enrich.error && <ErrorNotice error={enrich.error} />}
      <div className="scroll">
        <table>
          <thead><tr><th className="txt">Dataset</th><th className="txt">Chain</th><th>Transactions</th><th className="txt">Token data</th><th /></tr></thead>
          <tbody>
            {rows.map((d) => {
              const chain = d.chains.find((c) => evm.has(c))!;
              const last = enrichJobs.find((j) => j.dataset_id === d.id);
              return (
                <tr key={d.id}>
                  <td className="txt">#{d.id} {d.name}</td>
                  <td className="txt"><Coin chainKey={chain} /></td>
                  <td>{int(d.row_count)}</td>
                  <td className="txt">{last ? <><Status value={last.status} /> <span className="muted">{last.message}</span></> : <span className="muted">not loaded</span>}</td>
                  <td><button className="btn small" disabled={enrich.isPending || ["queued", "running"].includes(last?.status ?? "")}
                    onClick={() => enrich.mutate({ chain, id: d.id })}>{last?.status === "succeeded" ? "Load again" : "Load token data"}</button></td>
                </tr>
              );
            })}
            {rows.length === 0 && <tr><td colSpan={5} className="txt muted">No EVM datasets yet.</td></tr>}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function LabelsTab() {
  const qc = useQueryClient();
  const [category, setCategory] = useState("");
  const [q, setQ] = useState("");
  const [source, setSource] = useState("");
  const [chain, setChain] = useState("eth");
  const file = useRef<HTMLInputElement>(null);
  const labels = useQuery({ queryKey: ["labels", category, q], queryFn: () => scamApi.labels({ category: category || undefined, q: q || undefined }) });
  const refresh = () => { qc.invalidateQueries({ queryKey: ["labels"] }); qc.invalidateQueries({ queryKey: ["scam-summary"] }); };
  const upload = useMutation({ mutationFn: (fl: File) => scamApi.importLabels(fl, source, chain), onSuccess: refresh });
  const test = useMutation({ mutationFn: scamApi.loadTestLabels, onSuccess: refresh });
  const remove = useMutation({ mutationFn: scamApi.removeSource, onSuccess: refresh });
  return (
    <div className="grid cols-main">
      <Card title="Address labels" hint={labels.data ? `${int(labels.data.total)} labels` : ""}
        actions={
          <div className="row">
            <select aria-label="Category" value={category} onChange={(e) => setCategory(e.target.value)}>
              <option value="">All categories</option>
              {(labels.data?.categories ?? []).map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
            <input type="search" placeholder="Address or label" aria-label="Search labels" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
        }>
        <div className="scroll">
          <table>
            <thead><tr><th className="txt">Address</th><th className="txt">Chain</th><th className="txt">Label</th><th className="txt">Category</th><th className="txt">Source</th></tr></thead>
            <tbody>
              {labels.data?.rows.map((l: Label) => (
                <tr key={l.id}>
                  <td className="mono" title={l.address}>{shortAddr(l.address)}</td>
                  <td className="txt"><Coin chainKey={l.chain} /></td>
                  <td className="txt">{l.label}</td>
                  <td className="txt"><span className="chip">{l.category}</span></td>
                  <td className="txt muted">{l.source}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <Card title="Add labels" hint="you supply the lists; nothing is scraped">
        <p className="sub">CSV columns: <span className="mono">address, label, category</span> and optionally <span className="mono">chain, source</span>.
          Categories: exchange, bridge, mixer, sanctioned, scam_reported, defi, token, other.</p>
        <label className="field">Source name (e.g. ofac-2026-10)<input type="text" value={source} onChange={(e) => setSource(e.target.value)} /></label>
        <label className="field">Default chain
          <select value={chain} onChange={(e) => setChain(e.target.value)}>{["eth", "ethw", "etc", "btc", "sol"].map((c) => <option key={c}>{c}</option>)}</select>
        </label>
        <input ref={file} type="file" accept=".csv,text/csv" hidden onChange={(e) => { const fl = e.target.files?.[0]; if (fl) upload.mutate(fl); e.target.value = ""; }} />
        <div className="row">
          <button className="btn primary" disabled={upload.isPending} onClick={() => file.current?.click()}>Upload CSV</button>
          <button className="btn" disabled={test.isPending} onClick={() => test.mutate()}>Load TEST labels</button>
        </div>
        {upload.data && <div className="notice">{upload.data.imported} imported · {upload.data.rejected} rejected{upload.data.errors.length ? `: ${upload.data.errors.slice(0, 3).join("; ")}` : ""}</div>}
        {(upload.error || test.error || remove.error) && <ErrorNotice error={upload.error || test.error || remove.error} />}
        <h3>Sources</h3>
        <div className="list">
          {(labels.data?.sources ?? []).map((s) => (
            <div key={s.source} className="list-row" style={{ gridTemplateColumns: "1fr auto auto" }}>
              <span>{s.source}</span><span className="muted">{int(s.count)}</span>
              {s.source !== "builtin" ? <button className="btn small danger" onClick={() => remove.mutate(s.source)}>Remove</button> : <span className="muted">built-in</span>}
            </div>
          ))}
        </div>
        <p className="sub">Labels apply the next time the detectors run.</p>
      </Card>
    </div>
  );
}
