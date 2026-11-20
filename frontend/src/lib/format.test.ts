import { test } from "node:test";
import assert from "node:assert/strict";

import { daysAgo, formatChange, formatDay, formatMoment, formatGaps, formatMonthLong, formatMonthShort, formatMonthYear, formatYear } from "./format.ts";

const strip = (s: string) => s.replace(/[\s  ’']/g, "");

test("change always carries its sign", () => {
  assert.equal(strip(formatChange(1500.4)), "+CHF1500");
  assert.equal(strip(formatChange(-200)), "−CHF200");
  assert.equal(strip(formatChange(0.2)), "±CHF0");
});

test("month labels", () => {
  assert.equal(formatMonthShort(Date.UTC(2026, 10, 1)), "Nov");
  assert.equal(formatYear(Date.UTC(2023, 0, 1)), "2023");
  assert.equal(formatMonthLong("2026-01"), "January 2026");
  assert.equal(formatMonthYear("2023-01-15"), "Jan 2023");
  assert.equal(formatMonthYear("2026-11"), "Nov 2026");
});

test("day labels show the year only when it differs", () => {
  assert.equal(formatDay("2026-06-03", 2026), "3 Jun");
  assert.equal(formatDay("2025-12-31T10:00:00+00:00", 2026), "31 Dec 2025");
});

test("moments read as today, yesterday, or a day", () => {
  const now = new Date(2026, 10, 4, 12, 0);
  assert.equal(formatMoment(new Date(2026, 10, 4, 6, 5).toISOString(), now), "today 06:05");
  assert.equal(formatMoment(new Date(2026, 10, 3, 23, 59).toISOString(), now), "yesterday 23:59");
  assert.equal(formatMoment(new Date(2026, 5, 26, 9, 0).toISOString(), now), "26 Jun");
  assert.equal(formatMoment(new Date(2025, 11, 31, 9, 0).toISOString(), now), "31 Dec 2025");
  assert.equal(daysAgo(new Date(2026, 9, 1, 8, 0).toISOString(), now), 34);
});

test("gaps read as month ranges, leaving out those before the curve starts", () => {
  const gaps = [
    { source: "neon", label: "Neon", start: null, end: "2026-04-30", reason: "" },
    { source: "binance", label: "Binance", start: "2023-01-15", end: "2024-03-25", reason: "" },
    { source: "wise", label: "Wise", start: "2025-12-04", end: null, reason: "" },
    { source: "ibkr", label: "IBKR", start: "2019-01-01", end: "2019-06-30", reason: "" },
  ];
  assert.deepEqual(formatGaps(gaps, "2022-01-31"), ["Neon until Apr 2026", "Binance Jan 2023 – Mar 2024", "Wise from Dec 2025"]);
});
