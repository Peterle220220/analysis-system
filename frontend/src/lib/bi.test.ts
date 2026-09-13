import assert from "node:assert/strict";
import { test } from "node:test";
import {
  cellTone,
  chartOption,
  drop,
  EMPTY_SPEC,
  escapeHtml,
  formatNumber,
  matchesText,
  matrixOf,
  plan,
  refusal,
  remove,
  sanitizeState,
  setAggregation,
  setFilter,
  shares,
  signed,
  toQuery,
  waterfall,
  zoneLabel,
  type BiField,
  type BiResult,
  type ChartPalette,
} from "./bi.ts";

const flag: BiField = { name: "Bankrupt?", role: "dimension", kind: "boolean", distinct: 2 };
const region: BiField = { name: "Region", role: "dimension", kind: "text", distinct: 3 };
const debt: BiField = { name: "Debt ratio %", role: "measure", kind: "number", distinct: 100 };
const margin: BiField = { name: "Gross margin", role: "measure", kind: "number", distinct: 100 };

test("Legend chi nhan Dimension; truc X nhan ca Measure de ve phan tan", () => {
  assert.match(refusal("color", debt), /Dimension/);
  assert.equal(refusal("x", debt), "");
  assert.equal(drop(EMPTY_SPEC, "x", debt).x, "Debt ratio %");
  assert.equal(drop(EMPTY_SPEC, "color", debt), EMPTY_SPEC);
});

test("tha Dimension vao truc Y thi phep gop chuyen sang Dem", () => {
  const spec = drop(EMPTY_SPEC, "y", region);
  assert.equal(spec.aggregation, "count");
  assert.equal(setAggregation(spec, "sum", region).aggregation, "count");
  assert.equal(setAggregation(drop(spec, "y", debt), "sum", debt).aggregation, "sum");
});

test("mot cot khong nam cung luc o truc X va Legend", () => {
  const spec = drop(drop(EMPTY_SPEC, "x", flag), "color", flag);
  assert.equal(spec.color, "Bankrupt?");
  assert.equal(spec.x, null);
});

test("JSON chi gui khi co truc; bo loc chua chon gi thi chua gui", () => {
  assert.equal(toQuery(EMPTY_SPEC), null);
  let spec = drop(drop(EMPTY_SPEC, "x", flag), "y", debt);
  spec = drop(drop(spec, "filters", region), "filters", debt);
  assert.deepEqual(toQuery(spec)?.filters, []);
  spec = setFilter(setFilter(spec, "Region", { values: ["Nam"] }), "Debt ratio %", { min: 0.2 });
  assert.deepEqual(toQuery(spec), {
    x: "Bankrupt?",
    y: "Debt ratio %",
    aggregation: "mean",
    color: null,
    filters: [{ field: "Region", values: ["Nam"] }, { field: "Debt ratio %", min: 0.2 }],
  });
  assert.equal(remove(spec, "filters", "Region").filters.length, 1);
});

test("vanh khuyen va thac nuoc bo Legend; vanh khuyen xin toi da 8 lat", () => {
  const spec = { ...drop(drop(EMPTY_SPEC, "x", region), "y", debt), color: "Bankrupt?" };
  assert.equal(toQuery(spec, "donut")?.color, null);
  assert.equal(toQuery(spec, "donut")?.top, 8);
  assert.equal(toQuery(spec, "waterfall")?.color, null);
  assert.equal(toQuery(spec, "stacked")?.color, "Bankrupt?");
  assert.equal(zoneLabel("x", "donut"), "Nhóm (lát cắt)");
  assert.equal(zoneLabel("x", "bar"), "Trục X");
});

test("ban luu mo lai tren bang da doi cot: bo cot khong con, va noi ra", () => {
  const restored = sanitizeState(
    {
      x: "Region",
      y: "Cot da mat",
      aggregation: "sum",
      color: "Debt ratio %",
      chart: "stacked100",
      filters: [{ field: "Bankrupt?", role: "measure", values: ["1"], min: null, max: null }, { field: "Mat nua", role: "dimension", values: [], min: null, max: null }],
    },
    [flag, region, debt],
  );
  assert.deepEqual(restored.dropped, ["Cot da mat", "Debt ratio %", "Mat nua"]);
  assert.equal(restored.spec.x, "Region");
  assert.equal(restored.spec.y, null);
  assert.equal(restored.spec.color, null);
  assert.equal(restored.spec.filters[0].role, "dimension");
  assert.equal(restored.chart, "stacked100");
});

const palette: ChartPalette = {
  text: "#text",
  muted: "#muted",
  grid: "#grid",
  axis: "#axis",
  surface: "#surface",
  tooltipBg: "#tip",
  tooltipText: "#tiptext",
  tooltipBorder: "#tipborder",
  series: ["#s1", "#s2", "#s3", "#s4", "#s5", "#s6", "#s7", "#s8"],
};

function result(overrides: Partial<BiResult>): BiResult {
  return {
    kind: "bar",
    title: "",
    x_label: "Bankrupt?",
    value_label: "Trung bình Debt ratio %",
    categories: ["0", "1"],
    series: [{ name: "Trung bình Debt ratio %", values: [0.1, 0.2] }],
    rows_used: 10,
    dropped: 0,
    other_series: false,
    sql: "",
    params: [],
    ...overrides,
  };
}

type Series = { type: string; stack?: string; stackStrategy?: string; data: unknown[]; itemStyle: { color: string } };
type Option = {
  legend: { show: boolean };
  xAxis: { data?: string[]; axisLabel: { rotate: number } };
  yAxis: { max?: number };
  series: Series[];
};
const option = (value: BiResult, chart: Parameters<typeof chartOption>[2] = "auto") => chartOption(value, palette, chart) as unknown as Option;
const two = result({ series: [{ name: "Bắc", values: [1, 3] }, { name: "Nam", values: [3, 1] }] });

test("cot: moi nhom Legend mot chuoi, mau theo dung thu tu bang mau", () => {
  const drawn = option(two);
  assert.deepEqual(drawn.series.map((item) => item.itemStyle.color), ["#s1", "#s2"]);
  assert.deepEqual(drawn.series.map((item) => item.type), ["bar", "bar"]);
  assert.equal(drawn.legend.show, true);
  assert.equal(drawn.series[0].stack, undefined);
});

test("cot chong dung chung mot chong; 100% doi ra ty trong", () => {
  assert.deepEqual(option(two, "stacked").series.map((item) => item.stack), ["total", "total"]);
  const percent = option(two, "stacked100");
  assert.equal(percent.yAxis.max, 100);
  assert.deepEqual(percent.series[0].data, [25, 75]);
  assert.deepEqual(shares([{ name: "a", values: [0, null] }, { name: "b", values: [0, 2] }]).map((item) => item.values), [[null, null], [null, 100]]);
});

test("thac nuoc: day tang hinh la muc thap hon, cot cuoi la Tong, ke ca khi qua so 0", () => {
  assert.deepEqual(waterfall(["a", "b", "c"], [10, -4, 6]), {
    labels: ["a", "b", "c", "Tổng"],
    base: [0, 6, 6, 0],
    up: [10, null, 6, null],
    down: [null, 4, null, null],
    total: [null, null, null, 12],
  });
  const crossing = waterfall(["a", "b"], [5, -8]);
  assert.deepEqual(crossing.base, [0, -3, 0]);
  assert.deepEqual(crossing.total, [null, null, -3]);
  const drawn = option(result({ categories: ["a", "b"], series: [{ name: "v", values: [5, -8] }] }), "waterfall");
  assert.deepEqual(drawn.series.map((item) => item.stackStrategy), ["all", "all", "all", "all"]);
  assert.deepEqual(drawn.xAxis.data, ["a", "b", "Tổng"]);
});

test("vanh khuyen la pie hai ban kinh; gia tri am thi ve cot va noi ra", () => {
  const donut = chartOption(result({}), palette, "donut") as unknown as { series: Array<{ type: string; radius: string[] }> };
  assert.equal(donut.series[0].type, "pie");
  assert.deepEqual(donut.series[0].radius, ["40%", "70%"]);
  const negative = plan(result({ series: [{ name: "v", values: [1, -2] }] }), "donut");
  assert.equal(negative.kind, "bar");
  assert.match(negative.notice, /âm/);
});

test("phan tan: hai truc so, moi nhom Legend mot chuoi diem", () => {
  const scatter = result({ kind: "scatter", categories: [], series: [{ name: "a", values: [], points: [[1, 2], [3, 4]] }, { name: "b", values: [], points: [[5, 6]] }] });
  const drawn = chartOption(scatter, palette) as unknown as { xAxis: { type: string }; series: Series[] };
  assert.equal(drawn.xAxis.type, "value");
  assert.deepEqual(drawn.series.map((item) => item.type), ["scatter", "scatter"]);
  assert.equal(plan(result({}), "scatter").kind, "bar");
});

test("dang bang va mot con so thi khong ve canvas", () => {
  assert.equal(chartOption(result({}), palette, "table"), null);
  assert.equal(chartOption(result({ kind: "single", categories: [] }), palette), null);
  const many = Array.from({ length: 12 }, (_, index) => `c${index}`);
  assert.equal(option(result({ categories: many, series: [{ name: "v", values: many.map(() => 1) }] })).xAxis.axisLabel.rotate, 35);
});

test("bang ma tran: moi nhom mot dong, to mau theo dau va do lon", () => {
  const matrix = matrixOf(two);
  assert.deepEqual(matrix.columns, ["Bankrupt?", "Bắc", "Nam"]);
  assert.deepEqual(matrix.rows[1], { label: "1", values: [3, 1] });
  assert.deepEqual(matrix.largest, [3, 3]);
  assert.deepEqual(cellTone(-1.5, 3), { sign: "neg", strength: 0.5 });
  assert.deepEqual(cellTone(3, 3), { sign: "pos", strength: 1 });
  assert.deepEqual(cellTone(null, 3), { sign: "none", strength: 0 });
});

test("so viet kieu Viet Nam, co dau, va chu trong tooltip duoc thoat", () => {
  assert.equal(formatNumber(1234.5), "1.234,5");
  assert.equal(formatNumber(null), "không có");
  assert.equal(signed(2), "+2");
  assert.equal(signed(-0.5), "−0,5");
  assert.equal(escapeHtml('<b a="1">&'), "&lt;b a=&quot;1&quot;&gt;&amp;");
  assert.ok(matchesText("Tỷ lệ nợ", "ty le"));
  assert.ok(!matchesText("Region", "debt"));
  assert.equal(margin.role, "measure");
});
