import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

test("the phone tab bar starts to the right of the LLM Monitor bubble, which sits bottom-left", () => {
  assert.match(read("../App.tsx"), /<nav className="[^"]*\bpl-32\b[^"]*\bmd:hidden\b/);
});
