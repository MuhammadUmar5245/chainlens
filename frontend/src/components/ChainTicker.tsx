import type { CSSProperties } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { ChainSummary } from "../api/types";
import { chainColorVar, chainMap, useChains } from "../lib/chains";
import { useFilters } from "../lib/filters";
import { compact, int, utcTime } from "../lib/format";
import { Coin } from "./ui";

/** Exchange-style chain strip: one tile per chain with its live numbers. Selection lives in the URL. */
export default function ChainTicker({ runChains, stats }: { runChains?: string[]; stats?: ChainSummary[] }) {
  const { chains, set } = useFilters();
  const { data: all } = useChains();
  const available = new Set(runChains ?? []);
  const selected = new Set(chains ?? runChains ?? []);
  const allSelected = !chains;
  const byChain = Object.fromEntries((stats ?? []).map((s) => [s.chain, s]));

  function toggle(key: string) {
    const next = new Set(selected);
    if (allSelected) {
      next.clear();
      next.add(key);                           // from "all": jump straight to one chain
    } else if (next.has(key)) next.delete(key);
    else next.add(key);
    const list = (runChains ?? []).filter((c) => next.has(c));
    set({ chains: list.length === 0 || list.length === (runChains ?? []).length ? undefined : list });
  }

  return (
    <div className="ticker" role="group" aria-label="Chains">
      <button type="button" className="tick all" aria-pressed={allSelected} onClick={() => set({ chains: undefined })}>
        <span className="name">All chains</span>
        <span className="stats"><span>{available.size} with data</span></span>
      </button>
      {(all ?? []).map((c) => {
        const s = byChain[c.key];
        return (
          <button key={c.key} type="button" className="tick" disabled={!available.has(c.key)}
            aria-pressed={!allSelected && selected.has(c.key)}
            style={{ "--chain": chainColorVar(c.key) } as CSSProperties}
            title={available.has(c.key) ? `Show ${c.name}` : `${c.name}: no data in this analytics run`}
            onClick={() => toggle(c.key)}>
            <span className="name"><Coin chainKey={c.key} />{c.name}</span>
            <span className="stats">
              {available.has(c.key)
                ? <>{s ? <><span><b>{compact(s.transactions)}</b> txs</span><span><b>{int(s.anomalies)}</b> alerts</span></> : <span>selected run</span>}</>
                : <span>no data yet</span>}
            </span>
          </button>
        );
      })}
    </div>
  );
}

export function RunSelect() {
  const { run, set } = useFilters();
  const { data: runs } = useQuery({ queryKey: ["runs"], queryFn: api.runs });
  const { data: chains } = useChains();
  const byKey = chainMap(chains);
  const finished = (runs ?? []).filter((r) => r.status === "succeeded");
  return (
    <select aria-label="Analytics run" value={run ?? ""} onChange={(e) => set({ run: e.target.value || undefined, chains: undefined })}>
      <option value="">Latest analytics run</option>
      {finished.map((r) => (
        <option key={r.id} value={r.id}>
          Run #{r.id} · {r.chains.map((k) => byKey[k]?.name ?? k).join(", ")} · {utcTime(r.created_at)}
        </option>
      ))}
    </select>
  );
}
