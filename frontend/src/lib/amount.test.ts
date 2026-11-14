import { test } from "node:test";
import assert from "node:assert/strict";

import { parsePositiveAmount } from "./amount.ts";

test("a plain number is accepted", () => {
  assert.deepEqual(parsePositiveAmount("42500"), { ok: true, value: 42500 });
});

test("decimals and Swiss thousands separators are accepted", () => {
  assert.deepEqual(parsePositiveAmount("42'500.75"), { ok: true, value: 42500.75 });
  assert.deepEqual(parsePositiveAmount(" 1’250 "), { ok: true, value: 1250 });
});

test("text mixed into a number is rejected, not silently trimmed", () => {
  for (const text of ["42500abc", "abc", "12.3.4", "1e5", "", "  "]) {
    const result = parsePositiveAmount(text);
    assert.equal(result.ok, false, text);
  }
});

test("zero and negative amounts are rejected", () => {
  for (const text of ["0", "0.00", "-5", "-0.5"]) {
    const result = parsePositiveAmount(text);
    assert.equal(result.ok, false, text);
  }
});

test("the rejection says what is wrong", () => {
  assert.deepEqual(parsePositiveAmount("42500abc"), { ok: false, message: "Enter a number, for example 42500 or 1250.75." });
  assert.deepEqual(parsePositiveAmount("-5"), { ok: false, message: "Enter an amount greater than zero." });
});
