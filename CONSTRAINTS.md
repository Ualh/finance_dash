# Constraints

Last reviewed: 2026-11-08, first version, written from the captain's common floor and the
`constraint-driven-development` defaults (addyosmani/agent-skills@301b02b).

This is finance_dash's quality bar. A change is done when `scripts/check task` passes. This file is
the source of truth: `scripts/check` mirrors it, and if the two disagree, this file wins.

## Running the checks

| Entry point | Command | When | Budget |
|-------------|---------|------|--------|
| `check:fast` | `scripts/check fast` | after every edit | a few seconds |
| `check:task` | `scripts/check task` | before handing work back or opening a PR | about 90 s |
| CI | `.github/workflows/constraints.yml` runs `scripts/check task` | every pull request | unlimited |

Setup, once per checkout: `pip install -r requirements.txt -r requirements-dev.txt` (into `.venv`,
which `scripts/check` uses when it exists) and `npm --prefix frontend ci`. The diff-scoped checks
compare against `origin/main`, the PR base; set `CHECK_BASE` to use another ref.
gitleaks, osv-scanner and semgrep are installed in CI only. Locally, `scripts/check` skips them
with a notice when they are missing. In CI, a missing scanner fails the run.

A red PR is not merged. Fix the code; do not weaken this file or the checks to get to green.

## Floor (always enforced, blocks)

- No new suppression comment: `@ts-ignore`, `@ts-nocheck`, `@ts-expect-error`, `eslint-disable`, `# noqa`, `# type: ignore`, `# pyright: ignore`, `# nosec`, `# pragma: no cover`, `istanbul ignore`, `nosemgrep`, `gitleaks:allow`
- No unimplemented stub or swallowed error: `throw new Error("Not implemented")`, `raise NotImplementedError`, an empty `catch {}`, `except ...: pass`, a `TODO` where the code should be
- No easier tests: no test deleted, skipped (`.skip`, `{ skip: true }`, `pytest.skip`, `@pytest.mark.skip`) or marked `xfail`, no test file that ends up with fewer assertions, and no assertion that cannot fail (`assert True`, `assert.ok(true)`)
- No lowered bar: no threshold in this file lowered or removed, and no new Exceptions row nobody discussed
- No change to the guard without a human: `scripts/check`, `scripts/floor-guard.mjs`, its tests, `scripts/quality-gate.mjs`, `.coveragerc`, the CI workflow and the checker configs (`frontend/eslint.config.js`, `frontend/tsconfig*.json`) fail the floor guard when changed
- Existing tests, type checks and lint stay green
- No secrets in source

The first five are checked on the diff against the PR base by `scripts/floor-guard.mjs`, adapted
from the skill's reference floor guard. Markdown files are not scanned for the patterns, since
prose cannot silence a checker. A finding blocks: fix the code, or bring the case to a human.

Changing the guard is a human's decision. A PR that changes a guard file stays red by design, and
no agent can clear that. The captain reviews it and merges it by hand, which is the only way a red
PR lands. Agents put guard changes in a PR of their own and say so in the PR body.

The assertion check counts assertion lines per test file. Changing an expected value passes. A
file that loses assertions overall, or gains one that cannot fail, is flagged. Assertions moved
from one test to another in the same file are not told apart from a rewrite.

## Enforced

| Dimension | Rule | Checked by | Runs at | On failure |
|-----------|------|-----------|---------|------------|
| Floor | the five diff rules above | `node scripts/floor-guard.mjs --base origin/main` | fast, task, CI | block |
| Floor guard | its own tests pass | `node --test scripts/floor-guard.test.mjs` | task, CI | block |
| Types (frontend) | zero type errors | `frontend/node_modules/.bin/tsc --noEmit -p frontend` | fast, task, CI | block |
| Lint (frontend) | zero ESLint errors from the project config (warnings allowed) | `npm --prefix frontend run lint` | fast, task, CI | block |
| Tests (backend) | every pytest test passes | `python -m pytest --cov` | task, CI | block |
| Tests (frontend) | every node:test test passes | `node --test 'src/**/*.test.ts'` in `frontend/` | task, CI | block |
| Secrets | no secret in the commits since the PR base | `gitleaks git --redact --log-opts=<merge-base>..HEAD` | CI, task when installed | block |
| Coverage | changed lines ≥ 80% covered | `diff-cover <pytest lcov> <node lcov> --compare-branch=origin/main` | task, CI | warn |
| Security: dependencies | no known vulnerability, any severity | `osv-scanner scan source -r .` | CI, task when installed | warn |
| Security: code | no semgrep finding at high or above, including `ERROR` | `semgrep scan --config p/default --strict --json` + `node scripts/quality-gate.mjs semgrep` | CI, task when installed | warn |

Why these numbers and levels:

- Block on the floor (which includes keeping existing tests, types, lint and secrets clean), warn on
  the rest: the skill's default, so new checks start as information before they gate anything.
- 80% of changed lines: the skill's default. High enough to require a test, low enough to allow a
  config line. It counts backend Python and the frontend files the node tests load (`src/lib`).
  The React components have no test setup, so their lines are not counted.
- gitleaks runs `--redact` so a matched secret never lands in a log or transcript. It scans the
  commits since the PR base, so commit before relying on it locally.
- Security checks warn rather than block: the dependency baseline below is far from zero, and
  failing every PR on it would teach everyone to ignore red.
  osv-scanner has no severity filter, so it warns on any known vulnerability. That is stricter than
  the skill's "high or above" default, which is harmless while the check only warns.
- diff-cover does the skill's "intersect the coverage report with `git diff`" step and reads both
  lcov reports, so no project-specific script is needed.

## Measured, not yet enforced

`scripts/check task` warns when a coverage line falls more than 0.5 points below the value here.
The 0.5-point margin absorbs drift when an unrelated change moves the total.

| Metric | Today | Direction |
|--------|-------|-----------|
| Backend line coverage | 93.2% | must not fall |
| Frontend line coverage | 100.0% | must not fall |
| Known dependency vulnerabilities (osv-scanner) | 79 | must not grow |
| Semgrep findings (none at high or above) | 5 | must not grow |

Backend coverage is `backend/` without its tests (`.coveragerc`). Frontend coverage covers only
the files the node tests load. Update a value here when it improves. A drop is a finding.

The two security rows come from the first CI run of `scripts/check task` (2026-11-08) and are
compared by reading the CI log, not by a command. The 79 vulnerabilities are 2 critical, 39 high,
33 medium and 5 low, in 28 packages. For Python, osv-scanner reads `requirements.txt`'s `>=` lower
bounds as the versions, so those rows describe the oldest versions allowed, not the ones a fresh
install picks. gitleaks found no leaks.

## Not covered yet

- Python types and lint: the project has no mypy or ruff configuration. Adding one is its own change.
- Accessibility and performance budgets: deliberately left out of this first version.

## Exceptions

| ID | Rule | Path | Reason | Owner | Expires |
|----|------|------|--------|-------|---------|
