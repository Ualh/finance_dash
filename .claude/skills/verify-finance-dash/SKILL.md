---
name: verify-finance-dash
description: Drive finance_dash (the personal net-worth dashboard) through its real web UI in a private, disposable instance and capture proof (screenshots, accessibility snapshots, API and database reads). Use to prove a change to the dashboard, the Update page (Neon CSV, Finpension, cash, other holdings) or Settings actually works in the running app, not only in tests.
---

# Verify finance_dash

finance_dash is a FastAPI app that serves the API and the built React frontend from one process. The captain uses the web UI, mostly on the phone over Tailscale: the Dashboard (net worth, sources, spending), the Update page for the monthly gestures, and Settings. That web UI is the surface this skill drives. Other surfaces, not driven here: the JSON API on its own (`/freshness` feeds the monthly reminder), the history backfill CLI (`python -m backend.history`, real Binance and Wise accounts only) and the backup CLI (`python -m backend.backup`).

Verification means using the real app: build the frontend, start the server, click through the page in a browser, then read the result back from a second view. Tests passing is not proof.

## Never touch the live app

- The live app is `finance-dash.service` on stella, port **8001**, run from `~/Projects/finance_dash` with the captain's real database. Never open, restart, stop or write to it, and never run this skill from that checkout (`control.sh launch` refuses).
- Ports 8000 (dev API) and 5173 (Vite) belong to the captain's dev setup. The helper picks a free port.
- Never put real credentials in the instance. The helper blanks the Binance, Wise and IBKR variables, so a `.env` that `load_dotenv()` finds cannot fill them, and points outbound HTTP at a dead proxy (`127.0.0.1:9`).
- Never click the floating `Noter` button or send its form: it posts a note to the captain's real notes service on the tailnet. (The browser is proxied to nowhere as well, so a stray click fails instead of sending.)

## Helper

Everything goes through `.claude/skills/verify-finance-dash/scripts/control.sh` (executable, verification scaffolding, not product code). Every command takes a run id first; use one per verification run, such as your task id.

```bash
S=.claude/skills/verify-finance-dash/scripts/control.sh   # from the repo root, or use the absolute path
RUN=my-task-id

$S launch    $RUN                    # build frontend, start server, wait until usable
$S doctor    $RUN                    # read-only health and isolation check
$S url       $RUN                    # http://127.0.0.1:<port>
$S proof-dir $RUN                    # create and print the evidence directory
$S browser   $RUN <chrome-devtools-axi args...>   # browser in a session private to this run
$S ref       $RUN 'button "Sync now"'             # current @ref of an element, by role and name
$S api       $RUN GET /holdings      # curl the instance (prints body, then "HTTP <code>")
$S sql       $RUN "select * from holdings"        # read-only query on the instance's database
$S stop      $RUN                    # tear down; proof is kept
```

## Launch

Prerequisites, once per checkout: `.venv` with `requirements.txt` installed and `frontend/node_modules` (`npm --prefix frontend ci`). A task worktree usually has both; `launch` says what is missing.

```bash
$S launch $RUN
# building frontend (same-origin API, as in production)...
# ready: http://127.0.0.1:41234 (pid 12345, db /tmp/finance-dash-verify/<run>/finance_dash.db)
```

What it does: runs `npm run build` with an empty `VITE_API_BASE_URL` (the production build, served by FastAPI from `frontend/dist`), then starts `uvicorn backend.api:app` on `127.0.0.1:<free port>` with `FINANCE_DASH_DB_FILE` in the scratch dir `${TMPDIR:-/tmp}/finance-dash-verify/<run>/`. The schema is created on startup from an empty file, so there is no seed: a fresh instance is a fresh install (net worth `CHF 0`, Neon and Finpension `Never`). Ready means `/dashboard` returns its JSON and `/` serves the built page, not only that the port answers. Startup takes about 6 s. Server log: `<scratch dir>/server.log`; build log: `build.log` next to it.

Options: `FD_VERIFY_PORT=<port>` to choose the port; `FD_VERIFY_ALLOW_FX=1` to let the backend reach the public FX service (`api.frankfurter.dev`, no account). Without it, every currency conversion falls back to rate 1.0 and the page says `Old exchange rate`.

## Doctor

Run it after launch and whenever anything looks off. It is read-only and exits 1 on any `FAIL`.

```bash
$S doctor $RUN
# ok    process 12345 alive and is our uvicorn
# ok    port 41234 listened on by pid 12345
# ok    GET /health answers ok
# ok    GET / serves the built frontend
# ok    database is the scratch file /tmp/finance-dash-verify/<run>/finance_dash.db
# ok    source credentials blank (Binance, Wise, IBKR)
# ok    outbound HTTP goes to the dead proxy
# ok    build is this checkout's HEAD 9ab69b5818b4
```

A HEAD mismatch means you committed or switched since launch: `stop` and `launch` again so the build matches the code under test.

## Drive

The harness is `chrome-devtools-axi`, wrapped by `$S browser $RUN …` so each run has its own bridge (`CHROME_DEVTOOLS_AXI_SESSION=fdverify-<run>`) and a throwaway profile.

Browser binary: stella has no system Chrome. Set `CHROME_DEVTOOLS_AXI_EXECUTABLE_PATH` to a Chrome for Testing binary before the first browser command. Install one into your own task data dir with `npx @puppeteer/browsers install chrome@stable --path <dir>`; an existing one is listed by `ls -d /home/ualh/firstmate/data/*/*/chrome/linux-*/chrome-linux64/chrome`. The wrapper adds `--no-sandbox` for any binary outside `/opt/google/chrome`, because Ubuntu's AppArmor only gives that path the user namespaces Chrome's sandbox needs ("No usable sandbox" otherwise).

Recipe:

```bash
URL=$($S url $RUN)
$S browser $RUN open "$URL/"
$S browser $RUN resize 390 844              # phone width: the captain's view, with the bottom tab bar;
                                            # after the first open, which may move to a new tab
$S browser $RUN click "$($S ref $RUN 'link "✏️ Update"')"
$S browser $RUN fill "$($S ref $RUN 'textbox "Finpension (CHF)"')" 42000
$S browser $RUN click "$($S ref $RUN 'button "Save"')"
$S browser $RUN wait "Finpension saved"
```

- Every action prints a fresh accessibility snapshot. Refs like `@g7:4_5` are generation-tagged and go stale after the next action: look elements up with `ref` by role and accessible name, as the snapshot prints them (`button "Sync now"`, `textbox "Note"`, `link "⚙️ Settings"`).
- Wait for text (`wait "<text>"`), never a fixed sleep.
- File inputs: `upload <ref> <path>` on `button "Upload Neon CSV"` (the hidden file input).
- Date fields: `fill` does not reach React. Click the field's `spinbutton "Month"`, then `type MMDDYYYY`.
- At desktop width the bottom tab bar is hidden and there is no other menu: navigate with `open "$URL/update"` instead, and say so in the proof. At phone width the `Noter` pill covers the centre of the Settings tab, so open `/settings` by URL too.

The feature map in [`features/README.md`](features/README.md) has one recipe per user-facing feature. Read it before driving.

## Evidence

Put every artifact in `$($S proof-dir $RUN)`:

- From a firstmate task, export `FD_PROOF_DIR=/home/ualh/firstmate/data/<your task id>/proof` before calling the helper.
- Otherwise it defaults to `data/verify-proof/<run>/` in the checkout, which `.gitignore` already ignores (`data/`).

Standards:

- Drive the real user path: the page, its buttons and file input. `api` and `sql` are for preconditions and for the read-back, never for the action under test.
- Capture the action and the resulting state: the snapshot printed after the click (`… | tee <proof>/NN-step.aria.txt`) and a screenshot (`$S browser $RUN screenshot <proof>/NN-step.png`) with the `Finance Dash` header visible.
- Verify side effects from a second view: reload the page or open another one, and read the stored row with `$S sql $RUN "…"` or `$S api $RUN GET …`. Save those outputs too.
- Keep a transcript (`transcript.md` in the proof dir) with each command, its output and exit code, the run id, the feature ID and the entry point used.
- The sync button is a dry run here: with blank credentials no source is called. Prove what it skipped by observing it (`select count(*) from sync_log` stays 0, `Synced never` stays), not by trusting it.
- Report a journey you could not reach with the command tried and the missing precondition. Never report a feature as verified through a different entry point than the one named.

## Cleanup

```bash
$S stop $RUN
# stopped server pid 12345 (port 41234)
# stopped browser session fdverify-<run>
# removed archived upload <checkout>/data/csv_archive/neon/<timestamp>.csv
# removed scratch state /tmp/finance-dash-verify/<run>
# proof kept in <proof dir>
```

`stop` kills only the process group launch started (by recorded pid, never by name), stops this run's browser session, deletes the Neon CSV copies this run's uploads added to `<checkout>/data/csv_archive/neon/` (files that were there before launch stay), and removes the scratch dir with the database. It never touches the proof dir. Run it after every failed attempt too, then check the proof dir still holds your files. `frontend/dist` is left built; it is gitignored build output.

## What this stand-in does not cover

- Real source syncs (Binance, Wise, IBKR) and the history backfill: they need the captain's accounts. Only the no-credential path is verified.
- Live FX rates, unless `FD_VERIFY_ALLOW_FX=1`.
- The phone itself and Tailscale: the browser emulates a 390 px viewport on 127.0.0.1.
- The systemd unit and the `0.0.0.0:8001` bind of the live service.
