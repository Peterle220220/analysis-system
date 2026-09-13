// Khung keo tha tu phan tich: cau hinh (Spec) -> JSON gui may chu -> tuy chon
// bieu do ECharts. Ham thuan, khong import gi, de test duoc bang Node tran.

export type Role = "dimension" | "measure";
export type Kind = "text" | "date" | "boolean" | "number";
export type BiField = { name: string; role: Role; kind: Kind; distinct: number };
export type Zone = "x" | "y" | "color" | "filters";
export type Aggregation = "sum" | "mean" | "median" | "min" | "max" | "count" | "count_distinct";
export type FilterSpec = { field: string; role: Role; values: string[]; min: number | null; max: number | null };
export type Spec = { x: string | null; y: string | null; aggregation: Aggregation; color: string | null; filters: FilterSpec[] };

export const EMPTY_SPEC: Spec = { x: null, y: null, aggregation: "mean", color: null, filters: [] };

export const AGGREGATIONS: ReadonlyArray<{ value: Aggregation; label: string; numeric: boolean }> = [
  { value: "sum", label: "Tổng", numeric: true },
  { value: "mean", label: "Trung bình", numeric: true },
  { value: "median", label: "Trung vị", numeric: true },
  { value: "min", label: "Nhỏ nhất", numeric: true },
  { value: "max", label: "Lớn nhất", numeric: true },
  { value: "count", label: "Đếm", numeric: false },
  { value: "count_distinct", label: "Đếm giá trị khác nhau", numeric: false },
];

export const ZONE_LABELS: Record<Zone, string> = {
  x: "Trục X",
  y: "Trục Y",
  color: "Phân nhóm (Legend)",
  filters: "Bộ lọc",
};

export function isNumericAggregation(aggregation: Aggregation): boolean {
  return AGGREGATIONS.some((item) => item.value === aggregation && item.numeric);
}

/** Vi sao vung nay khong nhan cot nay; chuoi rong la nhan. */
export function refusal(zone: Zone, field: BiField): string {
  if ((zone === "x" || zone === "color") && field.role !== "dimension") {
    return `${ZONE_LABELS[zone]} chỉ nhận Dimension; "${field.name}" là Measure. Hãy kéo nó vào Trục Y hoặc Bộ lọc.`;
  }
  return "";
}

/** Tha mot cot vao mot vung. Vung khong nhan thi giu nguyen cau hinh. */
export function drop(spec: Spec, zone: Zone, field: BiField): Spec {
  if (refusal(zone, field)) return spec;
  if (zone === "x") return { ...spec, x: field.name, color: spec.color === field.name ? null : spec.color };
  if (zone === "color") return { ...spec, color: field.name, x: spec.x === field.name ? null : spec.x };
  if (zone === "y") {
    // Mot Dimension tren truc Y chi dem duoc: cong hay lay trung binh chu thi vo nghia.
    const aggregation = field.role !== "measure" && isNumericAggregation(spec.aggregation) ? "count" : spec.aggregation;
    return { ...spec, y: field.name, aggregation };
  }
  if (spec.filters.some((item) => item.field === field.name)) return spec;
  return { ...spec, filters: [...spec.filters, { field: field.name, role: field.role, values: [], min: null, max: null }] };
}

export function remove(spec: Spec, zone: Zone, name: string): Spec {
  if (zone === "x") return spec.x === name ? { ...spec, x: null } : spec;
  if (zone === "y") return spec.y === name ? { ...spec, y: null } : spec;
  if (zone === "color") return spec.color === name ? { ...spec, color: null } : spec;
  return { ...spec, filters: spec.filters.filter((item) => item.field !== name) };
}

/** Doi phep gop. Phep gop can so tren mot cot Dimension thi bi bo qua. */
export function setAggregation(spec: Spec, aggregation: Aggregation, y: BiField | undefined): Spec {
  if (y && y.role !== "measure" && isNumericAggregation(aggregation)) return spec;
  return { ...spec, aggregation };
}

export function setFilter(spec: Spec, name: string, patch: Partial<Pick<FilterSpec, "values" | "min" | "max">>): Spec {
  return { ...spec, filters: spec.filters.map((item) => (item.field === name ? { ...item, ...patch } : item)) };
}

export type QueryFilter = { field: string; values?: string[]; min?: number; max?: number };
export type QueryJson = { x: string | null; y: string | null; aggregation: Aggregation; color: string | null; filters: QueryFilter[] };

/** JSON gui may chu; null khi chua co gi de ve. Bo loc chua chon gi thi chua gui. */
export function toQuery(spec: Spec): QueryJson | null {
  if (!spec.x && !spec.y && !spec.color) return null;
  const filters = spec.filters.flatMap((item): QueryFilter[] => {
    if (item.role === "dimension") return item.values.length ? [{ field: item.field, values: item.values }] : [];
    const bound: QueryFilter = { field: item.field };
    if (item.min !== null && Number.isFinite(item.min)) bound.min = item.min;
    if (item.max !== null && Number.isFinite(item.max)) bound.max = item.max;
    return bound.min === undefined && bound.max === undefined ? [] : [bound];
  });
  return { x: spec.x, y: spec.y, aggregation: spec.aggregation, color: spec.color, filters };
}

export type BiResult = {
  kind: "bar" | "line" | "single";
  title: string;
  x_label: string;
  value_label: string;
  categories: string[];
  series: Array<{ name: string; values: Array<number | null> }>;
  rows_used: number;
  dropped: number;
  other_series: boolean;
  sql: string;
  params: unknown[];
};

export type ChartPalette = {
  text: string;
  muted: string;
  grid: string;
  axis: string;
  tooltipBg: string;
  tooltipText: string;
  tooltipBorder: string;
  series: string[];
};

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "không có";
  return value.toLocaleString("vi-VN", { maximumFractionDigits: Math.abs(value) >= 100 ? 1 : 3 });
}

/** So khop chu khong phan biet hoa thuong va dau: "ty le" tim ra "Tỷ lệ". */
export function matchesText(text: string, query: string): boolean {
  const fold = (value: string) => value.normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/đ/g, "d").replace(/Đ/g, "D").toLowerCase();
  return fold(text).includes(fold(query.trim()));
}

/** Tuy chon ECharts cho mot ket qua. `single` khong ve bieu do (hien mot con so lon). */
export function chartOption(result: BiResult, palette: ChartPalette): Record<string, unknown> | null {
  if (result.kind === "single" || result.categories.length === 0) return null;
  const line = result.kind === "line";
  const legend = result.series.length > 1;
  const crowded = result.categories.length > 8;
  return {
    animation: false,
    color: palette.series,
    textStyle: { color: palette.text, fontFamily: "system-ui, -apple-system, 'Segoe UI', sans-serif" },
    grid: { left: 8, right: 16, top: legend ? 40 : 16, bottom: 8, containLabel: true },
    legend: { show: legend, top: 0, type: "scroll", icon: "roundRect", textStyle: { color: palette.text } },
    tooltip: {
      trigger: "axis",
      axisPointer: { type: line ? "line" : "shadow" },
      backgroundColor: palette.tooltipBg,
      borderColor: palette.tooltipBorder,
      textStyle: { color: palette.tooltipText },
      valueFormatter: (value: number) => formatNumber(value),
    },
    xAxis: {
      type: "category",
      data: result.categories,
      axisLabel: { color: palette.muted, rotate: crowded ? 35 : 0, hideOverlap: true },
      axisLine: { lineStyle: { color: palette.axis } },
      axisTick: { show: false },
    },
    yAxis: {
      type: "value",
      axisLabel: { color: palette.muted, formatter: (value: number) => formatNumber(value) },
      splitLine: { lineStyle: { color: palette.grid } },
    },
    series: result.series.map((item, index) => ({
      name: item.name,
      type: line ? "line" : "bar",
      data: item.values,
      itemStyle: { color: palette.series[index % palette.series.length], borderRadius: line ? 0 : [4, 4, 0, 0] },
      barMaxWidth: 48,
      showSymbol: line && result.categories.length <= 60,
      symbolSize: 8,
      lineStyle: { width: 2 },
      emphasis: { focus: "series" },
    })),
  };
}
