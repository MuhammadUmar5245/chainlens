import type { CSSProperties, ReactNode } from "react";
import { ApiError } from "../api/client";
import type { JobStatus } from "../api/types";
import { CHAIN_SHORT, chainColorVar, tagLabel } from "../lib/chains";
import { coin } from "../lib/format";

export function Card({ title, hint, actions, children, className = "", style }: {
  title?: ReactNode; hint?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; style?: CSSProperties;
}) {
  return (
    <section className={`card ${className}`} style={style}>
      {(title || hint || actions) && (
        <div className="card-head">
          <div className="row" style={{ gap: 10 }}>
            {typeof title === "string" ? <h2>{title}</h2> : title}
            {hint && <span className="hint">{hint}</span>}
          </div>
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}
/** Kept for pages that still use the old name. */
export const Panel = ({ title, aside, children, className }: { title?: ReactNode; aside?: ReactNode; children: ReactNode; className?: string }) => (
  <Card title={title} hint={aside} className={className}>{children}</Card>
);

const STATUS_CLASS: Record<string, string> = {
  succeeded: "ok", ready: "ok", running: "run", loading: "run", queued: "idle", pending: "idle",
  cancelling: "warn", cancelled: "idle", failed: "bad",
};
const STATUS_LABEL: Record<string, string> = {
  succeeded: "Done", ready: "Ready", running: "Running", loading: "Loading", queued: "Queued", pending: "Pending",
  cancelling: "Stopping", cancelled: "Cancelled", failed: "Failed",
};
export function Status({ value }: { value: string }) {
  return <span className={`status ${STATUS_CLASS[value] ?? "idle"}`}>{STATUS_LABEL[value] ?? value}</span>;
}

export function Progress({ value, status }: { value: number; status?: JobStatus }) {
  const active = status === "running" || status === "cancelling";
  const indeterminate = active && value <= 0.001;
  return (
    <div className={`progress ${indeterminate ? "indeterminate" : ""}`} role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(value * 100)}>
      <i style={{ width: `${Math.round(Math.min(1, Math.max(0, value)) * 100)}%` }} />
    </div>
  );
}

export function ErrorNotice({ error, title = "Something went wrong" }: { error: unknown; title?: string }) {
  const msg = error instanceof ApiError || error instanceof Error ? error.message : String(error);
  return (
    <div className="notice error" role="alert">
      <strong>{title}</strong>
      <span>{msg}</span>
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <h2>{title}</h2>
      {children}
    </div>
  );
}

export function Coin({ chainKey }: { chainKey: string }) {
  return (
    <span className="coin" style={{ "--chain": chainColorVar(chainKey) } as CSSProperties} aria-hidden="true">
      {CHAIN_SHORT[chainKey] ?? chainKey.slice(0, 1).toUpperCase()}
    </span>
  );
}

export function ChainName({ chainKey, name }: { chainKey: string; name?: string }) {
  return (
    <span className="chain-name">
      <Coin chainKey={chainKey} />
      {name ?? chainKey}
    </span>
  );
}

export function TagChips({ tags }: { tags: string[] }) {
  if (!tags.length) return <span className="muted">–</span>;
  return (
    <>
      {tags.map((t) => (
        <span className={`chip ${t}`} key={t}>{tagLabel(t)}</span>
      ))}
    </>
  );
}

export function Severity({ score, z }: { score: number; z: number }) {
  if (score >= 2 * z) return <span className="sev critical" title={`score ≥ ${2 * z}`}>▲ Extreme</span>;
  if (score >= z) return <span className="sev serious" title={`score ≥ ${z}`}>▲ Unusual</span>;
  return null;
}

/** Signed amount in exchange colours: green in, red out. */
export function Flow({ value, symbol }: { value: number; symbol?: string }) {
  const cls = value > 0 ? "flow-up" : value < 0 ? "flow-down" : "muted";
  return <span className={cls}>{value > 0 ? "+" : ""}{coin(value)}{symbol ? ` ${symbol}` : ""}</span>;
}
