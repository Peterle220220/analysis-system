// Khung keo tha tu phan tich: cau hinh (Spec) -> JSON gui may chu -> tuy chon
// bieu do ECharts. Ham thuan, khong import gi, de test duoc bang Node tran.

export type Role = "dimension" | "measure";
export type Kind = "text" | "date" | "boolean" | "number";
export type BiField = { name: string; role: Role; kind: Kind; distinct: number };
export type Zone = "x" | "y" | "color" | "filters";
export type Aggregation = "sum" | "mean" | "median" | "min" | "max" | "count" | "count_distinct";
export type FilterSpec = { field: string; role: Role; values: string[]; min: number | null; max: number | null };
export type Spec = { x: string | null; y: string | null; aggregation: Aggregation; color: string | null; filters: FilterSpec[] };
export type Chart = "auto" | "bar" | "stacked" | "stacked100" | "line" | "donut" | "waterfall" | "scatter" | "table";
export type ViewState = Spec & { chart: Chart };
export type SavedView = { id: string; name: string; state: ViewState; created_at: string; updated_at: string };

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

export const CHARTS: ReadonlyArray<{ value: Chart; label: string }> = [
  { value: "auto", label: "Tự động" },
  { value: "bar", label: "Cột" },
  { value: "stacked", label: "Cột chồng" },
  { value: "stacked100", label: "Cột chồng 100%" },
  { value: "line", label: "Đường" },
  { value: "donut", label: "Vành khuyên" },
  { value: "waterfall", label: "Thác nước" },
  { value: "scatter", label: "Phân tán" },
  { value: "table", label: "Dạng bảng" },
];

export function chartLabel(chart: string): string {
  return CHARTS.find((item) => item.value === chart)?.label ?? chart;
}

export const ZONE_LABELS: Record<Zone, string> = {
  x: "Trục X",
  y: "Trục Y",
  color: "Phân nhóm (Legend)",
  filters: "Bộ lọc",
};

/** Vanh khuyen chia toi da chung nay lat; lat thu tam tro di gop thanh "Khác". */
export const DONUT_SLICES = 8;

/** Ten vung theo loai bieu do: vanh khuyen khong co truc, chi co nhom va gia tri. */
export function zoneLabel(zone: Zone, chart: Chart): string {
  if (chart === "donut" && zone === "x") return "Nhóm (lát cắt)";
  if (chart === "donut" && zone === "y") return "Giá trị";
  if (chart === "waterfall" && zone === "x") return "Các bước (Trục X)";
  if (chart === "waterfall" && zone === "y") return "Mức thay đổi (Trục Y)";
  return ZONE_LABELS[zone];
}

/** Vanh khuyen va thac nuoc chi ve mot Measure, khong tach mau theo Legend. */
export function usesLegend(chart: Chart): boolean {
  return chart !== "donut" && chart !== "waterfall";
}

export function isNumericAggregation(aggregation: Aggregation): boolean {
  return AGGREGATIONS.some((item) => item.value === aggregation && item.numeric);
}

/**
 * Vi sao vung nay khong nhan cot nay; chuoi rong la nhan. Truc X nhan ca Measure
 * (hai Measure thanh bieu do phan tan); Legend van chi nhan Dimension.
 */
export function refusal(zone: Zone, field: BiField): string {
  if (zone === "color" && field.role !== "dimension") {
    return `${ZONE_LABELS.color} chỉ nhận Dimension; "${field.name}" là Measure. Hãy kéo nó vào một trục hoặc Bộ lọc.`;
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

/** Mot dong tom tat bo loc dang loc gi, hien tren thanh tieu de khi the da thu gon. */
export function filterSummary(filter: FilterSpec): string {
  if (filter.role === "measure") {
    const shown = (value: number) => value.toLocaleString("vi-VN");
    if (filter.min !== null && filter.max !== null) return `Từ ${shown(filter.min)} đến ${shown(filter.max)}`;
    if (filter.min !== null) return `Từ ${shown(filter.min)}`;
    if (filter.max !== null) return `Đến ${shown(filter.max)}`;
    return "Chưa đặt khoảng";
  }
  return filter.values.length ? `Đã chọn ${filter.values.length} giá trị` : "Chưa chọn giá trị nào";
}

export type QueryFilter = { field: string; values?: string[]; min?: number; max?: number };
export type QueryJson = {
  x: string | null;
  y: string | null;
  aggregation: Aggregation;
  color: string | null;
  filters: QueryFilter[];
  top?: number;
};

/** JSON gui may chu; null khi chua co gi de ve. Bo loc chua chon gi thi chua gui. */
export function toQuery(spec: Spec, chart: Chart = "auto"): QueryJson | null {
  if (!spec.x && !spec.y && !spec.color) return null;
  const filters = spec.filters.flatMap((item): QueryFilter[] => {
    if (item.role === "dimension") return item.values.length ? [{ field: item.field, values: item.values }] : [];
    const bound: QueryFilter = { field: item.field };
    if (item.min !== null && Number.isFinite(item.min)) bound.min = item.min;
    if (item.max !== null && Number.isFinite(item.max)) bound.max = item.max;
    return bound.min === undefined && bound.max === undefined ? [] : [bound];
  });
  const query: QueryJson = { x: spec.x, y: spec.y, aggregation: spec.aggregation, color: usesLegend(chart) ? spec.color : null, filters };
  if (chart === "donut") query.top = DONUT_SLICES;
  return query;
}

/**
 * Dung lai mot ban da luu tren bang hien tai. Bang co the da duoc lam sach lai
 * va doi cot: cot khong con thi bo, va noi ra ten cac cot da bo.
 */
export function sanitizeState(state: ViewState, fields: BiField[]): { spec: Spec; chart: Chart; dropped: string[] } {
  const known = new Map(fields.map((field) => [field.name, field]));
  const dropped: string[] = [];
  const keep = (name: string | null, dimensionOnly = false): string | null => {
    if (!name) return null;
    const field = known.get(name);
    if (!field || (dimensionOnly && field.role !== "dimension")) {
      dropped.push(name);
      return null;
    }
    return name;
  };
  const x = keep(state.x);
  const y = keep(state.y);
  const color = keep(state.color, true);
  const filters: FilterSpec[] = [];
  for (const item of state.filters) {
    const field = known.get(item.field);
    if (!field) dropped.push(item.field);
    else filters.push({ ...item, role: field.role });
  }
  const yField = y ? known.get(y) : undefined;
  const aggregation = yField && yField.role !== "measure" && isNumericAggregation(state.aggregation) ? "count" : state.aggregation;
  const chart = CHARTS.some((item) => item.value === state.chart) ? state.chart : "auto";
  return { spec: { x, y, aggregation, color, filters }, chart, dropped };
}

export type BiSeries = { name: string; values: Array<number | null>; points?: Array<[number, number]> };

export type BiResult = {
  kind: "bar" | "line" | "single" | "scatter";
  title: string;
  x_label: string;
  value_label: string;
  categories: string[];
  series: BiSeries[];
  rows_used: number;
  dropped: number;
  other_series: boolean;
  folded_x?: boolean;
  pairs?: number;
  correlation?: number | null;
  sampled?: boolean;
  sql: string;
  params: unknown[];
};

export type ChartPalette = {
  text: string;
  muted: string;
  grid: string;
  axis: string;
  surface: string;
  tooltipBg: string;
  tooltipText: string;
  tooltipBorder: string;
  series: string[];
};

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "không có";
  return value.toLocaleString("vi-VN", { maximumFractionDigits: Math.abs(value) >= 100 ? 1 : 3 });
}

/** So co dau: "+1,2" hay "−0,5" (dau tru that, khong phai gach noi). */
export function signed(value: number): string {
  return value > 0 ? `+${formatNumber(value)}` : value < 0 ? `−${formatNumber(Math.abs(value))}` : formatNumber(0);
}

/** Ten cot va gia tri den tu du lieu nguoi dung: thoat truoc khi dua vao HTML cua tooltip. */
export function escapeHtml(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

/** So khop chu khong phan biet hoa thuong va dau: "ty le" tim ra "Tỷ lệ". */
export function matchesText(text: string, query: string): boolean {
  const fold = (value: string) => value.normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/đ/g, "d").replace(/Đ/g, "D").toLowerCase();
  return fold(text).includes(fold(query.trim()));
}

/** Ten cot de doc: "_" thanh khoang trang, viet hoa chu dau, phan con lai giu nguyen. */
export function humanize(name: string): string {
  const spaced = name.replace(/_+/g, " ").replace(/\s+/g, " ").trim();
  return spaced ? spaced.charAt(0).toLocaleUpperCase("vi") + spaced.slice(1) : spaced;
}

/** Cau hinh da tao ra mot ket qua: tieu de dung tu dung cau hinh do, khong tu cau hinh dang keo do. */
export type TitleSource = { x: string | null; y: string | null; aggregation: Aggregation; color: string | null };

/** "Trung bình Debt ratio %", "Số lượng Student id", "Số lượng Region khác nhau", "Số dòng". */
export function measureLabel(source: TitleSource): string {
  if (!source.y) return "Số dòng";
  const y = humanize(source.y);
  if (source.aggregation === "count") return `Số lượng ${y}`;
  if (source.aggregation === "count_distinct") return `Số lượng ${y} khác nhau`;
  const label = AGGREGATIONS.find((item) => item.value === source.aggregation)?.label ?? "";
  return `${label} ${y}`.trim();
}

/**
 * Tieu de tu dong, viet nhu nguoi viet chu khong ghep may moc:
 * phan tan: "Mối tương quan giữa X và Y[, phân nhóm theo L]";
 * con lai: "[Phép tính] Y theo X[, phân theo L]".
 */
export function autoTitle(result: BiResult, source: TitleSource, chart: Chart): string {
  const legend = source.color && usesLegend(chart) ? humanize(source.color) : "";
  if (result.kind === "scatter") {
    const pair = `Mối tương quan giữa ${humanize(result.x_label)} và ${humanize(source.y ?? result.value_label)}`;
    return legend ? `${pair}, phân nhóm theo ${legend}` : pair;
  }
  const measure = measureLabel(source);
  if (result.kind === "single" || !result.x_label) return measure;
  // Chi co Legend thi may chu dua Legend len lam truc: khong noi "phan theo" lan nua.
  const split = legend && source.x ? `, phân theo ${legend}` : "";
  return `${measure} theo ${humanize(result.x_label)}${split}`;
}

/** Ket qua san de hien: tieu de, nhan truc va ten chuoi don deu theo cung quy tac. */
export function present(result: BiResult, source: TitleSource, chart: Chart): BiResult {
  const measure = result.kind === "scatter" ? humanize(source.y ?? result.value_label) : measureLabel(source);
  const legendUsed = Boolean(source.color && usesLegend(chart) && source.x);
  return {
    ...result,
    title: autoTitle(result, source, chart),
    x_label: result.x_label ? humanize(result.x_label) : result.x_label,
    value_label: measure,
    series: legendUsed || result.series.length !== 1 ? result.series : result.series.map((item) => ({ ...item, name: measure })),
  };
}

export type FolderLike = { run_id: string; label?: string; origin?: string; views: Array<{ name: string }> };

/**
 * Chia cac bo du lieu theo loi vao: tai thang vao Tu phan tich, hay tu muc Du
 * lieu. Tim theo ten bo HOAC ten mot ban da luu ben trong, khong can go dau.
 */
export function groupDatasets<T extends FolderLike>(folders: T[], query: string): { direct: T[]; library: T[] } {
  const wanted = query.trim();
  const shown = wanted ? folders.filter((folder) => matchesText(folder.run_id, wanted) || matchesText(folder.label ?? "", wanted) || folder.views.some((view) => matchesText(view.name, wanted))) : folders;
  return {
    direct: shown.filter((folder) => folder.origin === "tu_phan_tich"),
    library: shown.filter((folder) => folder.origin !== "tu_phan_tich"),
  };
}

export function hasNegative(result: BiResult): boolean {
  return result.series.some((item) => item.values.some((value) => value !== null && value < 0));
}

export type RenderKind = "single" | "table" | "bar" | "stacked" | "stacked100" | "line" | "donut" | "waterfall" | "scatter";

/** Loai bieu do se ve that, va mot cau noi ra khi phai doi so voi loai da chon. */
export function plan(result: BiResult, chart: Chart): { kind: RenderKind; notice: string } {
  if (chart === "table") return { kind: "table", notice: "" };
  if (result.kind === "single") return { kind: "single", notice: "" };
  if (result.kind === "scatter") return { kind: "scatter", notice: "" };
  const fallback: RenderKind = result.kind === "line" ? "line" : "bar";
  if (chart === "auto") return { kind: fallback, notice: "" };
  if (chart === "scatter") return { kind: fallback, notice: "Phân tán cần hai Measure ở Trục X và Trục Y; đang vẽ dạng thường." };
  if (chart === "donut" && hasNegative(result)) return { kind: "bar", notice: "Vành khuyên không vẽ được giá trị âm; đang vẽ dạng cột." };
  if (chart === "stacked100" && hasNegative(result)) return { kind: "stacked", notice: "Cột chồng 100% cần giá trị không âm; đang vẽ cột chồng." };
  if ((chart === "stacked" || chart === "stacked100") && result.series.length < 2) {
    return { kind: chart, notice: "Thả một Dimension vào Legend để chia mỗi cột thành nhiều phần." };
  }
  return { kind: chart, notice: "" };
}

/** Ty trong phan tram cua moi chuoi trong tung nhom (cot chong 100%). */
export function shares(series: BiSeries[]): BiSeries[] {
  const width = Math.max(0, ...series.map((item) => item.values.length));
  const totals = Array.from({ length: width }, (_, index) => series.reduce((sum, item) => sum + (item.values[index] ?? 0), 0));
  return series.map((item) => ({
    ...item,
    values: item.values.map((value, index) => (value === null || totals[index] <= 0 ? null : (value / totals[index]) * 100)),
  }));
}

export type Waterfall = {
  labels: string[];
  base: Array<number | null>;
  up: Array<number | null>;
  down: Array<number | null>;
  total: Array<number | null>;
};

/**
 * Thac nuoc theo kieu Power BI: moi nhom la mot khoan cong/tru. Day tang hinh la
 * muc thap hon giua truoc va sau buoc do; cot hien ra cao dung |thay doi|; cot
 * cuoi la Tong. Dung voi ca buoc di qua so 0 (chong kieu stackStrategy "all").
 */
export function waterfall(categories: string[], values: Array<number | null>): Waterfall {
  let running = 0;
  const flow: Waterfall = { labels: [...categories, "Tổng"], base: [], up: [], down: [], total: [] };
  for (const value of values) {
    const change = value ?? 0;
    const start = running;
    running += change;
    flow.base.push(Math.min(start, running));
    flow.up.push(change > 0 ? change : null);
    flow.down.push(change < 0 ? -change : null);
    flow.total.push(null);
  }
  flow.base.push(0);
  flow.up.push(null);
  flow.down.push(null);
  flow.total.push(running);
  return flow;
}

export type Tone = { sign: "pos" | "neg" | "none"; strength: number };

/** Mau nen cua mot o bang: duong/am, dam theo do lon so voi o lon nhat cot do. */
export function cellTone(value: number | null | undefined, largest: number): Tone {
  if (value === null || value === undefined || !Number.isFinite(value) || value === 0 || largest <= 0) return { sign: "none", strength: 0 };
  return { sign: value > 0 ? "pos" : "neg", strength: Math.min(1, Math.abs(value) / largest) };
}

export type Matrix = { columns: string[]; rows: Array<{ label: string; values: Array<number | null> }>; largest: number[] };

/** Ket qua gop nhom thanh bang ma tran: moi nhom mot dong, moi chuoi mot cot. */
export function matrixOf(result: BiResult): Matrix {
  let columns: string[];
  let rows: Matrix["rows"];
  if (result.kind === "scatter") {
    columns = ["Nhóm", result.x_label, result.value_label];
    rows = result.series.flatMap((item) => (item.points ?? []).map(([x, y]) => ({ label: item.name, values: [x, y] })));
  } else if (result.kind === "single") {
    columns = ["Chỉ số", "Giá trị"];
    rows = result.series.map((item) => ({ label: item.name, values: [item.values[0] ?? null] }));
  } else {
    columns = [result.x_label || "Nhóm", ...result.series.map((item) => item.name)];
    rows = result.categories.map((label, index) => ({ label, values: result.series.map((item) => item.values[index] ?? null) }));
  }
  const width = columns.length - 1;
  const largest = Array.from({ length: width }, (_, column) => Math.max(0, ...rows.map((row) => Math.abs(row.values[column] ?? 0))));
  return { columns, rows, largest };
}

type Params = { seriesName?: string; name?: string; value?: unknown };

/** Tuy chon ECharts cho mot ket qua va mot loai bieu do; null khi khong ve canvas. */
export function chartOption(result: BiResult, palette: ChartPalette, chart: Chart = "auto"): Record<string, unknown> | null {
  const { kind } = plan(result, chart);
  if (kind === "single" || kind === "table") return null;
  const colour = (index: number) => palette.series[index % palette.series.length];
  const tooltipStyle = { backgroundColor: palette.tooltipBg, borderColor: palette.tooltipBorder, textStyle: { color: palette.tooltipText } };
  const base = { animation: false, color: palette.series, textStyle: { color: palette.text, fontFamily: "system-ui, -apple-system, 'Segoe UI', sans-serif" } };
  const legendOn = result.series.length > 1;
  const legend = { show: legendOn, top: 0, type: "scroll", icon: "roundRect", textStyle: { color: palette.text } };
  const valueAxis = { type: "value", axisLabel: { color: palette.muted, formatter: (value: number) => formatNumber(value) }, splitLine: { lineStyle: { color: palette.grid } } };

  if (kind === "scatter") {
    return {
      ...base,
      legend,
      grid: { left: 12, right: 24, top: legendOn ? 40 : 24, bottom: 36, containLabel: true },
      tooltip: {
        ...tooltipStyle,
        trigger: "item",
        formatter: (params: Params) => {
          const [x, y] = (params.value as [number, number]) ?? [NaN, NaN];
          return `${escapeHtml(String(params.seriesName ?? ""))}<br/>${escapeHtml(result.x_label)}: ${formatNumber(x)}<br/>${escapeHtml(result.value_label)}: ${formatNumber(y)}`;
        },
      },
      xAxis: { ...valueAxis, scale: true, name: result.x_label, nameLocation: "middle", nameGap: 28, nameTextStyle: { color: palette.muted }, axisLine: { lineStyle: { color: palette.axis } } },
      yAxis: { ...valueAxis, scale: true, name: result.value_label, nameTextStyle: { color: palette.muted } },
      series: result.series.map((item, index) => ({
        name: item.name,
        type: "scatter",
        data: item.points ?? [],
        symbolSize: 7,
        large: (item.points?.length ?? 0) > 2000,
        itemStyle: { color: colour(index), opacity: 0.75, borderColor: palette.surface, borderWidth: 1 },
      })),
    };
  }

  if (kind === "donut") {
    const values = result.series[0]?.values ?? [];
    return {
      ...base,
      legend: { show: true, bottom: 0, type: "scroll", icon: "roundRect", textStyle: { color: palette.text } },
      tooltip: { ...tooltipStyle, trigger: "item", valueFormatter: (value: number) => formatNumber(value) },
      series: [{
        name: result.value_label,
        type: "pie",
        radius: ["40%", "70%"],
        center: ["50%", "45%"],
        avoidLabelOverlap: true,
        itemStyle: { borderColor: palette.surface, borderWidth: 2 },
        label: { color: palette.text, formatter: "{b}: {d}%" },
        data: result.categories.map((name, index) => ({ name, value: values[index] ?? 0, itemStyle: { color: colour(index) } })),
      }],
    };
  }

  const categoryAxis = (labels: string[]) => ({
    type: "category",
    data: labels,
    axisLabel: { color: palette.muted, rotate: labels.length > 8 ? 35 : 0, hideOverlap: true },
    axisLine: { lineStyle: { color: palette.axis } },
    axisTick: { show: false },
  });

  if (kind === "waterfall") {
    const flow = waterfall(result.categories, result.series[0]?.values ?? []);
    const step = { type: "bar", stack: "waterfall", stackStrategy: "all", barMaxWidth: 48 };
    const label = (show: (value: number) => string, position: string) => ({
      show: true,
      position,
      color: palette.text,
      formatter: (params: Params) => (typeof params.value === "number" ? show(params.value) : ""),
    });
    return {
      ...base,
      legend: { ...legend, show: true, data: ["Tăng", "Giảm", "Tổng"] },
      grid: { left: 8, right: 16, top: 40, bottom: 8, containLabel: true },
      tooltip: {
        ...tooltipStyle,
        trigger: "item",
        formatter: (params: Params) => {
          if (typeof params.value !== "number") return "";
          const shown = params.seriesName === "Giảm" ? signed(-params.value) : params.seriesName === "Tăng" ? signed(params.value) : formatNumber(params.value);
          return `${escapeHtml(String(params.name ?? ""))}<br/>${escapeHtml(String(params.seriesName ?? ""))}: ${shown}`;
        },
      },
      xAxis: categoryAxis(flow.labels),
      yAxis: valueAxis,
      series: [
        { ...step, name: "Nền", data: flow.base, silent: true, itemStyle: { color: "transparent" }, emphasis: { disabled: true }, tooltip: { show: false } },
        { ...step, name: "Tăng", data: flow.up, itemStyle: { color: colour(0) }, label: label((value) => signed(value), "top") },
        { ...step, name: "Giảm", data: flow.down, itemStyle: { color: colour(7) }, label: label((value) => signed(-value), "bottom") },
        { ...step, name: "Tổng", data: flow.total, itemStyle: { color: palette.muted }, label: label((value) => formatNumber(value), "top") },
      ],
    };
  }

  const line = kind === "line";
  const stacked = kind === "stacked" || kind === "stacked100";
  const percent = kind === "stacked100";
  const series = percent ? shares(result.series) : result.series;
  return {
    ...base,
    legend,
    grid: { left: 8, right: 16, top: legendOn ? 40 : 16, bottom: 8, containLabel: true },
    tooltip: {
      ...tooltipStyle,
      trigger: "axis",
      axisPointer: { type: line ? "line" : "shadow" },
      valueFormatter: (value: number) => (percent ? `${formatNumber(value)}%` : formatNumber(value)),
    },
    xAxis: categoryAxis(result.categories),
    yAxis: percent ? { ...valueAxis, max: 100, axisLabel: { color: palette.muted, formatter: (value: number) => `${value}%` } } : valueAxis,
    series: series.map((item, index) => ({
      name: item.name,
      type: line ? "line" : "bar",
      stack: stacked ? "total" : undefined,
      data: item.values,
      itemStyle: {
        color: colour(index),
        borderRadius: line || stacked ? 0 : [4, 4, 0, 0],
        borderColor: stacked ? palette.surface : undefined,
        borderWidth: stacked ? 1 : 0,
      },
      barMaxWidth: 48,
      showSymbol: line && result.categories.length <= 60,
      symbolSize: 8,
      lineStyle: { width: 2 },
      emphasis: { focus: "series" },
    })),
  };
}
