import { useMemo, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { PairRow, Summary } from "../api/types";
import ChainTicker, { RunSelect } from "../components/ChainTicker";
import EChart, { chrome } from "../components/EChart";
import { Card, Coin, Empty, ErrorNotice, TagChips } from "../components/ui";
import { chainColor, chainMap, tagLabel, useChains } from "../lib/chains";
import { useFilters } from "../lib/filters";
import { coin, int, pct, shortAddr, utcTime } from "../lib/format";

const SORTS = { txs: "Most interactions", two_way: "Two-way first", value: "Highest value", recent: "Most recent" } as const;
type Sort = keyof typeof SORTS;

/** Which wallets transact with each other the most: network graph + ranked pairs. */
export default function Connections() {
  const flt = useFilters();
  const navigate = useNavigate();
  const f = { run: flt.run, chains: flt.chains };
  const sort = (flt.get("sort") as Sort) in SORTS ? (flt.get("sort") as Sort) : "txs";
  const minTxs = Number(flt.get("min")) || 2;
  const twoWay = flt.get("twoway") === "1";
  const transfersOnly = flt.get("transfers") === "1";
  const page = Number(flt.get("page")) || 1;
  const [search, setSearch] = useState(flt.get("q") ?? "");
  const filters = { ...f, minTxs, twoWay, transfersOnly, q: flt.get("q"), sort };

  const summary = useQuery({ queryKey: ["summary", f], queryFn: () => api.summary(f), retry: false });
  const table = useQuery({ queryKey: ["pairs", filters, page], queryFn: () => api.pairs({ ...filters, page, limit: 50 }),
    enabled: summary.isSuccess, placeholderData: keepPreviousData });
  const graph = useQuery({ queryKey: ["pairs-graph", filters], queryFn: () => api.pairs({ ...filters, sort: "txs", limit: 90 }),
    enabled: summary.isSuccess });
  const { data: chainList } = useChains();
  const byKey = chainMap(chainList);

  if (summary.error instanceof ApiError && summary.error.status === 404) {
    return (<><Head /><Card><Empty title="No analytics yet"><Link className="btn primary" to="/data">Add data</Link></Empty></Card></>);
  }
  const data = table.data;
  const pages = data ? Math.max(1, Math.ceil(data.total / data.limit)) : 1;

  return (
    <>
      <Head />
      {summary.data && <ChainTicker runChains={summary.data.run.chains} stats={summary.data.per_chain} />}
      {data && !data.computed && summary.data && <Recompute s={summary.data} />}

      <Card>
        <div className="row">
          <div className="tabs" role="group" aria-label="Sort pairs">
            {(Object.keys(SORTS) as Sort[]).map((k) => (
              <button key={k} type="button" aria-pressed={k === sort} onClick={() => flt.set({ sort: k === "txs" ? undefined : k })}>{SORTS[k]}</button>
            ))}
          </div>
          <label className="field" style={{ gridAutoFlow: "column", alignItems: "center", gap: 8 }}>At least
            <select aria-label="Minimum interactions" value={minTxs} onChange={(e) => flt.set({ min: e.target.value === "2" ? undefined : e.target.value })}>
              {[2, 3, 5, 10, 25, 100].map((n) => <option key={n} value={n}>{n} interactions</option>)}
            </select>
          </label>
          <label className="check"><input type="checkbox" checked={twoWay} onChange={(e) => flt.set({ twoway: e.target.checked ? "1" : undefined })} /> Two-way only</label>
          <label className="check"><input type="checkbox" checked={transfersOnly} onChange={(e) => flt.set({ transfers: e.target.checked ? "1" : undefined })} /> Hide contract-only pairs</label>
          <input type="search" placeholder="Search address" aria-label="Search address" value={search}
            onChange={(e) => setSearch(e.target.value)} onKeyDown={(e) => e.key === "Enter" && flt.set({ q: search || undefined })}
            onBlur={() => flt.set({ q: search || undefined })} />
        </div>
      </Card>

      <div className="grid cols-main">
        <Card title="Network" hint="top 90 pairs · node size = interactions · gold links go both ways" className="grow">
          {graph.error ? <ErrorNotice error={graph.error} /> : (
            <Graph rows={graph.data?.rows ?? []} names={byKey}
              onOpen={(chain, wallet) => navigate(`/wallets/${chain}/${wallet}${flt.run ? `?run=${flt.run}` : ""}`)} />
          )}
          <p className="sub">Click a wallet to open it. Red rings mark wallets with an alert.</p>
        </Card>
        <TopHubs rows={graph.data?.rows ?? []} names={byKey} run={flt.run} />
      </div>

      <Card title="Connected pairs" hint={data ? `${int(data.total)} pairs with ${minTxs}+ interactions` : "loading…"}>
        {table.error && <ErrorNotice error={table.error} title="Could not load connections" />}
        <div className="scroll">
          <table>
            <thead>
              <tr>
                <th className="txt">Wallet A</th><th className="txt"></th><th className="txt">Wallet B</th><th className="txt">Chain</th>
                <th>Interactions</th><th>A → B</th><th>B → A</th><th>Value moved</th><th>Contract calls</th><th className="txt">Active (UTC)</th><th className="txt">Tags</th>
              </tr>
            </thead>
            <tbody>
              {data?.rows.map((r) => {
                const sym = byKey[r.chain]?.native_symbol ?? "";
                const both = r.a_to_b > 0 && r.b_to_a > 0;
                const link = (w: string) => `/wallets/${r.chain}/${w}${flt.run ? `?run=${flt.run}` : ""}`;
                return (
                  <tr key={`${r.chain}-${r.a}-${r.b}`}>
                    <td><Link className="mono" to={link(r.a)} title={r.a}>{shortAddr(r.a)}</Link></td>
                    <td className="txt" title={both ? "both directions" : "one direction"}>
                      <span style={{ color: both ? "var(--accent)" : "var(--muted)", fontWeight: 700 }}>{both ? "⇄" : r.a_to_b ? "→" : "←"}</span>
                    </td>
                    <td><Link className="mono" to={link(r.b)} title={r.b}>{shortAddr(r.b)}</Link></td>
                    <td className="txt"><Coin chainKey={r.chain} /></td>
                    <td style={{ fontWeight: 600 }}>{int(r.txs)}</td>
                    <td>{int(r.a_to_b)}</td>
                    <td>{int(r.b_to_a)}</td>
                    <td>{coin(r.value_a_to_b + r.value_b_to_a)} <span className="muted">{sym}</span></td>
                    <td>{pct(r.contract_calls / Math.max(r.txs, 1))}</td>
                    <td className="txt">{utcTime(r.first_seen)} → {utcTime(r.last_seen, false)}</td>
                    <td className="txt"><TagChips tags={[...new Set([...r.a_info.tags, ...r.b_info.tags])]} /></td>
                  </tr>
                );
              })}
              {data && data.rows.length === 0 && (
                <tr><td colSpan={11} className="txt muted" style={{ padding: "18px 4px" }}>No pairs match. Lower the minimum or clear the filters.</td></tr>
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

function Head() {
  return (
    <div className="page-head">
      <div className="meta">
        <span className="eyebrow">Network</span>
        <h1>Connections</h1>
        <p className="sub">Wallets that transact with each other the most. Pairs with two or more transactions between them, in either direction.</p>
      </div>
      <RunSelect />
    </div>
  );
}

function Recompute({ s }: { s: Summary }) {
  const qc = useQueryClient();
  const start = useMutation({
    mutationFn: () => api.startRun({ chains: s.run.chains, dataset_id: s.run.dataset_id ?? undefined }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
  });
  return (
    <div className="notice warn">
      <strong>Connections are not computed for run #{s.run.id}</strong>
      <span>This run was made before the connections feature existed. Run analytics again on the same data to build them.</span>
      <div className="row">
        <button className="btn small primary" disabled={start.isPending || start.isSuccess} onClick={() => start.mutate()}>
          {start.isSuccess ? "Started. See Jobs" : "Run analytics again"}
        </button>
        {start.error && <span className="down">{(start.error as Error).message}</span>}
      </div>
    </div>
  );
}

type Names = ReturnType<typeof chainMap>;

function Graph({ rows, names, onOpen }: { rows: PairRow[]; names: Names; onOpen: (chain: string, wallet: string) => void }) {
  const option = useMemo(() => {
    const c = chrome();
    const nodes = new Map<string, { chain: string; wallet: string; weight: number; flagged: boolean; tags: string[]; links: number }>();
    const add = (chain: string, wallet: string, txs: number, info: PairRow["a_info"]) => {
      const k = `${chain}|${wallet}`;
      const n = nodes.get(k) ?? { chain, wallet, weight: 0, flagged: info.anomaly_score >= 3, tags: info.tags, links: 0 };
      n.weight += txs;
      n.links += 1;
      nodes.set(k, n);
    };
    rows.forEach((r) => { add(r.chain, r.a, r.txs, r.a_info); add(r.chain, r.b, r.txs, r.b_info); });
    const maxW = Math.max(1, ...[...nodes.values()].map((n) => n.weight));
    const maxT = Math.max(1, ...rows.map((r) => r.txs));
    const labelled = new Set([...nodes.entries()].sort((x, y) => y[1].weight - x[1].weight).slice(0, 12).map(([k]) => k));
    return {
      tooltip: {
        ...c.tooltip,
        formatter: (p: { dataType: string; data: { n?: { chain: string; wallet: string; weight: number; links: number; tags: string[] }; r?: PairRow } }) => {
          if (p.dataType === "node" && p.data.n) {
            const n = p.data.n;
            return `<b>${shortAddr(n.wallet)}</b> · ${names[n.chain]?.name ?? n.chain}<br/>${int(n.weight)} interactions with ${n.links} wallet${n.links > 1 ? "s" : ""} shown` +
              (n.tags.length ? `<br/>${n.tags.map(tagLabel).join(" · ")}` : "");
          }
          const r = p.data.r!;
          return `${shortAddr(r.a)} → ${shortAddr(r.b)}: <b>${int(r.a_to_b)}</b><br/>${shortAddr(r.b)} → ${shortAddr(r.a)}: <b>${int(r.b_to_a)}</b><br/>` +
            `value ${coin(r.value_a_to_b + r.value_b_to_a)} ${names[r.chain]?.native_symbol ?? ""}`;
        },
      },
      series: [{
        type: "graph", layout: "force", roam: true, draggable: true,
        force: { repulsion: 140, edgeLength: [40, 140], gravity: 0.08 },
        emphasis: { focus: "adjacency", lineStyle: { width: 4 } },
        data: [...nodes.entries()].map(([k, n]) => {
          const col = chainColor(n.chain);
          return {
            id: k, name: shortAddr(n.wallet), n,
            symbolSize: 8 + 34 * Math.sqrt(n.weight / maxW),
            itemStyle: { color: col, borderColor: n.flagged ? c.down : col, borderWidth: n.flagged ? 3 : 1, shadowBlur: 16, shadowColor: col },
            label: { show: labelled.has(k), color: c.ink, fontSize: 10, fontFamily: "JetBrains Mono, monospace", position: "right" },
          };
        }),
        links: rows.map((r) => {
          const both = r.a_to_b > 0 && r.b_to_a > 0;
          return {
            source: `${r.chain}|${r.a}`, target: `${r.chain}|${r.b}`, r,
            lineStyle: { width: 1 + 5 * (r.txs / maxT), color: both ? c.accent : "rgba(148,163,184,0.45)", opacity: 0.85, curveness: 0.08 },
          };
        }),
      }],
    };
  }, [rows, names]);
  if (!rows.length) return <Empty title="No connections to draw">Lower the minimum interactions or clear the filters.</Empty>;
  return (
    <EChart option={option} className="chart" ariaLabel="Network graph of wallets connected by repeated transactions"
      onClick={(p) => {
        const d = p.data as { n?: { chain: string; wallet: string } } | undefined;
        if (p.dataType === "node" && d?.n) onOpen(d.n.chain, d.n.wallet);
      }} />
  );
}

/** Wallets with the most distinct partners among the pairs shown. */
function TopHubs({ rows, names, run }: { rows: PairRow[]; names: Names; run?: number }) {
  const hubs = useMemo(() => {
    const m = new Map<string, { chain: string; wallet: string; partners: number; txs: number; tags: string[] }>();
    const add = (chain: string, wallet: string, txs: number, tags: string[]) => {
      const k = `${chain}|${wallet}`;
      const h = m.get(k) ?? { chain, wallet, partners: 0, txs: 0, tags };
      h.partners += 1;
      h.txs += txs;
      m.set(k, h);
    };
    rows.forEach((r) => { add(r.chain, r.a, r.txs, r.a_info.tags); add(r.chain, r.b, r.txs, r.b_info.tags); });
    return [...m.values()].sort((x, y) => y.partners - x.partners || y.txs - x.txs).slice(0, 9);
  }, [rows]);
  return (
    <Card title="Most connected" hint="partners among top pairs">
      <div className="list">
        {hubs.map((h, i) => (
          <Link key={`${h.chain}-${h.wallet}`} to={`/wallets/${h.chain}/${h.wallet}${run ? `?run=${run}` : ""}`} className="list-row" style={{ color: "inherit", textDecoration: "none" }}>
            <span className="rank">{i + 1}</span>
            <span style={{ minWidth: 0 }}>
              <span className="row" style={{ gap: 8, flexWrap: "nowrap" }}><Coin chainKey={h.chain} /><span className="addr">{shortAddr(h.wallet)}</span></span>
              <span className="meta">{h.tags.map(tagLabel).join(" · ") || names[h.chain]?.name}</span>
            </span>
            <span className="amt">{h.partners} <span className="muted">partners</span><br /><small className="muted">{int(h.txs)} interactions</small></span>
          </Link>
        ))}
        {!hubs.length && <p className="muted">No connected wallets in this selection.</p>}
      </div>
    </Card>
  );
}
