import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Chain } from "../api/types";
import { ChainName, ErrorNotice, Panel } from "../components/ui";
import { useChains } from "../lib/chains";

export default function Settings() {
  const { data: chains, error } = useChains();
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 15_000 });
  const h = health.data;

  return (
    <>
      <div className="page-head">
        <div className="meta">
          <h1>Settings</h1>
          <p className="sub">Chain endpoints and limits, and the state of the backend services.</p>
        </div>
      </div>

      <Panel title="Backend">
        {health.error ? <ErrorNotice error={health.error} title="The API is not reachable" /> : (
          <dl className="facts">
            <div><dt>PostgreSQL</dt><dd><Health value={h?.postgres} /></dd></div>
            <div><dt>ClickHouse</dt><dd><Health value={h?.clickhouse} /></dd></div>
            <div><dt>NOWNodes key</dt><dd>{h ? (h.nownodes_key ? <span className="status ok">Set</span> : <span className="status bad">Missing</span>) : "…"}</dd></div>
            <div><dt>History kept</dt><dd>{h ? `${h.history_days} days` : "…"}</dd></div>
          </dl>
        )}
        <p className="sub">Keys and database passwords are set in the server's .env file and are never sent to the browser.</p>
      </Panel>

      <Panel title="Chains">
        {error && <ErrorNotice error={error} />}
        <div className="scroll">
          <table>
            <thead>
              <tr><th>Chain</th><th className="txt">Endpoint</th><th>Whale threshold</th><th>Requests / s</th><th>Workers</th><th className="txt">Enabled</th><th className="txt">Live sync</th><th /></tr>
            </thead>
            <tbody>{(chains ?? []).map((c) => <ChainRow key={c.key} chain={c} />)}</tbody>
          </table>
        </div>
        <p className="sub">
          Live sync fetches new blocks every minute for that chain and keeps them for the history period. Fast chains make
          many API calls: Arbitrum produces about 4 blocks per second.
        </p>
      </Panel>
    </>
  );
}

function Health({ value }: { value?: string }) {
  if (!value) return <>…</>;
  return value === "ok" ? <span className="status ok">Connected</span> : <span className="status bad" title={value}>Error</span>;
}

function ChainRow({ chain }: { chain: Chain }) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState({ ...chain });
  const dirty = (["rpc_url", "whale_threshold", "rate_limit_rps", "workers", "enabled", "autosync"] as const)
    .some((k) => draft[k] !== chain[k]);
  const save = useMutation({
    mutationFn: () => api.updateChain(chain.key, {
      rpc_url: draft.rpc_url, whale_threshold: draft.whale_threshold, rate_limit_rps: draft.rate_limit_rps,
      workers: draft.workers, enabled: draft.enabled, autosync: draft.autosync,
    }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["chains"] }),
  });
  return (
    <>
      <tr>
        <td><ChainName chainKey={chain.key} name={chain.name} /></td>
        <td className="txt"><input type="text" aria-label={`${chain.name} endpoint`} value={draft.rpc_url} style={{ width: 230 }}
          onChange={(e) => setDraft({ ...draft, rpc_url: e.target.value })} /></td>
        <td><input type="number" aria-label={`${chain.name} whale threshold`} min={0} value={draft.whale_threshold} style={{ width: 120 }}
          onChange={(e) => setDraft({ ...draft, whale_threshold: Number(e.target.value) })} /> <span className="muted">{chain.native_symbol}</span></td>
        <td><input type="number" aria-label={`${chain.name} requests per second`} min={0.1} step={0.1} value={draft.rate_limit_rps} style={{ width: 80 }}
          onChange={(e) => setDraft({ ...draft, rate_limit_rps: Number(e.target.value) })} /></td>
        <td><input type="number" aria-label={`${chain.name} workers`} min={1} max={64} value={draft.workers} style={{ width: 70 }}
          onChange={(e) => setDraft({ ...draft, workers: Number(e.target.value) })} /></td>
        <td className="txt"><input type="checkbox" aria-label={`${chain.name} enabled`} checked={draft.enabled} onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })} /></td>
        <td className="txt"><input type="checkbox" aria-label={`${chain.name} live sync`} checked={draft.autosync} onChange={(e) => setDraft({ ...draft, autosync: e.target.checked })} /></td>
        <td><button className="btn small primary" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>{save.isPending ? "Saving…" : "Save"}</button></td>
      </tr>
      {save.error && <tr><td colSpan={8}><ErrorNotice error={save.error} title={`Could not save ${chain.name}`} /></td></tr>}
    </>
  );
}
