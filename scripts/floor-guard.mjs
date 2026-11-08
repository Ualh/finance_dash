#!/usr/bin/env node
// floor-guard.mjs — diff-scoped enforcement of the CONSTRAINTS.md floor.
// Usage: node floor-guard.mjs [--base <ref>]   (default base: origin/main)
//
// Adapted for finance_dash from addyosmani/agent-skills@301b02b
// (skills/constraint-driven-development/references/floor-guard.md). Every departure from the
// reference is marked `finance_dash` below; scripts/floor-guard.test.mjs covers them.
import { execFileSync } from 'node:child_process';

const base = (() => {
  const i = process.argv.indexOf('--base');
  return i > -1 ? process.argv[i + 1] : 'origin/main';
})();

// `git diff --no-index` exits 1 whenever the two sides differ, which is the normal case for a
// new file, so that output is kept. Any other failure is null, and null never reads as clean.
const git = (args, { diffExit = false } = {}) => {
  try { return execFileSync('git', args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }); }
  catch (e) { return diffExit && e.status === 1 && typeof e.stdout === 'string' ? e.stdout : null; }
};
const bail = (msg) => { console.error('floor-guard: ' + msg); process.exit(2); };

// Run from the top of the work tree. `git ls-files` lists only the current directory's subtree,
// relative to it, so a guard started in a subfolder would miss untracked files elsewhere and name
// the rest differently from `git diff`, which always covers the whole tree.
const top = git(['rev-parse', '--show-toplevel'])?.trim();
if (!top) bail('not inside a git work tree');
process.chdir(top);

// Merge base; bail to exit 2 rather than pretending a shallow/rootless clone is clean.
const mergeBase = git(['merge-base', base, 'HEAD'])?.trim();
if (!mergeBase) bail('no merge base against ' + base);

// Unified diff plus untracked files (git diff alone cannot see new files).
// finance_dash: --no-renames, so a renamed file reads as deleted plus created and a guard file
// or test file renamed away is still seen leaving.
const tracked = git(['diff', '--no-renames', '--unified=0', mergeBase, '--']);
if (tracked === null) bail('could not diff against ' + mergeBase);
const untrackedFiles = git(['ls-files', '--others', '--exclude-standard']);
if (untrackedFiles === null) bail('could not list untracked files');
const untracked = untrackedFiles.split('\n').filter(Boolean).map((f) => {
  const d = git(['diff', '--no-index', '--unified=0', '/dev/null', f], { diffExit: true });
  if (d === null) bail('could not diff untracked file ' + f);
  return d;
}).join('\n');
const diff = tracked + '\n' + untracked;

// Walk the diff. `---` and `+++` are file headers only between a file's `diff` line and its first
// `@@` hunk; inside a hunk every line is content, so an added `++i` (shown as `+++i`) or a removed
// `-- comment` is a change, not a header. Both headers name the file, so a deletion
// (`+++ /dev/null`) keeps its name.
const added = [], removed = [], deleted = [], created = [];
const pathOf = (s) => s.replace(/^[ab]\//, '');
let file = '', oldFile = '', inHeader = false;
for (const line of diff.split('\n')) {
  if (line.startsWith('diff ')) inHeader = true;
  else if (line.startsWith('@@')) inHeader = false;
  else if (inHeader) {
    if (line.startsWith('--- ')) oldFile = pathOf(line.slice(4));
    else if (line.startsWith('+++ ')) {
      const newFile = pathOf(line.slice(4));
      file = newFile === '/dev/null' ? oldFile : newFile;
      if (newFile === '/dev/null') deleted.push(file);
      if (oldFile === '/dev/null') created.push(file);
    }
  }
  else if (line.startsWith('+')) added.push({ file, text: line.slice(1) });
  else if (line.startsWith('-')) removed.push({ file, text: line.slice(1) });
}

const findings = [];
const flag = (rule, f, text) => findings.push({ rule, file: f, text: text.trim().slice(0, 120) });
// finance_dash adds pytest's conftest.py, where shared fixtures and their checks live.
const isTest = (f) => /\.(test|spec)\.|_test\.|test_|(^|\/)conftest\.py$/.test(f);
const isConstraints = (f) => /CONSTRAINTS\.md$/.test(f);
// finance_dash: the files that run the bar. They contain the very patterns they look for, so the
// pattern checks skip them, and any change to one already on the base is reported instead: a human
// reviews a change to the guard, an agent does not make it to get to green.
const GUARD_FILES = new Set([
  'scripts/floor-guard.mjs', 'scripts/floor-guard.test.mjs', 'scripts/quality-gate.mjs',
  'scripts/check', '.github/workflows/constraints.yml', '.coveragerc',
  // The checkers' own configs: turning a rule or `strict` off lowers the bar as surely as a comment.
  'frontend/eslint.config.js', 'frontend/tsconfig.json', 'frontend/tsconfig.node.json',
]);
// Prose cannot silence a checker, and it may name the patterns, so markdown skips the pattern checks.
const patternChecked = (f) => !GUARD_FILES.has(f) && !/\.md$/i.test(f);

// 1. Silenced checker — extend this list for your ecosystem.
// finance_dash adds the TypeScript and Python forms its stack uses: @ts-expect-error, coverage.py's
// `pragma: no cover` (the Python `istanbul ignore`), bandit's `nosec` and pyright's ignore.
const SUPPRESSIONS = /@ts-ignore|@ts-nocheck|@ts-expect-error|eslint-disable|biome-ignore|# *noqa|# *type: *ignore|# *pyright: *ignore|# *nosec\b|pragma: *no *cover|istanbul ignore|nosemgrep|gitleaks:allow|Stryker disable/;
// 4. Unfinished work.
// finance_dash adds Python's stub and swallowed exception: `raise NotImplementedError`, `except ...: pass`.
const STUBS = /throw new (Error|NotImplemented).*[Nn]ot implemented|catch\s*\(\w*\)\s*\{\s*\}|catch\s*\{\s*\}|\bTODO\b|\bpass\s*# *stub|\braise NotImplementedError\b|\bexcept\b[^:]*:\s*pass\b/;
// 2. A test made easier (added skips).
// finance_dash adds pytest's xfail and node:test's `{ skip: ... }` / `{ todo: ... }` options.
const SKIPS = /\.(skip|todo)\b|\bxit\(|\bxdescribe\(|@pytest\.mark\.skip|t\.Skip\(|\bxfail\b|\b(skip|todo)\s*:\s*(true|['"`])/;

// finance_dash: Python's usual swallowed exception spans two lines, `except X:` then `pass`.
const EXCEPT_OPEN = /^\s*except\b[^:]*:\s*(#.*)?$/;
const BARE_PASS = /^\s*pass\s*(#.*)?$/;
added.forEach(({ file, text }, i) => {
  if (patternChecked(file)) {
    if (SUPPRESSIONS.test(text)) flag('silenced-checker', file, text);
    if (STUBS.test(text)) flag('unfinished-work', file, text);
    if (SKIPS.test(text)) flag('test-made-easier', file, text);
    const prev = added[i - 1];
    if (BARE_PASS.test(text) && prev?.file === file && EXCEPT_OPEN.test(prev.text)) {
      flag('unfinished-work', file, text);
    }
  }
  if (isConstraints(file) && /^\| *(W|E)\d+ *\|/.test(text)) flag('new-exception', file, text);
});

// 1c. A guard file that is on the base changed or went away (finance_dash).
const touched = new Set([...added, ...removed].map((l) => l.file).concat(deleted));
for (const f of touched) {
  if (GUARD_FILES.has(f) && !created.includes(f)) {
    flag('guard-changed', f, deleted.includes(f) ? 'file deleted' : 'file changed');
  }
}

// 2b. A test file deleted, or an assertion removed from a test file that still exists.
// finance_dash change: an edited assertion shows as one removed and one added line, so a file is
// flagged only when it loses assertion lines on balance; then each removed assertion is listed.
// `raises` covers pytest.raises; `assert\w*` covers unittest's assertEqual and node's assert.equal.
const ASSERTION = /\b(expect|assert\w*|should|raises)\b/;
for (const f of deleted) if (isTest(f)) flag('test-deleted', f, 'file deleted');
// An assertion that cannot fail is an assertion removed, whatever the count says.
const TRIVIAL = /\bassert\s+(True|1)\b|\bassert(\.ok)?\(\s*(true|1)\s*\)|\bexpect\(\s*true\s*\)/;
for (const { file, text } of added) {
  if (isTest(file) && patternChecked(file) && TRIVIAL.test(text)) flag('assertion-removed', file, text);
}
const assertionCount = (lines, f) => lines.filter((l) => l.file === f && ASSERTION.test(l.text)).length;
for (const f of new Set(removed.map((l) => l.file))) {
  if (!isTest(f) || deleted.includes(f) || assertionCount(removed, f) <= assertionCount(added, f)) continue;
  for (const { text } of removed.filter((l) => l.file === f && ASSERTION.test(l.text))) {
    flag('assertion-removed', f, text);
  }
}

// 1b/2c. A rule in CONSTRAINTS.md weakened or removed. A rule is a floor bullet or a table row,
// identified by the bullet's text before its first colon or by the row's first cell. Each number
// carries a direction read from the words around it: a minimum (>=, at least, must not fall) is
// loosened by going down, a maximum (<=, at most, under, must not grow) by going up. A number whose
// direction cannot be read is reported whenever it changes, because the guard cannot tell
// tightening from loosening and staying quiet is the wrong default. Numbers are paired within
// their direction (the first minimum with the first minimum, and so on), so a number added
// elsewhere in the text does not shift the pairing; a threshold with no counterpart after the
// edit was removed, and an added one tightens.
const ruleKey = (t) => {
  const s = t.trim();
  if (s.startsWith('|')) return s.split('|').map((c) => c.trim()).filter(Boolean)[0] ?? '';
  if (/^[-*] /.test(s)) return s.slice(2).split(':')[0].trim();
  return null; // prose, headings, dates: not a rule
};
const isException = (t) => /^\| *(W|E)\d+ *\|/.test(t.trim());
const MIN_BEFORE = /(>=|>|≥|at least|minimum|\bmin\b|no less than|not fall|not drop)\s*$/;
const MAX_BEFORE = /(<=|<|≤|at most|maximum|\bmax\b|no more than|under|below|not grow|not exceed)\s*$/;
const MIN_AFTER = /^\s*\S*\s*(?:\|\s*)?(or more|or higher|must not fall|must not drop)/;
const MAX_AFTER = /^\s*\S*\s*(?:\|\s*)?(or less|or lower|must not grow|must not exceed)/;
const thresholds = (t) => {
  const out = [], re = /\d+(?:\.\d+)?/g;
  let m;
  while ((m = re.exec(t))) {
    const before = t.slice(Math.max(0, m.index - 24), m.index).toLowerCase();
    const after = t.slice(m.index + m[0].length, m.index + m[0].length + 40).toLowerCase();
    const dir = MIN_BEFORE.test(before) || MIN_AFTER.test(after) ? 'min'
      : MAX_BEFORE.test(before) || MAX_AFTER.test(after) ? 'max' : null;
    out.push({ n: Number(m[0]), dir });
  }
  return out;
};
const removedRules = removed.filter((l) => isConstraints(l.file) && ruleKey(l.text) !== null);
const addedRules = added.filter((l) => isConstraints(l.file) && ruleKey(l.text) !== null);
for (const r of removedRules) {
  const a = addedRules.find((x) => ruleKey(x.text) === ruleKey(r.text));
  if (!a) {
    if (!isException(r.text)) flag('rule-removed', r.file, r.text); // dropping an exception tightens: silent
    continue;
  }
  const before = thresholds(r.text), after = thresholds(a.text);
  let verdict = null;
  for (const dir of ['min', 'max', null]) {
    const was = before.filter((x) => x.dir === dir), now = after.filter((x) => x.dir === dir);
    was.forEach((b, i) => {
      const n = now[i];
      if (verdict) return;
      if (!n) verdict = 'threshold-removed';
      else if (n.n === b.n) return;
      else if (dir === 'min' ? n.n < b.n : dir === 'max' ? n.n > b.n : true) {
        verdict = dir ? 'threshold-loosened' : 'threshold-changed';
      }
    });
  }
  if (verdict) flag(verdict, r.file, r.text + '  ->  ' + a.text);
}

if (findings.length === 0) { console.log('floor-guard: clean'); process.exit(0); }
console.error('floor-guard: ' + findings.length + ' floor violation(s):');
for (const f of findings) console.error(`  [${f.rule}] ${f.file}: ${f.text}`);
if (findings.some((f) => f.rule === 'rule-removed')) {
  console.error('\nA rule-removed finding can also mean the rule\'s label changed: rename a rule in one commit and change its thresholds in another.');
}
if (findings.some((f) => f.rule === 'threshold-removed')) {
  console.error('\nA threshold-removed finding can also mean a number gained or lost its direction words (">= 80%" becoming "80%", or the reverse): compare the two lines before assuming a threshold was deleted.');
}
if (findings.some((f) => f.rule === 'guard-changed')) {
  console.error('\nA guard-changed finding means a file that runs the checks changed. That is a human\'s call: leave it for review rather than working around it.');
}
console.error('\nEach is a move that lowers the bar. Fix the code, or route it through a tracked exception.');
process.exit(1);
