// Tests for scripts/floor-guard.mjs, run against throwaway git repos through its CLI.
// Run: node --test scripts/floor-guard.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const GUARD = join(dirname(fileURLToPath(import.meta.url)), 'floor-guard.mjs');

// A repo whose `main` holds `base`, with `change` applied on top on a `work` branch, as
// uncommitted work unless `commit` is set. A file mapped to null is deleted.
function repo(base, change, { commit = false } = {}) {
  const dir = mkdtempSync(join(tmpdir(), 'floor-guard-'));
  const git = (...args) => execFileSync('git', args, { cwd: dir, stdio: 'pipe' });
  const write = (files) => {
    for (const [path, text] of Object.entries(files)) {
      const full = join(dir, path);
      if (text === null) { rmSync(full); continue; }
      mkdirSync(dirname(full), { recursive: true });
      writeFileSync(full, text);
    }
  };
  git('init', '-q', '-b', 'main');
  git('config', 'user.email', 'test@example.invalid');
  git('config', 'user.name', 'test');
  write({ 'README.md': 'base\n', ...base });
  git('add', '-A');
  git('commit', '-q', '-m', 'base');
  git('checkout', '-q', '-b', 'work');
  write(change);
  if (commit) {
    git('add', '-A');
    git('commit', '-q', '-m', 'change');
  }
  return dir;
}

function guard(base, change, opts) {
  const dir = repo(base, change, opts);
  try {
    const r = spawnSync('node', [GUARD, '--base', 'main'], { cwd: dir, encoding: 'utf8' });
    return { code: r.status, out: r.stdout + r.stderr };
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

test('a change that keeps the bar is clean', () => {
  const r = guard({ 'src/a.ts': 'export const a = 1;\n' }, { 'src/a.ts': 'export const a = 2;\n' });
  assert.equal(r.code, 0, r.out);
});

test('a new TypeScript suppression is flagged', () => {
  const r = guard({ 'src/a.ts': 'export const a = 1;\n' }, { 'src/a.ts': '// @ts-ignore\nexport const a = 1;\n' });
  assert.equal(r.code, 1, r.out);
  assert.match(r.out, /\[silenced-checker\] src\/a\.ts/);
});

test('an unknown base is an error, never clean', () => {
  const dir = repo({}, {});
  try {
    const r = spawnSync('node', [GUARD, '--base', 'no-such-ref'], { cwd: dir, encoding: 'utf8' });
    assert.equal(r.status, 2, r.stdout + r.stderr);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('Python and node:test ways of lowering the bar are flagged', () => {
  const cases = [
    ['backend/x.py', 'x = 1  # pragma: no cover\n', 'silenced-checker'],
    ['backend/x.py', 'run(cmd)  # nosec\n', 'silenced-checker'],
    ['backend/x.py', 'x = f()  # pyright: ignore\n', 'silenced-checker'],
    ['src/a.ts', '// @ts-expect-error\n', 'silenced-checker'],
    ['backend/tests/test_x.py', '@pytest.mark.xfail\n', 'test-made-easier'],
    ['backend/tests/test_x.py', '    pytest.skip("flaky")\n', 'test-made-easier'],
    ['src/a.test.ts', "test('a', { skip: true }, () => {});\n", 'test-made-easier'],
    ['backend/x.py', '    raise NotImplementedError\n', 'unfinished-work'],
    ['backend/x.py', 'except Exception: pass\n', 'unfinished-work'],
  ];
  for (const [file, line, rule] of cases) {
    const r = guard({ [file]: 'ok = 1\n' }, { [file]: 'ok = 1\n' + line });
    assert.equal(r.code, 1, `${line.trim()}: ${r.out}`);
    assert.ok(r.out.includes(`[${rule}] ${file}`), `${line.trim()}: ${r.out}`);
  }
});

test('changing an expected value is not an assertion removed', () => {
  const r = guard(
    { 'backend/tests/test_x.py': 'def test_a():\n    assert f() == 1\n' },
    { 'backend/tests/test_x.py': 'def test_a():\n    assert f() == 2\n' },
  );
  assert.equal(r.code, 0, r.out);
});

test('a test file that loses assertions is flagged', () => {
  const r = guard(
    { 'backend/tests/test_x.py': 'def test_a():\n    assert f() == 1\n    assert g() == 2\n' },
    { 'backend/tests/test_x.py': 'def test_a():\n    assert f() == 1\n' },
  );
  assert.equal(r.code, 1, r.out);
  assert.match(r.out, /\[assertion-removed\] backend\/tests\/test_x\.py: assert g\(\) == 2/);
});

test('removing a pytest.raises check or a conftest fixture body counts as an assertion removed', () => {
  const raises = guard(
    { 'backend/tests/test_x.py': 'def test_a():\n    with pytest.raises(ValueError):\n        f()\n' },
    { 'backend/tests/test_x.py': 'def test_a():\n    f()\n' },
  );
  assert.equal(raises.code, 1, raises.out);
  const conftest = guard(
    { 'backend/conftest.py': 'def check():\n    assert ok()\n' },
    { 'backend/conftest.py': 'def check():\n    pass\n' },
  );
  assert.equal(conftest.code, 1, conftest.out);
});

test('prose may name suppressions and TODOs: markdown is not code', () => {
  const r = guard({}, { 'docs/notes.md': 'TODO: explain why `# noqa` and `.skip` are banned\n' });
  assert.equal(r.code, 0, r.out);
});

test('the guard files may contain the patterns they look for when they first land', () => {
  const r = guard({}, {
    'scripts/floor-guard.mjs': 'const SUPPRESSIONS = /@ts-ignore|TODO/;\n',
    'scripts/floor-guard.test.mjs': "test('x', { skip: true });\n",
    'scripts/check': '#!/bin/sh\n',
  });
  assert.equal(r.code, 0, r.out);
});

test('changing or deleting a guard file that is already on the base is flagged', () => {
  const base = {
    'scripts/check': '#!/bin/sh\nrun pytest\n',
    '.github/workflows/constraints.yml': 'on: pull_request\n',
    '.coveragerc': '[run]\nsource = backend\n',
  };
  const edited = guard(base, { 'scripts/check': '#!/bin/sh\n' });
  assert.equal(edited.code, 1, edited.out);
  assert.match(edited.out, /\[guard-changed\] scripts\/check/);
  const removed = guard(base, { '.github/workflows/constraints.yml': null });
  assert.equal(removed.code, 1, removed.out);
  assert.match(removed.out, /\[guard-changed\] \.github\/workflows\/constraints\.yml/);
  const omitted = guard(base, { '.coveragerc': '[run]\nsource = backend\nomit = backend/api.py\n' });
  assert.match(omitted.out, /\[guard-changed\] \.coveragerc/);
});

test('renaming a guard file away is a change to it', () => {
  const wf = 'on: pull_request\njobs:\n  check:\n    runs-on: ubuntu-latest\n    steps:\n      - run: scripts/check task\n';
  const r = guard(
    { '.github/workflows/constraints.yml': wf },
    { '.github/workflows/constraints.yml': null, '.github/workflows/other.yml': wf.replace('task', 'fast') },
    { commit: true },
  );
  assert.equal(r.code, 1, r.out);
  assert.match(r.out, /\[guard-changed\] \.github\/workflows\/constraints\.yml/);
});
