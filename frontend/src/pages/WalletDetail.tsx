import { useMemo, type CSSProperties } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { WalletTx } from "../api/types";
import EChart, { chrome } from "../components/EChart";
import { Card, ChainName, Empty, ErrorNotice, Flow, Severity, TagChips } from "../components/ui";
import { callWord, chainColorVar, chainMap, useChains } from "../lib/chains";
import { coin, gwei, int, parseUtc, pct, shortAddr, shortHash, utcTime } from "../lib/format";

export default function WalletDetail() {
  const { chain = "", address = "" } = useParams();
  const [sp] = useSearchParams();
  const run = Number(sp.get("run")) || undefined;
  const q = useQuery({ queryKey: ["wallet", chain, address, run], queryFn: () => api.wallet(chain, address, run) });
  const { data: chains } = useChains();
  const c = chainMap(chains)[chain];
  const p = q.data?.profile;
  const sym = q.data?.native_symbol ?? c?.native_symbol ?? "";

  return (
    <>
      <p className="sub"><Link to={`/wallets${run ? `?run=${run}` : ""}`}>← Wallets</Link></p>
      <section className="card hero" style={{ "--chain": chainColorVar(chain) } as CSSProperties}>
        <div className="card-head">
          <div className="stack" style={{ gap: 6 }}>
            <ChainName chainKey={chain} name={c?.name} />
            <h1 className="mono" style={{ fontSize: "clamp(15px, 2vw, 20px)", wordBreak: "break-all" }}>{address}</h1>
            {p && <div><TagChips tags={p.tags} /></div>}
          </div>
          <div className="row">
            {p && <span className="row" style={{ gap: 6 }}><span className="muted">Anomaly</span><span className="num" style={{ fontSize: 22, fontWeight: 600 }}>{p.anomaly_score.toFixed(2)}</span><Severity score={p.anomaly_score} z={3} /></span>}
            {q.data?.explorer_url && <a className="btn" href={q.data.explorer_url} target="_blank" rel="noopener noreferrer">Block explorer ↗</a>}
          </div>
        </div>
        {p && (
          <dl className="facts">
            <div><dt>Volume</dt><dd>{coin(p.volume)} {sym}</dd></div>
            <div><dt>Net flow</dt><dd><Flow value={p.net_flow} symbol={sym} /></dd></div>
            <div><dt>Sent / received</dt><dd>{int(p.tx_out)} / {int(p.tx_in)}</dd></div>
            <div><dt>Counterparties</dt><dd>{int(p.uniq_receivers)} out · {int(p.uniq_senders)} in</dd></div>
            <div><dt>Tx per block</dt><dd>{p.tx_per_block.toFixed(2)}</dd></div>
            <div><dt>{q.data?.family === "solana" ? "Program calls" : "Contract calls"}</dt><dd>{p.tx_out ? pct(p.contract_call_ratio) : "–"}</dd></div>
            <div><dt>Avg fee</dt><dd>{gwei(p.avg_gas_gwei)} {q.data?.fee_unit}</dd></div>
            <div><dt>Active (UTC)</dt><dd style={{ fontSize: 13 }}>{utcTime(p.first_seen)} → {utcTime(p.last_seen, false)}</dd></div>
          </dl>
        )}
      </section>
      {q.error && <ErrorNotice error={q.error} title="Could not load this wallet" />}
      {q.data && !p && <Card><Empty title="Not in this analytics run">No activity in run #{q.data.run_id}. Stored transactions are listed below.</Empty></Card>}
      {q.data && q.data.transactions.length > 0 && <FlowChart txs={q.data.transactions} address={address} symbol={sym} />}
      {q.data && q.data.counterparties.length > 0 && (
        <Card title="Top counterparties" hint={`wallets this address transacted with 2+ times · run #${q.data.run_id}`}
          actions={<Link className="btn small" to={`/connections?q=${encodeURIComponent(address)}${run ? `&run=${run}` : ""}`}>See in Connections →</Link>}>
          <div className="scroll">
            <table>
              <thead><tr><th className="txt">Wallet</th><th>Interactions</th><th>Sent to</th><th>Received from</th><th>Value sent</th><th>Value received</th><th className="txt">Last seen (UTC)</th></tr></thead>
              <tbody>
                {q.data.counterparties.map((cp) => (
                  <tr key={cp.wallet}>
                    <td><Link className="mono" to={`/wallets/${chain}/${cp.wallet}${run ? `?run=${run}` : ""}`} title={cp.wallet}>{shortAddr(cp.wallet)}</Link>
                      {cp.sent > 0 && cp.received > 0 && <span className="chip whale" style={{ marginLeft: 8 }} title="money went both ways">⇄ two-way</span>}</td>
                    <td style={{ fontWeight: 600 }}>{int(cp.txs)}</td>
                    <td>{int(cp.sent)}</td>
                    <td>{int(cp.received)}</td>
                    <td><span className={cp.value_sent ? "flow-down" : "muted"}>{coin(cp.value_sent)}</span> <span className="muted">{sym}</span></td>
                    <td><span className={cp.value_received ? "flow-up" : "muted"}>{coin(cp.value_received)}</span> <span className="muted">{sym}</span></td>
                    <td className="txt">{utcTime(cp.last_seen)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
      {q.data && (
        <Card title="Transactions" hint={`latest ${q.data.transactions.length} stored, across all datasets`}>
          <div className="scroll">
            <table>
              <thead>
                <tr><th className="txt">Hash</th><th>Block</th><th className="txt">Time (UTC)</th><th className="txt">Side</th><th className="txt">Counterparty</th><th>Value</th><th>Fee ({q.data.fee_unit})</th><th className="txt">Type</th></tr>
              </thead>
              <tbody>
                {q.data.transactions.map((t) => {
                  const out = t.from_addr === address;
                  const other = out ? t.to_addr : t.from_addr;
                  return (
                    <tr key={t.tx_hash}>
                      <td className="mono" title={t.tx_hash}>{shortHash(t.tx_hash)}</td>
                      <td>{int(t.block_number)}</td>
                      <td className="txt">{utcTime(t.block_time)}</td>
                      <td className="txt"><span className={out ? "flow-down" : "flow-up"} style={{ fontWeight: 700 }}>{out ? "OUT" : "IN"}</span></td>
                      <td className="txt mono" title={other}>
                        {!["contract_creation", "coinbase", ""].includes(other) ? <Link to={`/wallets/${chain}/${other}${run ? `?run=${run}` : ""}`}>{shortAddr(other)}</Link> : other}
                      </td>
                      <td>{t.value_native === 0 ? <span className="muted">0</span>
                        : <span className={out ? "flow-down" : "flow-up"}>{out ? "−" : "+"}{coin(t.value_native)}</span>} <span className="muted">{sym}</span></td>
                      <td>{gwei(t.gas_price_gwei)}</td>
                      <td className="txt">{t.is_contract_call ? callWord(q.data.family) : "Transfer"}</td>
                    </tr>
                  );
                })}
                {q.data.transactions.length === 0 && <tr><td colSpan={8} className="txt muted">No stored transactions for this address.</td></tr>}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </>
  );
}

function FlowChart({ txs, address, symbol }: { txs: WalletTx[]; address: string; symbol: string }) {
  const option = useMemo(() => {
    const c = chrome();
    const sorted = [...txs].sort((a, b) => a.block_number - b.block_number);
    let bal = 0;
    const bars = sorted.map((t) => {
      const v = t.from_addr === address ? -t.value_native : t.value_native;
      bal += v;
      return { time: parseUtc(t.block_time)!.getTime(), v, bal };
    });
    return {
      grid: { left: 8, right: 16, top: 20, bottom: 8, containLabel: true },
      tooltip: { ...c.tooltip, trigger: "axis", valueFormatter: (v: unknown) => (typeof v === "number" ? `${coin(v)} ${symbol}` : String(v)) },
      xAxis: { type: "time", axisLine: c.axisLine, axisTick: { show: false }, axisLabel: { ...c.axisLabel, hideOverlap: true }, splitLine: { show: false } },
      yAxis: { type: "value", axisLabel: { ...c.axisLabel, formatter: (v: number) => coin(v) }, splitLine: c.splitLine },
      series: [
        {
          type: "bar", name: "Transaction", barMaxWidth: 10,
          data: bars.map((b) => ({ value: [b.time, b.v], itemStyle: { color: b.v >= 0 ? c.up : c.down, borderRadius: 2 } })),
        },
        {
          type: "line", name: "Running net flow", step: "end", showSymbol: false,
          lineStyle: { width: 2, color: c.accent, shadowBlur: 10, shadowColor: c.accent },
          data: bars.map((b) => [b.time, b.bal]),
        },
      ],
    };
  }, [txs, address, symbol]);
  return (
    <Card title="Money in and out" hint={`green = received · red = sent · gold = running net flow (${symbol})`}>
      <EChart option={option} className="chart short" ariaLabel="Value received and sent per transaction, with running net flow" />
    </Card>
  );
}
