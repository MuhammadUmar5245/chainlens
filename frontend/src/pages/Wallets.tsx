import { useEffect, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { ApiError, api, type WalletQuery } from "../api/client";
import ChainTicker, { RunSelect } from "../components/ChainTicker";
import { Card, ChainName, Empty, ErrorNotice, Flow, Severity, TagChips } from "../components/ui";
import { TAGS, chainMap, useChains } from "../lib/chains";
import { useFilters } from "../lib/filters";
import { coin, int, pct, shortAddr } from "../lib/format";

const VIEWS = {
  volume: { label: "Top volume", sort: "volume" },
  active: { label: "Most active", sort: "tx_out" },
  anomalies: { label: "Alerts", sort: "anomaly_score", anomaliesOnly: true },
  hubs: { label: "Hubs", sort: "counterparties", tag: "hub_exchange_like" },
  inflow: { label: "Inflows", sort: "net_flow" },
} as const;
type View = keyof typeof VIEWS;

const COLS: { key: string; label: string; sort?: string; txt?: boolean }[] = [
  { key: "wallet", label: "Wallet", txt: true },
  { key: "chain", label: "Chain", txt: true },
  { key: "volume", label: "Volume", sort: "volume" },
  { key: "net_flow", label: "Net flow", sort: "net_flow" },
  { key: "tx_out", label: "Sent", sort: "tx_out" },
  { key: "tx_in", label: "Received", sort: "tx_in" },
  { key: "cp", label: "Counterparties", sort: "counterparties" },
  { key: "contract", label: "Contract" },
  { key: "anomaly", label: "Anomaly", sort: "anomaly_score" },
  { key: "tags", label: "Tags", txt: true },
];

export default function Wallets() {
  const flt = useFilters();
  const navigate = useNavigate();
  const view = (flt.get("view") as View) in VIEWS ? (flt.get("view") as View) : "volume";
  const v = VIEWS[view];
  const sort = flt.get("sort") ?? v.sort;
  const order = (flt.get("order") as "asc" | "desc") ?? "desc";
  const tag = flt.get("tag") ?? ("tag" in v ? v.tag : undefined);
  const page = Number(flt.get("page")) || 1;
  const [search, setSearch] = useState(flt.get("q") ?? "");

  useEffect(() => {
    const id = setTimeout(() => {
      if ((flt.get("q") ?? "") !== search) flt.set({ q: search || undefined });
    }, 300);
    return () => clearTimeout(id);
  }, [search]); // only the typed text should trigger this

  const query: WalletQuery = {
    run: flt.run, chains: flt.chains, tag, q: flt.get("q"), anomaliesOnly: "anomaliesOnly" in v,
    sort, order, page, limit: 50,
  };
  const res = useQuery({ queryKey: ["wallets", query], queryFn: () => api.wallets(query), placeholderData: keepPreviousData, retry: false });
  const summary = useQuery({ queryKey: ["summary", { run: flt.run, chains: flt.chains }], queryFn: () => api.summary({ run: flt.run, chains: flt.chains }), retry: false });
  const { data: chainList } = useChains();
  const byKey = chainMap(chainList);
  const z = summary.data?.run.settings.anomaly_z ?? 3;

  function sortBy(col?: string) {
    if (!col) return;
    flt.set({ sort: col, order: sort === col && order === "desc" ? "asc" : "desc" });
  }

  if (res.error instanceof ApiError && res.error.status === 404) {
    return (
      <>
        <h1>Wallets</h1>
        <Card><Empty title="No analytics yet"><Link className="btn primary" to="/data">Add data</Link></Empty></Card>
      </>
    );
  }

  const data = res.data;
  const pages = data ? Math.max(1, Math.ceil(data.total / data.limit)) : 1;
  const link = (chain: string, wallet: string) => `/wallets/${chain}/${wallet}${flt.run ? `?run=${flt.run}` : ""}`;

  return (
    <>
      <div className="page-head">
        <div className="meta">
          <span className="eyebrow">Explorer</span>
          <h1>Wallets</h1>
          <p className="sub">{data ? `${int(data.total)} wallets` : "Loading…"} · sorted, filtered and paged on the server</p>
        </div>
        <div className="row">
          <RunSelect />
          <a className="btn" href={api.walletExportUrl(query)}>Export CSV</a>
        </div>
      </div>
      {summary.data && <ChainTicker runChains={summary.data.run.chains} stats={summary.data.per_chain} />}
      <Card>
        <div className="row">
          <div className="tabs" role="group" aria-label="View">
            {(Object.keys(VIEWS) as View[]).map((k) => (
              <button key={k} type="button" aria-pressed={k === view}
                onClick={() => flt.set({ view: k === "volume" ? undefined : k, sort: undefined, order: undefined, tag: undefined })}>
                {VIEWS[k].label}
              </button>
            ))}
          </div>
          <select aria-label="Filter by tag" value={tag ?? ""} onChange={(e) => flt.set({ tag: e.target.value || undefined })}>
            <option value="">All tags</option>
            {Object.entries(TAGS).map(([k, t]) => <option key={k} value={k}>{t.label}</option>)}
          </select>
          <input type="search" placeholder="Search address" aria-label="Search wallet address" value={search} onChange={(e) => setSearch(e.target.value)} />
          {res.isFetching && <span className="muted">updating…</span>}
        </div>
        {res.error && <ErrorNotice error={res.error} title="Could not load wallets" />}
        <div className="scroll">
          <table>
            <thead>
              <tr>
                {COLS.map((c) => (
                  <th key={c.key} className={`${c.sort ? "sortable" : ""} ${c.sort === sort ? "sorted" : ""} ${c.txt ? "txt" : ""}`}
                    onClick={() => sortBy(c.sort)} aria-sort={c.sort === sort ? (order === "desc" ? "descending" : "ascending") : undefined}>
                    {c.label}{c.sort === sort ? (order === "desc" ? " ↓" : " ↑") : ""}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data?.rows.map((w) => (
                <tr key={`${w.chain}-${w.wallet}`} className="clickable" onClick={() => navigate(link(w.chain, w.wallet))}>
                  <td><Link className="mono" to={link(w.chain, w.wallet)} title={w.wallet} onClick={(e) => e.stopPropagation()}>{shortAddr(w.wallet)}</Link></td>
                  <td className="txt"><ChainName chainKey={w.chain} name={byKey[w.chain]?.name} /></td>
                  <td>{coin(w.volume)} <span className="muted">{byKey[w.chain]?.native_symbol}</span></td>
                  <td><Flow value={w.net_flow} /></td>
                  <td>{int(w.tx_out)}</td>
                  <td>{int(w.tx_in)}</td>
                  <td>{int(w.uniq_receivers + w.uniq_senders)}</td>
                  <td>{w.tx_out ? pct(w.contract_call_ratio) : "–"}</td>
                  <td>{w.anomaly_score.toFixed(2)}<Severity score={w.anomaly_score} z={z} /></td>
                  <td className="txt"><TagChips tags={w.tags} /></td>
                </tr>
              ))}
              {data && data.rows.length === 0 && (
                <tr><td colSpan={COLS.length} className="txt muted" style={{ padding: "18px 4px" }}>No wallets match. Clear the search or pick another tag or chain.</td></tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="pager">
          <span className="muted">Page {int(page)} of {int(pages)}</span>
          <button className="btn small" disabled={page <= 1} onClick={() => flt.set({ page: page - 1 }, false)}>← Previous</button>
          <button className="btn small" disabled={page >= pages} onClick={() => flt.set({ page: page + 1 }, false)}>Next →</button>
        </div>
      </Card>
    </>
  );
}
