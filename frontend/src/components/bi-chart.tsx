"use client";

import { useEffect, useRef } from "react";
import { BarChart, LineChart, PieChart, ScatterChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import MatrixTable from "@/components/matrix-table";
import { chartOption, plan, type BiResult, type Chart, type ChartPalette } from "@/lib/bi";

// Chi nap dung phan dung toi: cot (ca chong va thac nuoc), duong, tron, phan tan.
echarts.use([BarChart, LineChart, PieChart, ScatterChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);

/** Mau cua bieu do doc tu bien CSS, nen doi theo giao dien Sang/Toi. */
function readPalette(): ChartPalette {
  const style = getComputedStyle(document.documentElement);
  const read = (name: string) => style.getPropertyValue(name).trim();
  return {
    text: read("--chart-text"),
    muted: read("--chart-muted"),
    grid: read("--chart-grid"),
    axis: read("--chart-axis"),
    surface: read("--surface"),
    tooltipBg: read("--tooltip-bg"),
    tooltipText: read("--tooltip-text"),
    tooltipBorder: read("--tooltip-border"),
    series: [1, 2, 3, 4, 5, 6, 7, 8].map((slot) => read(`--series-${slot}`)),
  };
}

export default function BiChart({ result, chart }: { result: BiResult; chart: Chart }) {
  const host = useRef<HTMLDivElement>(null);
  const { kind, notice } = plan(result, chart);
  const canvas = kind !== "table" && kind !== "single";

  useEffect(() => {
    const node = host.current;
    if (!node || !canvas) return;
    const instance = echarts.init(node, undefined, { renderer: "canvas" });
    const paint = () => {
      const option = chartOption(result, readPalette(), chart);
      if (option) instance.setOption(option as unknown as echarts.EChartsCoreOption, true);
    };
    paint();
    const resize = new ResizeObserver(() => instance.resize());
    resize.observe(node);
    const theme = new MutationObserver(paint);
    theme.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => {
      resize.disconnect();
      theme.disconnect();
      instance.dispose();
    };
  }, [result, chart, canvas]);

  const summary = `${result.title}. Xem bảng số liệu bên dưới.`;
  return (
    <>
      {notice && <p className="notice notice-info" role="status">{notice}</p>}
      {kind === "table" ? (
        <MatrixTable result={result} />
      ) : (
        <>
          {canvas && <div ref={host} className="bi-chart" role="img" aria-label={summary} />}
          <details className="details-block">
            <summary>Bảng số liệu</summary>
            <MatrixTable result={result} />
          </details>
        </>
      )}
    </>
  );
}
