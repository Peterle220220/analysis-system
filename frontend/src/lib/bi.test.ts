import assert from "node:assert/strict";
import { test } from "node:test";
import {
  chartOption,
  drop,
  EMPTY_SPEC,
  formatNumber,
  matchesText,
  refusal,
  remove,
  setAggregation,
  setFilter,
  toQuery,
  type BiField,
  type BiResult,
  type ChartPalette,
} from "./bi.ts";

const flag: BiField = { name: "Bankrupt?", role: "dimension", kind: "boolean", distinct: 2 };
const region: BiField = { name: "Region", role: "dimension", kind: "text", distinct: 3 };
const debt: BiField = { name: "Debt ratio %", role: "measure", kind: "number", distinct: 100 };

test("truc X va Legend chi nhan Dimension, va noi ro vi sao", () => {
  assert.match(refusal("x", debt), /Dimension/);
  assert.match(refusal("color", debt), /Dimension/);
  assert.equal(refusal("y", debt), "");
  assert.equal(drop(EMPTY_SPEC, "x", debt), EMPTY_SPEC);
  assert.equal(drop(EMPTY_SPEC, "x", flag).x, "Bankrupt?");
});

test("tha Dimension vao truc Y thi phep gop chuyen sang Dem", () => {
  const spec = drop(EMPTY_SPEC, "y", region);
  assert.equal(spec.y, "Region");
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
  assert.equal(remove(spec, "x", "Bankrupt?").x, null);
});

const palette: ChartPalette = {
  text: "#text",
  muted: "#muted",
  grid: "#grid",
  axis: "#axis",
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

type Option = {
  legend: { show: boolean };
  xAxis: { axisLabel: { rotate: number } };
  series: Array<{ type: string; itemStyle: { color: string } }>;
};

test("cot: moi nhom Legend mot chuoi, mau theo dung thu tu bang mau", () => {
  const option = chartOption(result({ series: [{ name: "Bắc", values: [1, 2] }, { name: "Nam", values: [3, null] }] }), palette) as unknown as Option;
  assert.equal(option.series.length, 2);
  assert.deepEqual(option.series.map((item) => item.itemStyle.color), ["#s1", "#s2"]);
  assert.deepEqual(option.series.map((item) => item.type), ["bar", "bar"]);
  assert.equal(option.legend.show, true);
});

test("mot chuoi thi khong can hop chu giai; truc ngay la duong", () => {
  const single = chartOption(result({}), palette) as unknown as Option;
  assert.equal(single.legend.show, false);
  const line = chartOption(result({ kind: "line" }), palette) as unknown as Option;
  assert.equal(line.series[0].type, "line");
});

test("nhieu nhom thi nghieng nhan truc X; mot con so thi khong ve bieu do", () => {
  const many = Array.from({ length: 12 }, (_, index) => `c${index}`);
  const option = chartOption(result({ categories: many, series: [{ name: "v", values: many.map(() => 1) }] }), palette) as unknown as Option;
  assert.equal(option.xAxis.axisLabel.rotate, 35);
  assert.equal(chartOption(result({ kind: "single", categories: [] }), palette), null);
});

test("so viet kieu Viet Nam, thieu so thi noi ro", () => {
  assert.equal(formatNumber(1234.5), "1.234,5");
  assert.equal(formatNumber(0.12345), "0,123");
  assert.equal(formatNumber(null), "không có");
});

test("tim cot khong can go dau", () => {
  assert.ok(matchesText("Tỷ lệ nợ", "ty le"));
  assert.ok(matchesText("Debt ratio %", "RATIO"));
  assert.ok(!matchesText("Region", "debt"));
});
