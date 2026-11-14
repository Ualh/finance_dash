import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

test("the Noter button rises by --ship-notes-lift", () => {
  assert.match(read("../../public/notes.js"), /\.pill\{bottom:calc\([^}]*var\(--ship-notes-lift,0px\)\)/);
});

test("the phone tab bar lifts the Noter button by its own height, and only below md", () => {
  const css = read("../styles.css");
  assert.match(css, /@media \(max-width: 767\.98px\)\s*\{\s*:root\s*\{\s*--ship-notes-lift: 4rem;/);
  assert.match(read("../App.tsx"), /<nav className="[^"]*\bmd:hidden\b/);
});
