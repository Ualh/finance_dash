import { test } from "node:test";
import assert from "node:assert/strict";

import { formatChange, formatDay, formatMonthLong, formatMonthShort } from "./format.ts";

const strip = (s: string) => s.replace(/[\s  ’']/g, "");

test("change always carries its sign", () => {
  assert.equal(strip(formatChange(1500.4)), "+CHF1500");
  assert.equal(strip(formatChange(-200)), "−CHF200");
  assert.equal(strip(formatChange(0.2)), "±CHF0");
});

test("month labels", () => {
  assert.equal(formatMonthShort("2026-11"), "Nov");
  assert.equal(formatMonthLong("2026-01"), "January 2026");
});

test("day labels show the year only when it differs", () => {
  assert.equal(formatDay("2026-06-03", 2026), "3 Jun");
  assert.equal(formatDay("2025-12-31T10:00:00+00:00", 2026), "31 Dec 2025");
});
