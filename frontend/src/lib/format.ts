const nf = new Intl.NumberFormat("en-US");

/** ClickHouse may return times without an offset; they are always UTC. */
export function parseUtc(s: string | null | undefined): Date | null {
  if (!s) return null;
  const hasZone = /[zZ]|[+-]\d\d:?\d\d$/.test(s);
  const d = new Date(hasZone ? s : s.replace(" ", "T") + "Z");
  return Number.isNaN(d.getTime()) ? null : d;
}

export const int = (n: number | null | undefined) => (n == null ? "–" : nf.format(Math.round(n)));

export function compact(n: number): string {
  const a = Math.abs(n);
  if (a >= 1e9) return `${+(n / 1e9).toFixed(1)}B`;
  if (a >= 1e6) return `${+(n / 1e6).toFixed(1)}M`;
  if (a >= 1e4) return `${+(n / 1e3).toFixed(1)}k`;
  return int(n);
}

/** Native-coin amounts: whole numbers when large, 2 decimals in the middle, 2 significant digits when tiny. */
export function coin(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "–";
  const a = Math.abs(n);
  if (a === 0) return "0";
  if (a >= 1000) return nf.format(Math.round(n));
  if (a >= 1) return n.toFixed(2);
  return n.toPrecision(2);
}

export const signedCoin = (n: number) => (n > 0 ? "+" : "") + coin(n);
export const pct = (n: number | null | undefined) => (n == null ? "–" : `${Math.round(n * 100)}%`);
export const gwei = (n: number | null | undefined) => (n == null ? "–" : n >= 100 ? n.toFixed(0) : n >= 1 ? n.toFixed(2) : n.toFixed(3));
export const shortAddr = (a: string) => (a.length > 16 ? `${a.slice(0, 8)}…${a.slice(-6)}` : a);
export const shortHash = (h: string) => (h.length > 20 ? `${h.slice(0, 10)}…${h.slice(-6)}` : h);

export function utcTime(s: string | null | undefined, withDate = true): string {
  const d = parseUtc(s);
  if (!d) return "–";
  const iso = d.toISOString();
  return withDate ? `${iso.slice(0, 10)} ${iso.slice(11, 16)}` : iso.slice(11, 16);
}

export function duration(seconds: number): string {
  if (seconds < 90) return `${Math.round(seconds)} s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min`;
  if (seconds < 172800) return `${+(seconds / 3600).toFixed(1)} hours`;
  return `${+(seconds / 86400).toFixed(1)} days`;
}

export function bytes(n: number): string {
  if (n >= 1024 ** 3) return `${(n / 1024 ** 3).toFixed(2)} GB`;
  if (n >= 1024 ** 2) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(n / 1024))} KB`;
}

export function bucketLabel(seconds: number): string {
  if (seconds < 3600) return `${seconds / 60}-minute`;
  if (seconds < 86400) return `${seconds / 3600}-hour`;
  return "daily";
}
