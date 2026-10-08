import { useId } from "react";

/** Small area sparkline for KPI cards: gradient fill, 2px line, emphasised end point. */
export default function Sparkline({ values, color = "var(--accent)", width = 220, height = 38 }: {
  values: number[];
  color?: string;
  width?: number;
  height?: number;
}) {
  const id = useId().replace(/:/g, "");
  if (values.length < 2) return <svg width="100%" height={height} aria-hidden="true" />;
  const max = Math.max(...values), min = Math.min(...values, 0);
  const span = max - min || 1;
  const pad = 4;
  const x = (i: number) => (i / (values.length - 1)) * width;
  const y = (v: number) => pad + (1 - (v - min) / span) * (height - pad * 2);
  const line = values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const area = `${line}L${width},${height}L0,${height}Z`;
  const last = values[values.length - 1];
  return (
    <svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-hidden="true">
      <defs>
        <linearGradient id={`g${id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.35" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#g${id})`} />
      <path d={line} fill="none" stroke={color} strokeWidth="2" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
      <circle cx={x(values.length - 1)} cy={y(last)} r="3" fill={color} />
    </svg>
  );
}
