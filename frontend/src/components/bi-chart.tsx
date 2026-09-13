"use client";

import { useEffect, useRef } from "react";
import { BarChart, LineChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { chartOption, formatNumber, type BiResult, type ChartPalette } from "@/lib/bi";

// Chi nap dung phan dung toi: cot, duong, luoi, chu giai, tooltip.
echarts.use([BarChart, LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);

/** Mau cua bieu do doc tu bien CSS, nen doi theo giao dien Sang/Toi. */
function readPalette(): ChartPalette {
  const style = getComputedStyle(document.documentElement);
  const read = (name: string) => style.getPropertyValue(name).trim();
  return {
    text: read("--chart-text"),
    muted: read("--chart-muted"),
    grid: read("--chart-grid"),
    axis: read("--chart-axis"),
    tooltipBg: read("--tooltip-bg"),
    tooltipText: read("--tooltip-text"),
    tooltipBorder: read("--tooltip-border"),
    series: [1, 2, 3, 4, 5, 6, 7, 8].map((slot) => read(`--series-${slot}`)),
  };
}

export default function BiChart({ result }: { result: BiResult }) {
  const host = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const node = host.current;
    if (!node) return;
    const chart = echarts.init(node, undefined, { renderer: "canvas" });
    const paint = () => {
      const option = chartOption(result, readPalette());
      if (option) chart.setOption(option as unknown as echarts.EChartsCoreOption, true);
    };
    paint();
    const resize = new ResizeObserver(() => chart.resize());
    resize.observe(node);
    const theme = new MutationObserver(paint);
    theme.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => {
      resize.disconnect();
      theme.disconnect();
      chart.dispose();
    };
  }, [result]);

  const summary = `${result.title}: ${result.categories.length} nhóm, ${result.series.length} chuỗi. Xem bảng số liệu bên dưới.`;
  return (
    <>
      <div ref={host} className="bi-chart" role="img" aria-label={summary} />
      <details className="details-block">
        <summary>Bảng số liệu</summary>
        <div className="table-wrap">
          <table>
            <caption className="sr-only">{result.title}</caption>
            <thead><tr><th scope="col">{result.x_label || "Nhóm"}</th>{result.series.map((item) => <th scope="col" key={item.name}>{item.name}</th>)}</tr></thead>
            <tbody>{result.categories.map((category, row) => <tr key={category}><th scope="row">{category}</th>{result.series.map((item) => <td key={item.name}>{formatNumber(item.values[row])}</td>)}</tr>)}</tbody>
          </table>
        </div>
      </details>
    </>
  );
}
