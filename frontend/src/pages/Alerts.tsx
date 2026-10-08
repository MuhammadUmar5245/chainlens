import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ApiError, api } from "../api/client";
import ChainTicker, { RunSelect } from "../components/ChainTicker";
import { Card, Coin, Empty, ErrorNotice, Flow, TagChips } from "../components/ui";
import { chainMap, useChains } from "../lib/chains";
import { useFilters } from "../lib/filters";
import { coin, int, shortAddr, utcTime } from "../lib/format";

/** Flagged wallets as alert cards, most unusual first. */
export default function Alerts() {
  const { run, chains } = useFilters();
  const f = { run, chains };
  const summary = useQuery({ queryKey: ["summary", f], queryFn: () => api.summary(f), retry: false });
  const q = useQuery({
    queryKey: ["alerts", f],
    queryFn: () => api.wallets({ ...f, anomaliesOnly: true, sort: "anomaly_score", limit: 48 }),
    enabled: summary.isSuccess,
  });
  const { data: chainList } = useChains();
  const byKey = chainMap(chainList);
  const z = summary.data?.run.settings.anomaly_z ?? 3;
  const top = Math.max(1, ...(q.data?.rows ?? []).map((w) => w.anomaly_score));

  return (
    <>
      <div className="page-head">
        <div className="meta">
          <span className="eyebrow">Anomaly feed</span>
          <h1>Alerts</h1>
          <p className="sub">Wallets whose behaviour sits far outside their chain's normal range (score ≥ {z}). Highest first.</p>
        </div>
        <RunSelect />
      </div>
      {summary.data && <ChainTicker runChains={summary.data.run.chains} stats={summary.data.per_chain} />}
      {summary.error instanceof ApiError && summary.error.status === 404 && (
        <Card><Empty title="No analytics yet"><Link className="btn primary" to="/data">Add data</Link></Empty></Card>
      )}
      {q.error && <ErrorNotice error={q.error} title="Could not load alerts" />}
      {q.data && (
        <p className="sub">{int(q.data.total)} flagged wallets{q.data.total > q.data.rows.length ? ` · showing the top ${q.data.rows.length}` : ""} · <Link to="/wallets?view=anomalies">open as table →</Link></p>
      )}
      <div className="alerts">
        {(q.data?.rows ?? []).map((w) => {
          const critical = w.anomaly_score >= 2 * z;
          const sym = byKey[w.chain]?.native_symbol;
          return (
            <Link key={`${w.chain}-${w.wallet}`} to={`/wallets/${w.chain}/${w.wallet}${run ? `?run=${run}` : ""}`}
              className={`card alert-card ${critical ? "critical" : ""}`} style={{ color: "inherit", textDecoration: "none" }}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <span className="row" style={{ gap: 8 }}><Coin chainKey={w.chain} /><span className="mono">{shortAddr(w.wallet)}</span></span>
                <span className={`sev ${critical ? "critical" : "serious"}`}>▲ {critical ? "Extreme" : "Unusual"}</span>
              </div>
              <div className="row" style={{ alignItems: "baseline", gap: 8 }}>
                <span className="score">{w.anomaly_score.toFixed(2)}</span>
                <span className="muted">anomaly score</span>
              </div>
              <div className="scorebar"><i style={{ width: `${(w.anomaly_score / top) * 100}%` }} /></div>
              <dl className="mini-stats">
                <div><dt>Volume</dt><dd>{coin(w.volume)} <small className="muted">{sym}</small></dd></div>
                <div><dt>Sent / recv</dt><dd>{int(w.tx_out)} / {int(w.tx_in)}</dd></div>
                <div><dt>Net flow</dt><dd><Flow value={w.net_flow} /></dd></div>
              </dl>
              <div><TagChips tags={w.tags} /></div>
              <span className="sub">Active {utcTime(w.first_seen)} → {utcTime(w.last_seen, false)} UTC</span>
            </Link>
          );
        })}
      </div>
      {q.data && q.data.rows.length === 0 && <Card><Empty title="No alerts">No wallet crossed the threshold for this selection.</Empty></Card>}
    </>
  );
}
