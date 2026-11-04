import { test } from "node:test";
import assert from "node:assert/strict";

import { resolveApiBaseUrl } from "./apiBaseUrl.ts";

const ORIGIN = "http://100.64.0.1:8001";

test("empty VITE_API_BASE_URL in a production build uses the page origin (regression: Invalid base URL)", () => {
  const base = resolveApiBaseUrl("", false, ORIGIN);
  assert.equal(base, ORIGIN);
  // The ApiClient builds every request URL this way; it threw with the old `??` fallback.
  assert.equal(new URL("dashboard", `${base}/`).toString(), `${ORIGIN}/dashboard`);
});

test("missing VITE_API_BASE_URL in production uses the page origin", () => {
  assert.equal(resolveApiBaseUrl(undefined, false, ORIGIN), ORIGIN);
});

test("missing VITE_API_BASE_URL in vite dev uses the local backend", () => {
  assert.equal(resolveApiBaseUrl(undefined, true, ORIGIN), "http://127.0.0.1:8000");
  assert.equal(resolveApiBaseUrl("  ", true, ORIGIN), "http://127.0.0.1:8000");
});

test("an explicit VITE_API_BASE_URL wins", () => {
  assert.equal(resolveApiBaseUrl("http://api.local:9000", false, ORIGIN), "http://api.local:9000");
});
