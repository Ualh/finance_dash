import { test } from "node:test";
import assert from "node:assert/strict";

import { curveAxis, toCurvePoints } from "./curve.ts";

const history = [
  { month: "2026-06", date: "2026-06-23", total_chf: 0 },
  { month: "2026-10", date: "2026-10-25", total_chf: 1800.83 },
  { month: "2026-11", date: "2026-11-20", total_chf: 3391.17 },
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
    { month: "2025-11", date: "2025-11-15", total_chf: 1 },
    { month: "2026-11", date: "2026-11-20", total_chf: 2 },
  ];
  const axis = curveAxis(toCurvePoints(year));
  assert.equal(axis.byYear, false);
  assert.deepEqual(axis.ticks, [11, 13, 15, 17, 19, 21].map((m) => Date.UTC(2025, m, 1)));
});

test("a history of several years is labelled on year starts", () => {
  const long = [
    { month: "2022-01", date: "2022-01-28", total_chf: 100 },
    { month: "2026-11", date: "2026-11-20", total_chf: 3391.17 },
  ];
  const axis = curveAxis(toCurvePoints(long));
  assert.equal(axis.byYear, true);
  assert.deepEqual(axis.ticks, [2023, 2024, 2025, 2026].map((y) => Date.UTC(y, 0, 1)));
});

test("a very long history keeps at most six year ticks", () => {
  const decade = [
    { month: "2011-03", date: "2011-03-01", total_chf: 1 },
    { month: "2026-11", date: "2026-11-20", total_chf: 2 },
  ];
  const { ticks } = curveAxis(toCurvePoints(decade));
  assert.deepEqual(ticks, [2012, 2015, 2018, 2021, 2024].map((y) => Date.UTC(y, 0, 1)));
});
