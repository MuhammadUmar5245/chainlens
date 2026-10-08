import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { scamApi, type Trace } from "../api/scam";
import EChart, { chrome } from "../components/EChart";
import { Card, ChainName, Coin, Empty, ErrorNotice, TagChips } from "../components/ui";
import { chainColor, chainColorVar, chainMap, useChains } from "../lib/chains";
import { coin, int, shortAddr, shortHash, utcTime } from "../lib/format";
import { LabelChips, SevChip, traceLink } from "./ScamTracing";
import "./scam.css";

export default function WalletTrace() {
  const { chain = "eth", address = "" } = useParams();
  const [sp, setSp] = useSearchParams();
  const navigate = useNavigate();
  const depth = Number(sp.get("depth")) || 2;
  const direction = sp.get("direction") || "both";
  const run = Number(sp.get("run")) || undefined;
  const [form, setForm] = useState({ chain, address, depth, direction });
  useEffect(() => setForm({ chain, address, depth, direction }), [chain, address, depth, direction]);
  const { data: chains } = useChains();

  const q = useQuery({ queryKey: ["trace", chain, address, depth, direction, run], enabled: !!address,
    queryFn: () => scamApi.trace(chain, address, { depth, direction, run }) });

  function submit() {
    const a = form.address.trim();
    if (!a) return;
    navigate(`/trace/${form.chain}/${a}?depth=${form.depth}&direction=${form.direction}${run ? `&run=${run}` : ""}`);
  }

  return (
    <>
      <div className="page-head">
        <div className="meta">
          <span className="eyebrow">Wallet trace</span>
          <h1>Follow the money</h1>
          <p className="sub">Who a wallet dealt with, where its money came from and where it went. Built from data loaded into Chainlens.</p>
        </div>
        {q.data && <a className="btn" href={scamApi.traceExportUrl(chain, address, { depth, direction, run })}>Export Excel</a>}
      </div>
      <Card>
        <form className="trace-form" onSubmit={(e) => { e.preventDefault(); submit(); }}>
          <label className="field">Chain
            <select value={form.chain} onChange={(e) => setForm({ ...form, chain: e.target.value })}>
              {(chains ?? []).map((c) => <option key={c.key} value={c.key}>{c.name}</option>)}
            </select>
          </label>
          <label className="field">Wallet address
            <input type="text" value={form.address} placeholder="0x…, bc1… or a Solana address" onChange={(e) => setForm({ ...form, address: e.target.value })} />
          </label>
          <label className="field">Hops
            <select value={form.depth} onChange={(e) => setForm({ ...form, depth: Number(e.target.value) })}>{[1, 2, 3].map((d) => <option key={d}>{d}</option>)}</select>
          </label>
          <label className="field">Direction
            <select value={form.direction} onChange={(e) => setForm({ ...form, direction: e.target.value })}>
              <option value="both">Money in and out</option><option value="in">Where it came from</option><option value="out">Where it went</option>
            </select>
          </label>
          <button className="btn primary" type="submit">Trace</button>
        </form>
      </Card>
      {!address && <Card><Empty title="Enter a wallet to trace">Or open any wallet and press "Trace".</Empty></Card>}
      {q.isLoading && <p className="muted">Tracing…</p>}
      {q.error && <ErrorNotice error={q.error} title="Could not trace this wallet" />}
      {q.data && <Result t={q.data} names={chainMap(chains)} run={run} setDir={(d) => { sp.set("direction", d); setSp(sp); }} />}
    </>
  );
}

function Result({ t, names, run }: { t: Trace; names: ReturnType<typeof chainMap>; run?: number; setDir: (d: string) => void }) {
  const p = t.profile;
  const sym = names[t.chain]?.native_symbol ?? "";
  if (!p.transactions) {
    return <Card><Empty title="No transactions for this wallet">It has no activity in the data loaded into Chainlens for {names[t.chain]?.name ?? t.chain}.</Empty></Card>;
  }
  return (
    <>
      <div className="indicator-note" role="note"><b>Indicators, not proof.</b><span>{t.note.replace(/^Indicators, not proof\.\s*/, "")}</span></div>
      <section className="card hero" style={{ "--chain": chainColorVar(t.chain) } as CSSProperties}>
        <div className="card-head">
          <div className="stack" style={{ gap: 6 }}>
            <ChainName chainKey={t.chain} name={names[t.chain]?.name} />
            <h1 className="mono" style={{ fontSize: "clamp(14px, 2vw, 19px)", wordBreak: "break-all" }}>{t.address}</h1>
            <div><LabelChips labels={p.labels} /><TagChips tags={p.tags} /></div>
          </div>
          <div className="row">
            {p.risk ? <span className="row" style={{ gap: 6 }}><span className="muted">Risk</span><b className="num" style={{ fontSize: 24 }}>{p.risk.score}</b><SevChip s={p.risk.severity} /></span>
              : <span className="muted">No risk findings</span>}
            <Link className="btn" to={`/wallets/${t.chain}/${t.address}${run ? `?run=${run}` : ""}`}>Wallet profile</Link>
          </div>
        </div>
        <dl className="facts">
          <div><dt>Active (UTC)</dt><dd style={{ fontSize: 13 }}>{utcTime(p.first_seen)} → {utcTime(p.last_seen)}</dd></div>
          <div><dt>Transactions</dt><dd>{int(p.transactions)} <small className="muted">{int(p.sent)} out · {int(p.received)} in</small></dd></div>
          <div><dt>{sym} in / out</dt><dd><span className="flow-up">{coin(p.native_in)}</span> / <span className="flow-down">{coin(p.native_out)}</span></dd></div>
          <div><dt>Behaviour</dt><dd>{p.behaviour} <small className="muted">{p.active_hours} active hours</small></dd></div>
          <div><dt>Anomaly score</dt><dd>{p.anomaly_score == null ? "–" : p.anomaly_score.toFixed(2)}</dd></div>
          <div><dt>Tokens</dt><dd style={{ fontSize: 13 }}>{p.tokens.length ? p.tokens.slice(0, 3).map((x) => `${x.symbol} ${int(x.transfers)}`).join(" · ") : "–"}</dd></div>
        </dl>
      </section>

      <div className="grid cols-2">
        <Card title="First funder" hint="the first address that sent it value">
          {t.first_funder ? (
            <div className="stack" style={{ gap: 6 }}>
              <span className="row"><Coin chainKey={t.chain} /><Link className="mono" to={traceLink(t.chain, t.first_funder.funder, run)}>{t.first_funder.funder}</Link></span>
              <LabelChips labels={t.first_funder.labels} />
              <span className="sub">{coin(t.first_funder.amount)} {t.first_funder.asset === "native" ? sym : t.first_funder.asset} · block {int(t.first_funder.block)} · {utcTime(t.first_funder.time)} UTC
                · <span className="mono">{shortHash(t.first_funder.tx_hash)}</span></span>
            </div>
          ) : <p className="muted">No incoming value in the loaded data.</p>}
        </Card>
        <Card title="Exit points" hint="labelled exchange, bridge or mixer reached by outgoing money">
          {t.exit_points.length ? (
            <div className="list">
              {t.exit_points.map((x) => (
                <div key={x.address} className="list-row" style={{ gridTemplateColumns: "1fr auto" }}>
                  <span><Link className="mono exit" to={traceLink(t.chain, x.address, run)}>{shortAddr(x.address)}</Link> <LabelChips labels={x.labels} />
                    <div className="meta">via {shortAddr(x.via)}</div></span>
                  <span className="amt">{coin(x.amount)} {x.asset === "native" ? sym : x.asset}</span>
                </div>
              ))}
            </div>
          ) : <p className="muted">No labelled exit reached within {t.depth} hops. Exits only show for addresses you have labelled (Scam tracing → Labels).</p>}
        </Card>
      </div>

      <Card title="Money flow" className="grow"
        hint={`${int(t.graph.nodes.length)} wallets · ${int(t.graph.edges.length)} flows · ${t.depth} hops${t.truncated ? ` · stopped at ${t.limits.max_nodes} wallets` : ""}`}>
        <FlowGraph t={t} run={run} />
        <p className="sub">Gold = this wallet · red ring = high risk · square = hub (exchange, contract or {">"}{t.limits.hub_degree_limit} counterparties), shown but not followed · click to trace that wallet.</p>
      </Card>

      <div className="grid cols-2">
        <Card title="Counterparties" hint={`${t.counterparties.length} shown`}>
          <div className="scroll">
            <table>
              <thead><tr><th className="txt">Wallet</th><th className="txt">Side</th><th>Txs</th><th>{sym}</th><th className="txt">Last (UTC)</th></tr></thead>
              <tbody>
                {t.counterparties.map((c) => (
                  <tr key={c.other}>
                    <td><Link className="mono" to={traceLink(t.chain, c.other, run)}>{shortAddr(c.other)}</Link> <LabelChips labels={c.labels} /></td>
                    <td className="txt">{c.direction === "both" ? "⇄ both" : c.direction === "out" ? "→ sent to" : "← received from"}</td>
                    <td>{int(c.transactions)}</td>
                    <td>{coin(c.native_amount)}</td>
                    <td className="txt">{utcTime(c.last)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
        <Card title="Findings involving this wallet" hint={`${t.findings.length}`}>
          {t.findings.length ? (
            <div className="list">
              {t.findings.slice(0, 30).map((f, i) => (
                <div key={i} className="list-row" style={{ gridTemplateColumns: "auto 1fr" }}>
                  <SevChip s={f.severity} />
                  <span style={{ fontSize: 13 }}><span className="mono muted">{f.detector}</span> {f.reason}
                    {f.wallet !== t.address && <span className="muted"> (finding on {shortAddr(f.wallet)})</span>}</span>
                </div>
              ))}
            </div>
          ) : <p className="muted">No findings in run {t.run_id ?? "–"}.</p>}
        </Card>
      </div>

      <Card title="Timeline" hint={`${t.timeline.length} transfers in and out`}>
        <Timeline t={t} sym={sym} />
        <div className="scroll" style={{ maxHeight: 360 }}>
          <table>
            <thead><tr><th className="txt">Time (UTC)</th><th>Block</th><th className="txt">Side</th><th className="txt">Counterparty</th><th>Amount</th><th className="txt">Tx</th></tr></thead>
            <tbody>
              {t.timeline.slice(0, 200).map((x, i) => (
                <tr key={i}>
                  <td className="txt">{utcTime(x.time)}</td>
                  <td>{int(x.block)}</td>
                  <td className="txt"><b className={x.direction === "in" ? "flow-up" : "flow-down"}>{x.direction.toUpperCase()}</b></td>
                  <td><Link className="mono" to={traceLink(t.chain, x.counterparty, run)}>{shortAddr(x.counterparty)}</Link></td>
                  <td>{coin(x.amount)} <span className="muted">{x.asset === "native" ? sym : x.asset}</span></td>
                  <td className="txt mono">{shortHash(x.tx_hash)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}

function FlowGraph({ t, run }: { t: Trace; run?: number }) {
  const navigate = useNavigate();
  const option = useMemo(() => {
    const c = chrome();
    const col = chainColor(t.chain);
    const maxAmt = Math.max(1e-9, ...t.graph.edges.map((e) => e.amount));
    const labelled = new Set(t.graph.nodes.filter((n) => n.level <= 1 || n.exit || n.labels.length).slice(0, 40).map((n) => n.id));
    return {
      tooltip: {
        ...c.tooltip,
        formatter: (p: { dataType: string; data: { n?: Trace["graph"]["nodes"][number]; e?: Trace["graph"]["edges"][number] } }) => {
          if (p.dataType === "node" && p.data.n) {
            const n = p.data.n;
            return `<b>${shortAddr(n.id)}</b> · hop ${n.level}${n.hub ? `<br/>hub: ${n.hub}` : ""}` +
              `${n.labels.length ? `<br/>${n.labels.map((l) => l.label).join("; ")}` : ""}${n.risk ? `<br/>risk ${n.risk.score} (${n.risk.severity})` : ""}`;
          }
          const e = p.data.e!;
          return `${shortAddr(e.source)} → ${shortAddr(e.target)}<br/><b>${coin(e.amount)} ${e.asset === "native" ? "" : e.asset}</b> in ${e.count} transfer${e.count > 1 ? "s" : ""}`;
        },
      },
      series: [{
        type: "graph", layout: "force", roam: true, draggable: true, edgeSymbol: ["none", "arrow"], edgeSymbolSize: 6,
        force: { repulsion: 120, edgeLength: [30, 120], gravity: 0.1 },
        emphasis: { focus: "adjacency" },
        data: t.graph.nodes.map((n) => {
          const root = n.level === 0;
          const fill = root ? c.accent : n.exit ? c.down : col;
          return {
            id: n.id, name: shortAddr(n.id), n, symbol: n.hub ? "rect" : "circle",
            symbolSize: root ? 26 : n.hub ? 14 : 9 + (n.risk ? n.risk.score / 12 : 0),
            itemStyle: { color: fill, borderColor: n.risk?.severity === "high" ? c.down : fill, borderWidth: n.risk?.severity === "high" ? 3 : 1,
              shadowBlur: root ? 24 : 10, shadowColor: fill, opacity: n.level >= 2 ? 0.85 : 1 },
            label: { show: labelled.has(n.id), color: c.ink, fontSize: 10, fontFamily: "JetBrains Mono, monospace", position: "right" },
          };
        }),
        links: t.graph.edges.map((e) => ({
          source: e.source, target: e.target, e,
          lineStyle: { width: 1 + 4 * Math.sqrt(e.amount / maxAmt), color: e.source === t.address ? c.down : e.target === t.address ? c.up : "rgba(148,163,184,0.45)", curveness: 0.1 },
        })),
      }],
    };
  }, [t]);
  if (!t.graph.edges.length) return <p className="muted">No value transfers to draw.</p>;
  return <EChart option={option} className="chart tall" ariaLabel="Money-flow graph around the traced wallet"
    onClick={(p) => { const d = p.data as { n?: { id: string } }; if (p.dataType === "node" && d?.n) navigate(traceLink(t.chain, d.n.id, run)); }} />;
}

function Timeline({ t, sym }: { t: Trace; sym: string }) {
  const option = useMemo(() => {
    const c = chrome();
    const native = t.timeline.filter((x) => x.asset === "native");
    const pts = (dir: string) => native.filter((x) => x.direction === dir).map((x) => [new Date(x.time.endsWith("Z") ? x.time : x.time + "Z").getTime(), dir === "in" ? x.amount : -x.amount]);
    return {
      grid: { left: 8, right: 16, top: 16, bottom: 8, containLabel: true },
      tooltip: { ...c.tooltip, trigger: "axis", valueFormatter: (v: unknown) => (typeof v === "number" ? `${coin(v)} ${sym}` : String(v)) },
      xAxis: { type: "time", axisLine: c.axisLine, axisLabel: { ...c.axisLabel, hideOverlap: true }, splitLine: { show: false } },
      yAxis: { type: "value", axisLabel: { ...c.axisLabel, formatter: (v: number) => coin(v) }, splitLine: c.splitLine },
      series: [
        { type: "bar", name: "In", data: pts("in"), itemStyle: { color: c.up, borderRadius: 2 }, barMaxWidth: 10 },
        { type: "bar", name: "Out", data: pts("out"), itemStyle: { color: c.down, borderRadius: 2 }, barMaxWidth: 10 },
      ],
    };
  }, [t, sym]);
  if (!t.timeline.some((x) => x.asset === "native")) return null;
  return <EChart option={option} className="chart short" ariaLabel={`Incoming (green) and outgoing (red) ${sym} transfers over time`} />;
}
