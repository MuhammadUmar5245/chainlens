import { useMemo, useState, type CSSProperties } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ApiError, api, type AnalyticsFilter } from "../api/client";
import type { Chain, ChainSummary, ClusterRow, SeriesResponse, Summary, TagRow } from "../api/types";
import ChainTicker, { RunSelect } from "../components/ChainTicker";
import EChart, { chrome } from "../components/EChart";
import Sparkline from "../components/Sparkline";
import { Card, ChainName, Coin, Empty, ErrorNotice, Flow } from "../components/ui";
import { TAGS, chainColor, chainColorVar, chainMap, tagLabel, useChains } from "../lib/chains";
import { useFilters } from "../lib/filters";
import { bucketLabel, coin, compact, gwei, int, parseUtc, pct, shortAddr, utcTime } from "../lib/format";

export default function Overview() {
  const { run, chains } = useFilters();
  const f: AnalyticsFilter = { run, chains };
  const summary = useQuery({ queryKey: ["summary", f], queryFn: () => api.summary(f), retry: false });

  if (summary.error instanceof ApiError && summary.error.status === 404) {
    return (
      <>
        <Head />
        <Card>
          <Empty title="No analytics yet">
            <p>Fetch blocks from NOWNodes or upload a data dump. Analytics start automatically once the data is in.</p>
            <Link className="btn primary" to="/data">Add data</Link>
          </Empty>
        </Card>
      </>
    );
  }
  if (summary.error) return (<><Head /><ErrorNotice error={summary.error} title="Could not load the overview" /></>);
  if (!summary.data) return (<><Head /><p className="muted">Loading market view…</p></>);
  return <Loaded s={summary.data} f={f} />;
}

function Head({ s }: { s?: Summary }) {
  const t = s?.totals;
  return (
    <div className="page-head">
      <div className="meta">
        <span className="eyebrow">On-chain behaviour</span>
        <h1>Market overview</h1>
        {t && <p className="sub">Run #{s!.run.id} · {utcTime(t.time_from)} → {utcTime(t.time_to, false)} UTC · {int(t.blocks)} blocks</p>}
      </div>
      <RunSelect />
    </div>
  );
}

function Loaded({ s, f }: { s: Summary; f: AnalyticsFilter }) {
  const series = useQuery({ queryKey: ["series", f], queryFn: () => api.series(f) });
  const { data: chainList } = useChains();
  const byKey = chainMap(chainList);
  const t = s.totals;
  const single = s.per_chain.length === 1 ? s.per_chain[0] : undefined;
  const contractShare = t.transactions ? s.per_chain.reduce((a, c) => a + c.contract_share * c.transactions, 0) / t.transactions : 0;

  const sum = useMemo(() => totalsByBucket(series.data), [series.data]);
  const kpis: { label: string; value: string; note: string; spark?: number[]; hot?: boolean }[] = [
    { label: "Transactions", value: compact(t.transactions), note: `${int(t.transactions)} in ${int(t.blocks)} blocks`, spark: sum.txs },
    { label: "Active wallets", value: compact(t.wallets), note: "unique senders + receivers" },
    { label: "Alerts", value: int(t.anomalies), note: `${pct(t.wallets ? t.anomalies / t.wallets : 0)} of wallets flagged`, hot: t.anomalies > 0 },
    single
      ? { label: `Value moved`, value: `${coin(single.value)}`, note: byKey[single.chain]?.native_symbol ?? "", spark: sum.value }
      : { label: "Blocks", value: compact(t.blocks), note: `${s.chains.length} chains`, spark: sum.blocks },
    { label: "Contract calls", value: pct(contractShare), note: "share of all transactions", spark: sum.contract },
  ];

  return (
    <>
      <Head s={s} />
      <ChainTicker runChains={s.run.chains} stats={s.per_chain} />
      {s.chains.length === 0 ? <Card><Empty title="No chains selected">Pick a chain above.</Empty></Card> : (
        <>
          <section className="kpis" aria-label="Totals">
            {kpis.map((k) => (
              <div key={k.label} className={`card kpi ${k.hot ? "hot" : ""}`}>
                <span className="label">{k.label}</span>
                <span className="value">{k.value}</span>
                <span className="note">{k.note}</span>
                {k.spark && <Sparkline values={k.spark} />}
              </div>
            ))}
          </section>

          <div className="grid cols-main">
            {series.error ? <ErrorNotice error={series.error} title="Could not load activity" />
              : series.data ? <ActivityCard data={series.data} names={byKey} /> : <Card><p className="muted">Loading chart…</p></Card>}
            <WhaleWatch f={f} names={byKey} />
          </div>

          <div className="grid cols-3">
            <TagsCard f={f} chains={s.chains} />
            <DistributionCard f={f} />
            <ContractCard perChain={s.per_chain} names={byKey} />
          </div>

          <GroupsCard f={f} names={byKey} />

          <div className="grid cols-2">
            <FlowCard f={f} names={byKey} direction="in" />
            <FlowCard f={f} names={byKey} direction="out" />
          </div>
        </>
      )}
    </>
  );
}

function totalsByBucket(data?: SeriesResponse) {
  const m = new Map<string, { txs: number; blocks: number; value: number; contract: number }>();
  for (const s of data?.series ?? []) {
    for (const p of s.points) {
      const e = m.get(p.t) ?? { txs: 0, blocks: 0, value: 0, contract: 0 };
      e.txs += p.txs; e.blocks += p.blocks; e.value += p.value; e.contract += p.contract_share * p.txs;
      m.set(p.t, e);
    }
  }
  const rows = [...m.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([, v]) => v);
  return {
    txs: rows.map((r) => r.txs), blocks: rows.map((r) => r.blocks), value: rows.map((r) => r.value),
    contract: rows.map((r) => (r.txs ? r.contract / r.txs : 0)),
  };
}

type Names = Record<string, Chain>;

/* ---------- main activity chart ---------- */
function ActivityCard({ data, names }: { data: SeriesResponse; names: Names }) {
  const [metric, setMetric] = useState<"txs" | "value" | "gas">("txs");
  const withData = data.series.filter((s) => s.points.length);
  const [focus, setFocus] = useState<string>();
  const one = withData.find((s) => s.chain === focus) ?? withData[0];

  const option = useMemo(() => {
    const c = chrome();
    const shown = metric === "txs" ? withData : one ? [one] : [];
    const fmt = metric === "txs" ? compact : metric === "value" ? coin : gwei;
    return {
      grid: { left: 8, right: 16, top: 16, bottom: 8, containLabel: true },
      tooltip: { ...c.tooltip, trigger: "axis", valueFormatter: (v: unknown) => (typeof v === "number" ? fmt(v) : String(v)) },
      xAxis: { type: "time", axisLine: c.axisLine, axisTick: { show: false }, axisLabel: { ...c.axisLabel, hideOverlap: true }, splitLine: { show: false } },
      yAxis: { type: "value", axisLabel: { ...c.axisLabel, formatter: (v: number) => fmt(v) }, splitLine: c.splitLine },
      series: shown.map((s) => {
        const col = chainColor(s.chain);
        // samples can be hours apart: break the line where buckets are missing instead of drawing a ramp across
        const gap = data.bucket_seconds * 1000 * 2.5;
        const pts: [number, number | null][] = [];
        s.points.forEach((p, i) => {
          const t = parseUtc(p.t)!.getTime();
          if (i > 0 && t - pts[pts.length - 1][0] > gap) pts.push([t - 1, null]);
          pts.push([t, metric === "txs" ? p.txs : metric === "value" ? p.value : p.median_gas]);
        });
        return {
          type: "line", name: names[s.chain]?.name ?? s.chain, showSymbol: s.points.length < 60, symbolSize: 5,
          lineStyle: { width: 2, color: col, shadowColor: col, shadowBlur: 10 },
          itemStyle: { color: col },
          areaStyle: metric === "gas" ? undefined : {
            color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: col + "55" }, { offset: 1, color: col + "00" }] },
          },
          data: pts,
        };
      }),
    };
  }, [metric, withData, one, names, data.bucket_seconds]);

  const title = metric === "txs" ? "Transactions" : metric === "value" ? `Value moved${one ? ` (${names[one.chain]?.native_symbol ?? ""})` : ""}` : `Median fee${one ? ` (${names[one.chain]?.fee_unit ?? ""})` : ""}`;
  return (
    <Card title={title} hint={`${bucketLabel(data.bucket_seconds)} buckets · UTC`} className="grow"
      actions={
        <div className="row">
          {metric !== "txs" && withData.length > 1 && (
            <div className="tabs" role="group" aria-label="Chain">
              {withData.map((s) => (
                <button key={s.chain} type="button" aria-pressed={s.chain === one?.chain} onClick={() => setFocus(s.chain)}>{names[s.chain]?.name ?? s.chain}</button>
              ))}
            </div>
          )}
          <div className="tabs" role="group" aria-label="Metric">
            {(["txs", "value", "gas"] as const).map((m) => (
              <button key={m} type="button" aria-pressed={metric === m} onClick={() => setMetric(m)}>
                {m === "txs" ? "Transactions" : m === "value" ? "Value" : "Fees"}
              </button>
            ))}
          </div>
        </div>
      }>
      {metric === "txs" && withData.length > 1 && (
        <div className="legend">{withData.map((s) => <ChainName key={s.chain} chainKey={s.chain} name={names[s.chain]?.name} />)}</div>
      )}
      <EChart option={option} className="chart" ariaLabel={`${title} over time`} />
    </Card>
  );
}

/* ---------- whale watch ---------- */
function WhaleWatch({ f, names }: { f: AnalyticsFilter; names: Names }) {
  const q = useQuery({ queryKey: ["whales", f], queryFn: () => api.wallets({ ...f, sort: "volume", limit: 8 }) });
  const rows = q.data?.rows ?? [];
  const max = Math.max(1, ...rows.map((r) => r.volume));
  return (
    <Card title="Whale watch" hint="largest volume" actions={<Link className="btn small" to="/wallets">All wallets →</Link>}>
      {q.error && <ErrorNotice error={q.error} />}
      <div className="list">
        {rows.map((w, i) => (
          <Link key={`${w.chain}-${w.wallet}`} to={`/wallets/${w.chain}/${w.wallet}`} className="list-row" style={{ color: "inherit", textDecoration: "none" }}>
            <span className="rank">{i + 1}</span>
            <span style={{ minWidth: 0 }}>
              <span className="row" style={{ gap: 8, flexWrap: "nowrap" }}><Coin chainKey={w.chain} /><span className="addr">{shortAddr(w.wallet)}</span></span>
              <span className="meta">{w.tags.map(tagLabel).join(" · ") || "no tags"}</span>
              <div className="flowbar" style={{ width: `${(w.volume / max) * 100}%`, background: `linear-gradient(90deg, ${chainColorVar(w.chain)}, transparent)` }} />
            </span>
            <span className="amt">
              {coin(w.volume)} <span className="muted">{names[w.chain]?.native_symbol}</span>
              <br /><small><Flow value={w.net_flow} /></small>
            </span>
          </Link>
        ))}
        {q.data && rows.length === 0 && <p className="muted">No wallets for this selection.</p>}
      </div>
    </Card>
  );
}

/* ---------- tags ---------- */
function TagsCard({ f, chains }: { f: AnalyticsFilter; chains: string[] }) {
  const q = useQuery({ queryKey: ["tags", f], queryFn: () => api.tags(f) });
  const rows: TagRow[] = q.data?.rows ?? [];
  const totals = Object.keys(TAGS).map((tag) => ({ tag, total: rows.filter((r) => r.tag === tag).reduce((a, r) => a + r.wallets, 0) }))
    .sort((a, b) => b.total - a.total);
  const max = Math.max(1, ...totals.map((t) => t.total));
  return (
    <Card title="Behaviour tags" hint={chains.length > 1 ? "all selected chains" : "wallets per tag"}>
      <div className="stack">
        {totals.map((t) => (
          <div key={t.tag} className="hbar">
            <span style={{ fontWeight: 600 }}>{tagLabel(t.tag)}</span>
            <div className="track"><div className="fill" style={{ width: `${Math.max(1.5, (t.total / max) * 100)}%` }} /></div>
            <span className="v">{compact(t.total)}</span>
            <span className="rule">{TAGS[t.tag].rule}</span>
          </div>
        ))}
      </div>
    </Card>
  );
}

/* ---------- anomaly distribution ---------- */
function DistributionCard({ f }: { f: AnalyticsFilter }) {
  const q = useQuery({ queryKey: ["distribution", f], queryFn: () => api.distribution(f) });
  const option = useMemo(() => {
    if (!q.data) return {};
    const c = chrome();
    const { bin_width: w, bins, threshold } = q.data;
    const counts = Array.from({ length: bins }, () => 0);
    for (const r of q.data.rows) counts[r.bin] += r.wallets;
    return {
      grid: { left: 8, right: 10, top: 18, bottom: 6, containLabel: true },
      tooltip: {
        ...c.tooltip, trigger: "axis", axisPointer: { type: "shadow" },
        formatter: (p: { dataIndex: number; value: number }[]) =>
          `Score ${(p[0].dataIndex * w).toFixed(1)}–${((p[0].dataIndex + 1) * w).toFixed(1)}<br/><b>${int(p[0].value)}</b> wallets`,
      },
      xAxis: { type: "category", data: counts.map((_, i) => (i * w).toFixed(1)), axisLine: c.axisLine, axisTick: { show: false },
        axisLabel: { ...c.axisLabel, interval: Math.ceil(bins / 6) - 1 } },
      yAxis: { type: "log", logBase: 10, min: 1, axisLabel: { ...c.axisLabel, formatter: (v: number) => compact(v) }, splitLine: c.splitLine },
      series: [{
        type: "bar", barCategoryGap: "12%",
        data: counts.map((v, i) => ({
          value: v || null,
          itemStyle: { color: i * w >= threshold ? c.down : c.accent, borderRadius: [3, 3, 0, 0], shadowBlur: i * w >= threshold ? 10 : 0, shadowColor: c.down },
        })),
        markLine: {
          symbol: "none", silent: true, label: { color: c.muted, formatter: `alert ≥ ${threshold}`, fontSize: 11 },
          lineStyle: { color: c.down, type: "dashed" }, data: [{ xAxis: Math.min(bins - 1, Math.floor(threshold / w)) }],
        },
      }],
    };
  }, [q.data]);
  return (
    <Card title="Anomaly scores" hint="wallets per score band · log scale">
      {q.error ? <ErrorNotice error={q.error} /> : <EChart option={option} className="chart short" ariaLabel="Histogram of wallet anomaly scores; bars at or above the alert threshold are red" />}
      <p className="sub"><span className="down">Red</span> bands are at or above the alert threshold.</p>
    </Card>
  );
}

/* ---------- contract vs transfer ---------- */
function ContractCard({ perChain, names }: { perChain: ChainSummary[]; names: Names }) {
  return (
    <Card title="Contract & program calls" hint="share of transactions">
      <div className="stack">
        {perChain.map((c) => (
          <div key={c.chain} style={{ display: "grid", gap: 6 }}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <ChainName chainKey={c.chain} name={names[c.chain]?.name} />
              <span className="num">{names[c.chain]?.family === "utxo" ? <span className="muted">no smart contracts</span> : <>{pct(c.contract_share)} <span className="muted">calls</span></>}</span>
            </div>
            <div style={{ display: "flex", height: 10, borderRadius: 5, overflow: "hidden", background: "var(--chip)", gap: 2 }}>
              <div style={{ width: `${c.contract_share * 100}%`, background: chainColorVar(c.chain), boxShadow: `0 0 12px ${chainColorVar(c.chain)}` }} />
            </div>
            <span className="sub">{int(c.transactions)} txs · median fee {gwei(c.median_gas)} {names[c.chain]?.fee_unit}</span>
          </div>
        ))}
      </div>
    </Card>
  );
}

/* ---------- behaviour groups ---------- */
function nameClusters(rows: ClusterRow[]): Record<number, string> {
  const names: Record<number, string> = {};
  if (rows.length !== 4) return names;
  let rest = [...rows];
  const pick = (score: (c: ClusterRow) => number, label: string) => {
    const best = rest.reduce((a, b) => (score(b) > score(a) ? b : a));
    names[best.cluster] = label;
    rest = rest.filter((c) => c !== best);
  };
  pick((c) => c.avg_volume, "Big movers");
  pick((c) => c.avg_contract, "Contract users");
  pick((c) => c.avg_tx_in - c.avg_tx_out, "Mostly receiving");
  names[rest[0].cluster] = "Simple senders";
  return names;
}

function GroupsCard({ f, names }: { f: AnalyticsFilter; names: Names }) {
  const q = useQuery({ queryKey: ["clusters", f], queryFn: () => api.clusters(f) });
  const rows = q.data?.rows ?? [];
  const labels = useMemo(() => {
    const byChain: Record<string, ClusterRow[]> = {};
    rows.forEach((r) => (byChain[r.chain] ??= []).push(r));
    const out: Record<string, string> = {};
    Object.entries(byChain).forEach(([chain, list]) => {
      const n = nameClusters(list);
      list.forEach((r) => (out[`${chain}-${r.cluster}`] = n[r.cluster] ?? `Group ${r.cluster}`));
    });
    return out;
  }, [rows]);

  const option = useMemo(() => {
    const c = chrome();
    const maxW = Math.max(1, ...rows.map((r) => r.wallets));
    const chainsIn = [...new Set(rows.map((r) => r.chain))];
    return {
      grid: { left: 16, right: 40, top: 48, bottom: 28, containLabel: true },
      tooltip: {
        ...c.tooltip, trigger: "item",
        formatter: (p: { data: { r: ClusterRow; label: string } }) => {
          const r = p.data.r;
          return `<b>${p.data.label}</b> · ${names[r.chain]?.name ?? r.chain}<br/>${int(r.wallets)} wallets<br/>avg sent ${r.avg_tx_out.toFixed(2)} · received ${r.avg_tx_in.toFixed(2)}<br/>avg volume ${coin(r.avg_volume)} ${names[r.chain]?.native_symbol ?? ""}<br/>contract calls ${pct(r.avg_contract)}`;
        },
      },
      xAxis: { type: "log", name: "avg tx sent", nameLocation: "middle", nameGap: 28, nameTextStyle: { color: c.muted }, min: 0.01,
        max: (v: { max: number }) => Math.pow(10, Math.ceil(Math.log10(v.max * 3))),
        axisLabel: c.axisLabel, axisLine: c.axisLine, splitLine: c.splitLine },
      yAxis: { type: "log", name: "avg tx received", nameLocation: "middle", nameGap: 40, nameRotate: 90, nameTextStyle: { color: c.muted },
        min: 0.01, max: (v: { max: number }) => Math.pow(10, Math.ceil(Math.log10(v.max * 3))), axisLabel: c.axisLabel, splitLine: c.splitLine },
      series: chainsIn.map((ch) => {
        const col = chainColor(ch);
        return {
          type: "scatter", name: names[ch]?.name ?? ch,
          data: rows.filter((r) => r.chain === ch).map((r) => ({
            value: [Math.max(r.avg_tx_out, 0.01), Math.max(r.avg_tx_in, 0.01)], r, label: labels[`${ch}-${r.cluster}`],
            symbolSize: 14 + 60 * Math.sqrt(r.wallets / maxW),
          })),
          itemStyle: { color: col + "aa", borderColor: col, borderWidth: 2, shadowBlur: 18, shadowColor: col },
          label: { show: true, position: "top", color: c.ink, fontSize: 11, fontWeight: 600, formatter: (p: { data: { label: string } }) => p.data.label },
        };
      }),
    };
  }, [rows, labels, names]);

  return (
    <div className="grid cols-2">
      <Card title="Behaviour groups" hint="bubble size = wallets · log axes">
        {q.error ? <ErrorNotice error={q.error} /> : <EChart option={option} className="chart tall" ariaLabel="Bubble chart of KMeans behaviour groups by average transactions sent and received" />}
      </Card>
      <Card title="Group profiles" hint="averages per wallet">
        <div className="scroll">
          <table>
            <thead><tr><th className="txt">Group</th><th>Wallets</th><th>Sent</th><th>Recv</th><th>Avg volume</th><th>Contract</th><th>Anomaly</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={`${r.chain}-${r.cluster}`}>
                  <td className="txt"><span className="row" style={{ gap: 8, flexWrap: "nowrap" }}><Coin chainKey={r.chain} />{labels[`${r.chain}-${r.cluster}`]}</span></td>
                  <td>{int(r.wallets)}</td>
                  <td>{r.avg_tx_out.toFixed(2)}</td>
                  <td>{r.avg_tx_in.toFixed(2)}</td>
                  <td>{coin(r.avg_volume)}</td>
                  <td>{pct(r.avg_contract)}</td>
                  <td>{r.avg_anomaly.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="sub">Group names come from each group's averages.</p>
      </Card>
    </div>
  );
}

/* ---------- inflow / outflow leaders ---------- */
function FlowCard({ f, names, direction }: { f: AnalyticsFilter; names: Names; direction: "in" | "out" }) {
  const q = useQuery({
    queryKey: ["flows", direction, f],
    queryFn: () => api.wallets({ ...f, sort: "net_flow", order: direction === "in" ? "desc" : "asc", limit: 7 }),
  });
  const rows = (q.data?.rows ?? []).filter((w) => (direction === "in" ? w.net_flow > 0 : w.net_flow < 0));
  const max = Math.max(1e-9, ...rows.map((w) => Math.abs(w.net_flow)));
  const color = direction === "in" ? "var(--up)" : "var(--down)";
  return (
    <Card title={direction === "in" ? "Biggest net inflows" : "Biggest net outflows"} hint={direction === "in" ? "received minus sent" : "sent minus received"}>
      <div className="list">
        {rows.map((w) => (
          <Link key={`${w.chain}-${w.wallet}`} to={`/wallets/${w.chain}/${w.wallet}`} className="list-row" style={{ color: "inherit", textDecoration: "none" }}>
            <Coin chainKey={w.chain} />
            <span style={{ minWidth: 0 }}>
              <span className="addr">{shortAddr(w.wallet)}</span>
              <div className="flowbar" style={{ width: `${(Math.abs(w.net_flow) / max) * 100}%`, background: color, boxShadow: `0 0 10px ${color}` } as CSSProperties} />
            </span>
            <span className="amt"><Flow value={w.net_flow} symbol={names[w.chain]?.native_symbol} /></span>
          </Link>
        ))}
        {q.data && rows.length === 0 && <p className="muted">No {direction === "in" ? "inflows" : "outflows"} in this selection.</p>}
      </div>
    </Card>
  );
}
