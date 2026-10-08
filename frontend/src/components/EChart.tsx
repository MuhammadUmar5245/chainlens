import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { BarChart, GraphChart, LineChart, ScatterChart } from "echarts/charts";
import { GridComponent, MarkLineComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsCoreOption } from "echarts/core";
import { cssVar } from "../lib/theme";

echarts.use([LineChart, BarChart, ScatterChart, GraphChart, GridComponent, TooltipComponent, MarkLineComponent, CanvasRenderer]);

/** Shared chart chrome so every chart reads as one system. */
export function chrome() {
  const muted = cssVar("--muted"), grid = cssVar("--grid"), axis = cssVar("--axis"), ink = cssVar("--ink");
  return {
    muted, grid, axis, ink,
    accent: cssVar("--accent"), accent2: cssVar("--accent-2"), up: cssVar("--up"), down: cssVar("--down"),
    card: cssVar("--card-2"),
    tooltip: {
      backgroundColor: "rgba(14, 18, 26, 0.96)",
      borderColor: "rgba(148, 163, 184, 0.2)",
      textStyle: { color: ink, fontSize: 12, fontFamily: "Manrope, system-ui, sans-serif" },
      extraCssText: "border-radius:10px;box-shadow:0 10px 30px rgba(0,0,0,.45);",
    },
    axisLabel: { color: muted, fontSize: 11, fontFamily: "JetBrains Mono, monospace" },
    splitLine: { lineStyle: { color: grid } },
    axisLine: { lineStyle: { color: axis } },
  };
}

export default function EChart({ option, className = "chart", ariaLabel, onClick }: {
  option: EChartsCoreOption;
  className?: string;
  ariaLabel: string;
  onClick?: (params: { dataType?: string; data?: unknown }) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  const clickRef = useRef(onClick);
  clickRef.current = onClick;

  useEffect(() => {
    if (!ref.current) return;
    chart.current = echarts.init(ref.current, undefined, { renderer: "canvas" });
    chart.current.on("click", (p) => clickRef.current?.(p as { dataType?: string; data?: unknown }));
    const ro = new ResizeObserver(() => chart.current?.resize());
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      chart.current?.dispose();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    chart.current?.setOption({ animationDuration: 500, useUTC: true, ...option }, { notMerge: true });
  }, [option]);

  return <div ref={ref} className={className} role="img" aria-label={ariaLabel} />;
}
