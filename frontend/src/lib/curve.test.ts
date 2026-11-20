import { test } from "node:test";
import assert from "node:assert/strict";

import { curveAxis, missingLabels, toCurvePoints } from "./curve.ts";

const history = [
  { month: "2026-06", date: "2026-06-23", total_chf: 0, reconstructed: false, missing: [] },
  { month: "2026-10", date: "2026-10-25", total_chf: 1800.83, reconstructed: false, missing: [] },
  { month: "2026-11", date: "2026-11-20", total_chf: 3391.17, reconstructed: false, missing: [] },
];

test("every point sits at its real date, from the first recorded month on", () => {
  const points = toCurvePoints(history);
  assert.deepEqual(
    points.map((p) => p.at),
    [Date.UTC(2026, 5, 23), Date.UTC(2026, 9, 25), Date.UTC(2026, 10, 20)]
  );
  assert.deepEqual(points.map((p) => p.month), ["2026-06", "2026-10", "2026-11"]);
  assert.deepEqual(points.map((p) => p.total_chf), [0, 1800.83, 3391.17]);
});

test("months with no data keep their width on the axis", () => {
  const axis = curveAxis(toCurvePoints(history));
  assert.equal(axis.byYear, false);
  assert.deepEqual(axis.ticks, [6, 7, 8, 9, 10].map((m) => Date.UTC(2026, m, 1)));
});

test("a year of monthly ticks is thinned to six", () => {
  const year = [
    { month: "2025-11", date: "2025-11-15", total_chf: 1, reconstructed: false, missing: [] },
    { month: "2026-11", date: "2026-11-20", total_chf: 2, reconstructed: false, missing: [] },
  ];
  const axis = curveAxis(toCurvePoints(year));
  assert.equal(axis.byYear, false);
  assert.deepEqual(axis.ticks, [11, 13, 15, 17, 19, 21].map((m) => Date.UTC(2025, m, 1)));
});

test("a history of several years is labelled on year starts", () => {
  const long = [
    { month: "2022-01", date: "2022-01-28", total_chf: 100, reconstructed: false, missing: [] },
    { month: "2026-11", date: "2026-11-20", total_chf: 3391.17, reconstructed: false, missing: [] },
  ];
  const axis = curveAxis(toCurvePoints(long));
  assert.equal(axis.byYear, true);
  assert.deepEqual(axis.ticks, [2023, 2024, 2025, 2026].map((y) => Date.UTC(y, 0, 1)));
});

test("a very long history keeps at most six year ticks", () => {
  const decade = [
    { month: "2011-03", date: "2011-03-01", total_chf: 1, reconstructed: false, missing: [] },
    { month: "2026-11", date: "2026-11-20", total_chf: 2, reconstructed: false, missing: [] },
  ];
  const { ticks } = curveAxis(toCurvePoints(decade));
  assert.deepEqual(ticks, [2012, 2015, 2018, 2021, 2024].map((y) => Date.UTC(y, 0, 1)));
});

const point = (month: string, total: number | null, reconstructed: boolean, missing: string[] = []) => ({
  month,
  date: `${month}-28`,
  total_chf: total,
  reconstructed,
  missing,
});

test("rebuilt months draw a dashed line that reaches the first recorded month", () => {
  const points = toCurvePoints([
    point("2022-01", 400, true),
    point("2022-02", 300, true),
    point("2026-10", 2000, false),
    point("2026-11", 2100, false),
  ]);
  assert.deepEqual(points.map((p) => p.rebuilt), [400, 300, 2000, null]);
  assert.deepEqual(points.map((p) => p.recorded), [null, null, 2000, 2100]);
});

test("a month nothing is known for breaks both lines", () => {
  const points = toCurvePoints([point("2022-12", 300, true), point("2023-01", null, false), point("2023-02", 250, true)]);
  assert.deepEqual(points.map((p) => p.rebuilt), [300, null, 250]);
  assert.deepEqual(points.map((p) => p.recorded), [null, null, null]);
});

const gaps = [
  { source: "neon", label: "Neon", start: null, end: "2026-04-30", reason: "" },
  { source: "binance", label: "Binance", start: "2023-01-15", end: "2024-03-25", reason: "" },
  { source: "wise", label: "Wise", start: "2025-12-04", end: null, reason: "" },
  { source: "ibkr", label: "IBKR", start: "2019-01-01", end: "2019-06-30", reason: "" },
];

test("a point names the sources it leaves out by their labels", () => {
  assert.deepEqual(missingLabels(point("2023-02", null, false, ["binance", "neon", "other"]), gaps), ["Binance", "Neon", "other"]);
});
