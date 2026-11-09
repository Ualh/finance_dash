# finance_dash verification map

This directory is the maintained source for verifying the user-facing behavior of finance_dash. Read this index before driving the app, then use the matching feature file as the recipe. `S` below is `.claude/skills/verify-finance-dash/scripts/control.sh` and `RUN` is your run id (see `../SKILL.md`).

## Baseline preconditions

- A fresh instance from `$S launch $RUN`: empty scratch database, blank source credentials, outbound HTTP blocked. Nothing is seeded; a fresh instance shows net worth `CHF 0`, Neon and Finpension `Never`, `Synced never`, `Neon CSV imported never`.
- `$S doctor $RUN` prints only `ok` lines.
- `CHROME_DEVTOOLS_AXI_EXECUTABLE_PATH` points at a Chrome binary (see `../SKILL.md`, Drive).
- The page is open and at phone width: `$S browser $RUN open "$($S url $RUN)/"`, then `$S browser $RUN resize 390 844`. Resize after the first `open`: on a new bridge, `open` moves to a new tab and a resize done before it is lost.
- Never drive an instance this run did not launch.

## Driving conventions

- Start every recipe from the baseline unless its preconditions say otherwise. A recipe that needs data says how to create it, through the UI where a user path exists.
- Find elements with `$S ref $RUN '<role> "<name>"'` exactly as the snapshot prints them, then pass the printed `@ref` to `click`, `fill` or `upload`. Never reuse a ref after another action.
- Pages: Dashboard `/`, Update `/update`, Settings `/settings`. At phone width the bottom tab bar has `link "📊 Dashboard"`, `link "✏️ Update"` and `link "⚙️ Settings"`.
- Date fields (`Date` group): `fill` does not reach React. Click the `spinbutton "Month"` (or `spinbutton "Month Month"` on the Update page), then `$S browser $RUN type MMDDYYYY`.
- Amounts are typed plain (`42000`). The page prints them Swiss-style with a no-break space after the currency (`CHF 42'000`, `CHF 1'350.00` as written in this map). Assert on the words around the number and on the stored value via `sql`; never pass an amount to `ref`.
- Never click `button "Noter"` and never type in `textbox "Observation"`: that widget posts to the captain's real notes service.
- Treat every command as literal. Keep quoted names unchanged, including the emoji in tab names.

## Proof and skip reporting

- Capture the user action and the resulting state, not only the final screen: save the snapshot each action prints (`| tee <proof>/NN-<step>.aria.txt`) and a screenshot (`$S browser $RUN screenshot <proof>/NN-<step>.png`).
- Mutation proof includes a second, read-only view: the Dashboard or Settings page reopened, plus `$S sql $RUN "…"` of the stored row.
- Record the feature ID and the entry point used with every artifact (file names or `transcript.md`).
- Report an unreachable path with the command tried and the missing precondition. Do not report a skipped entry point as verified through a different one.
- Proof survives `$S stop $RUN`; check the proof dir after cleanup.

## Feature entry contract

Each feature file starts with an H1 title and one paragraph describing the user-visible behavior. It then uses exactly four H2 sections in this order.

1. `Sub-features` lists short IDs with one line for each behavior.
2. `How to get to it (user POV)` lists every user entry point.
3. `Driving it with control.sh` starts with `Preconditions:` and uses labeled bullets that pair each user action with an exact command and observable result.
4. `Gotchas` lists traps that can waste or invalidate a verification run.

Keep implementation details out of the map. Name only user paths, stable handles, required state, commands, and observable proof.

## Features

- [Dashboard](./dashboard.md) covers net worth, the source rows and their staleness, spending, the currency toggle and the sync button (a dry run here).
- [Neon CSV upload](./neon-csv.md) covers the monthly statement upload, re-upload of the same file, and the Neon anchor in Settings.
- [Finpension value](./finpension.md) covers the monthly Finpension figure typed on the Update page.
- [Cash withdrawals](./cash-withdrawals.md) covers recording, listing and deleting cash, and its line under spending.
- [Other holdings](./other-holdings.md) covers adding a manual holding on the Update page and editing its value in Settings.

Not mapped yet: the theme toggle (header button and Settings), the `/freshness` reminder endpoint (API only), and the history backfill and backup CLIs (real accounts or files outside the instance).
