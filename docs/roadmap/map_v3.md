# end-to-end plan 
of what’s done and what’s left to ship a functional MVP, grounded in our backend, current frontend scaffold, the sample data, and the Wealthfolio reference app. I’ll keep the frontend code reuse strict: everything we add should be sourced directly from Wealthfolio’s `src` where possible, with only minimal adaptation to call your FastAPI instead of Tauri.

## what the app aims to do (from your docs)

- Local-first, privacy-focused portfolio tracker.
- For the MVP: ingest your UBS cash movements from `data/transactions_v3.xlsx`, persist in SQLite, and present a clean Wealthfolio-style dashboard with:
  - Quick portfolio overview in a selected display currency (CHF/USD),
  - A recent activity/transactions view,
  - Optional live FX/quotes via Alpha Vantage + Coinranking.
- Keep it simple, focused, and “boringly” beautiful—underdo the competition and avoid feature creep.

## what’s working now

Backend (FastAPI; backend, `main.py`):
- Excel importer: Parses `data/transactions_v3.xlsx` (`crypto_transac`, `stocks_transac`), normalizes Swiss formats, and persists enriched data in `finance_dash.db`.
- REST API: Health, import, list transactions, summary (aggregate cash flows with display currency), FX refresh, and quote fetching. `.env` for API keys.
- Live provider hooks: Alpha Vantage (FX/equities) and Coinranking (crypto) wired through a `price_service`.
- Docs: `README.md` (setup/run), roadmap (`docs/roadmap/main_map.md`) aligning with a broader connectors strategy.

Frontend scaffold (Vite/React/Tailwind; frontend):
- Project setup (Vite + Tailwind + TS config), base layout, theme and currency contexts, API client, and core UI building blocks (e.g., `Layout`, `ThemeToggle`, `CurrencyToggle`, `SummaryCard`, `DataState`, `ui/Button`).
- Source patterned directly after Wealthfolio to ensure identical UX and styling.

Gaps noticed:
- Node/npm isn’t installed on your machine yet, so frontend dependencies aren’t installed—hence TS/JSX type errors (“react/jsx-runtime” missing).
- CORS isn’t confirmed—likely needed to allow the web front to call `http://127.0.0.1:8000`.

## the MVP scope we’ll ship

- Dashboard page:
  - Top-level summary in chosen display currency (read from `/summary?display_currency=…`).
  - Small cards/widgets for net inflow/outflow, BTC/VTI proxy allocation, last FX refresh status.
- Activity page:
  - Paginated table of recent transactions from `/transactions`.
- Settings (minimal):
  - Display currency toggle (uses your backend setting if implemented; otherwise use client context and call FX refresh when needed).
  - Optional: fields to place API keys locally (or guidance on `.env` since local-only is fine).
- Data import:
  - Manual trigger via `POST /import` from UI (simple button) and a toast for success/errors.

Everything above should reuse Wealthfolio components, hooks, and pages as much as possible to avoid reinventing UI.

## exact file reuse from Wealthfolio

Use Wealthfolio’s files and patterns wholesale (adapt imports/types minimally), then swap their data-fetching with your REST client:

- Layout and shell:
  - `src/pages/layouts/app-layout.tsx` → Use as the main shell.
  - `src/components/header.tsx`, `src/pages/layouts/sidebar-nav.tsx` → Top/header and sidebar if desired.
- Dashboard:
  - `src/pages/dashboard/dashboard-page.tsx`
  - Reuse light-weight cards/components from `src/components/metric-display.tsx`, and charts stubs from dashboard pages.
- Activity (transactions):
  - `src/pages/activity/components/activity-table.tsx` (and basic wrapper `activity-page.tsx`).
  - Strip advanced editing/import flows for MVP; just reuse table + filters where convenient.
- Context and hooks:
  - `src/context/privacy-context.tsx` (if needed for amount privacy),
  - `src/hooks/use-persistent-state.ts`,
  - `src/lib/utils.ts` helpers.
- UI library:
  - You’ve already mirrored the look-and-feel; for anything missing, pull from `packages/ui/src/components/ui/*` (buttons, cards, tables) and `packages/ui/src/components/common/*` (empty states, skeletons) to keep the same styling.

Replace Wealthfolio’s Tauri “commands” usage with your REST client:
- Wealthfolio modules under `src/commands/*` map to Tauri backend commands. For MVP, ignore Tauri and wire all reads to your FastAPI endpoints via `frontend/src/api/client.ts`.
- Keep the hook naming and call signatures similar where possible for future extensibility.

## backend ↔ frontend API mapping

- Summary widget
  - Frontend: Dashboard stats
  - Backend: `GET /summary?display_currency=CHF|USD`
  - Need: Shape likely includes aggregate in/out/net; expose whatever your backend returns directly in UI.

- Activity table
  - Frontend: Activity page with a table of rows.
  - Backend: `GET /transactions?limit=…&offset=…` (if pagination exists; if not, add minimal pagination).
  - Need: Columns: date, description, amount, currency, category/source (stock/crypto). Use your normalized schema.

- Live FX and quotes
  - Frontend: “Refresh FX” button and/or auto refresh on start.
  - Backend: `POST /fx/refresh?base=CHF&quote=USD`; `POST /quotes/equity/{symbol}`, `POST /quotes/crypto/{uuid}`
  - Need: FX refresh status and last-updated timestamp displayed in a small card.

- Display currency
  - Frontend: Toggle in header/settings.
  - Backend: If `/settings/display-currency` exists (per README), use it; otherwise store client-side in context and pass the query param to `/summary`.

- Import data
  - Frontend: “Import now” button.
  - Backend: `POST /import` with default workbook path.
  - Need: Toast with success count; trigger a soft refresh of dashboard + activity.

Recommended backend extras for a smoother UI:
- Add CORS middleware for origin `http://localhost:5173` (Vite dev) and `http://127.0.0.1:5173`.
- Add simple pagination parameters for `/transactions`.
- Add a `/health` endpoint (already present) and optionally return app version.

## Step-by-step MVP execution plan (with tests and verify/fix loop)

Each step includes: Why this step, the change to apply (typically reusing Wealthfolio files for the frontend), a test to write/run, and a run/verify loop. If anything fails, inspect logs (uvicorn console, pytest output, Vite console, browser devtools Network tab), fix, and add a regression test before moving on.

Preconditions
- Python 3.11+ with venv; FastAPI deps installed.
- Node.js LTS; `npm install` works in `frontend/`.
- Real workbook present at `data/transactions_v3.xlsx`.

Step 1 — Backend boots and CORS enabled
- Why: Frontend must reach the API locally during dev.
- Change: Ensure FastAPI runs and enable CORS for `http://localhost:5173` and `http://127.0.0.1:5173`.
- Test: `tests/backend/test_api_endpoints.py::test_health_ok` (200 on `/health`).
- Run & verify:
  - Backend: `python main.py`
  - If CORS errors appear later in browser, add CORS middleware and re-run.
  - If fails: fix import/runtime errors; add a regression test if a bug is discovered.

Step 2 — Importer parses the real workbook
- Why: Data pipeline foundation.
- Change: No code change expected; use existing importer via `POST /import`.
- Test: `tests/backend/test_importer.py::test_import_real_workbook_parses_and_persists`
  - Asserts rows ingested from `crypto_transac` and `stocks_transac`, with BTC/VTI proxy classification.
- Run & verify:
  - Call `POST /import` from Swagger.
  - `GET /transactions` returns > 0 rows.
  - If fails: check logs for parsing issues; fix normalization; add a targeted regression test.

Step 3 — Idempotent imports
- Why: Users can click import multiple times without duplicates.
- Change: Ensure upsert/dedup logic.
- Test: `tests/backend/test_importer.py::test_import_is_idempotent`
  - Import twice; confirm counts unchanged on second import.
- Run & verify: Repeat `POST /import`; if duplicates appear, adjust DB constraints/keys and add regression test.

Step 4 — Summary in CHF
- Why: Baseline summary must work in base currency without FX.
- Test: `tests/backend/test_services_summary.py::test_summary_chf_ok`
  - GET `/summary?display_currency=CHF` returns totals with expected shape.
- Run & verify: If shape mismatch, document exact response and align UI contract.

Step 5 — FX refresh + Summary in USD
- Why: USD display is a core MVP requirement.
- Tests:
  - `tests/backend/test_fx_refresh.py::test_summary_usd_requires_fx_then_succeeds`
    - Before refresh: USD summary fails clearly; after `POST /fx/refresh?base=CHF&quote=USD`, USD summary returns totals + cached rate.
- Run & verify: Trigger refresh then call `/summary?display_currency=USD`.
  - If fails: verify Alpha Vantage key and error handling; add regression for the failure mode.

Step 6 — Frontend boots with Wealthfolio shell
- Why: Establish the app frame before wiring data.
- Change: Copy from Wealthfolio to `frontend/src/`:
  - `App.tsx`, `routes.tsx`, layouts (`pages/layouts/app-layout.tsx`), and `components/header.tsx`.
  - Keep styling as-is; update imports to your folder aliases.
- Tests:
  - `tests/frontend/unit/components/App.test.tsx` — renders without crashing.
- Run & verify:
  - `cd frontend; npm run dev`; browser loads the shell.
  - If Vite error “Failed to resolve import './App'”: ensure `App.tsx` exists and path matches; commit fix and cover in unit test.

Step 7 — Dashboard summary integration
- Why: First end-to-end slice.
- Change: Implement `api/client.ts.getSummary(displayCurrency)`; wire the dashboard card copied from Wealthfolio to use it.
- Tests:
  - `tests/frontend/integration/dashboard.integration.test.tsx` with MSW mocking `/summary` (CHF → USD toggle re-fetches).
- Run & verify:
  - With backend running and imported data, dashboard shows CHF totals; toggle to USD updates values.
  - If fails: inspect Network tab and FastAPI logs; fix request/response shape and add regression.

Step 8 — Activity table integration
- Why: Visibility into imported rows.
- Change: Copy Wealthfolio's activity table component/page; wire `api/client.ts.getTransactions({ limit, offset })`.
- Tests:
  - `tests/frontend/integration/activity.integration.test.tsx` — rows render; empty and error states covered.
- Run & verify: Page shows transactions; tweak pagination if needed; add regression for any bug.

Step 9 — Currency toggle behavior
- Why: Ensure UI state drives correct backend queries.
- Tests:
  - `tests/frontend/unit/components/CurrencyToggle.test.tsx` — updates context.
  - `tests/frontend/integration/dashboard.integration.test.tsx` — asserts re-fetch on toggle.
- Run & verify: Toggle updates summary; add regression if missed edge-case arises.

Step 10 — Import button from UI
- Why: Enable refresh of data without leaving the app.
- Change: Add a small button to call `POST /import` and refresh dashboard/activity on success.
- Tests:
  - `tests/frontend/integration/apiClient.integration.test.ts` — success and error paths mocked via MSW.
- Run & verify: Button imports and updates views; handle errors with a toast; add regression as needed.

Step 11 — Final polish and test sweep
- Why: Stabilize MVP quality.
- Do:
  - Re-run all backend tests: `pytest tests/backend -q`.
  - Re-run all frontend tests: `cd frontend; npm run test`.
  - Manual smoke: Import workbook, view dashboard/activity, toggle currency, refresh FX.
- If any failures: fix and add targeted tests before declaring MVP done.

## tasks breakdown

Backend (small)
- [ ] Add/confirm CORS
- [ ] Add pagination to `/transactions` (limit, offset)
- [ ] Ensure `/summary` returns stable shape (document it in README)
- [ ] Optional: a “last_fx_updated” field (timestamp) for the dashboard

Frontend (reuse from Wealthfolio)
- [ ] Install Node/npm and dependencies
- [ ] Copy:
  - `src/pages/layouts/app-layout.tsx`
  - `src/components/header.tsx`, `src/pages/layouts/sidebar-nav.tsx` (optional)
  - `src/pages/dashboard/dashboard-page.tsx`
  - `src/pages/activity/components/activity-table.tsx` + `activity-page.tsx`
- [ ] Adapt imports to your directory structure and fetches to `api/client.ts`
- [ ] Wire `ThemeContext` and `DisplayCurrencyContext` you already have
- [ ] Implement `api/client.ts` methods to call FastAPI (GET /summary, GET /transactions, POST /import, POST /fx/refresh)
- [ ] Add a small `DataState` wrapper to handle loading/error/empty (you already have one)
- [ ] Smoke-test in browser; fix any data shape mismatches

Docs and polish
- [ ] Update README.md with frontend run steps and a short “MVP walkthrough”
- [ ] Optionally add a “Sample Data” section showing where `transactions_v3.xlsx` lives and how to replace with their own

## Tests (MVP quality gates)

Goal: fast, deterministic unit and integration tests that validate the importer, API behavior, and key UI flows against the local backend. No E2E for now. Use the real workbook `data/transactions_v3.xlsx` (no synthetic fixtures).

Folder layout (at repo root):

- tests/
  - backend/
    - conftest.py
    - test_importer.py
    - test_services_summary.py
    - test_api_endpoints.py
    - test_fx_refresh.py
  - frontend/
    - unit/
      - lib/
        - format.test.ts
      - components/
        - DataState.test.tsx
        - SummaryCard.test.tsx
        - CurrencyToggle.test.tsx
    - integration/
      - dashboard.integration.test.tsx
      - activity.integration.test.tsx
      - apiClient.integration.test.ts

Test tools:
- Backend: pytest, FastAPI TestClient (httpx/starlette), freezegun for time control.
- Frontend: vitest + @testing-library/react with jsdom; MSW for API mocking in integration tests.

Acceptance criteria:
- Importer
  - Parses Swiss dates and numeric formats (thousands separators, "[$]" prefixes) from `data/transactions_v3.xlsx`.
  - Classifies sheet rows: crypto_transac → BTC proxy, stocks_transac → VTI proxy per MVP assumption.
  - Idempotent re-import (no duplicate rows on repeated POST /import).
  - Logs and skips malformed rows without failing the whole import.
- Summary and FX
  - `/summary` returns stable totals in CHF and USD given a pre-seeded FX rate.
  - Missing FX produces a clear error; after POST `/fx/refresh`, USD summary succeeds and caches the rate.
- API endpoints
  - `/health` returns 200.
  - `/transactions` respects limit/offset if available, or returns a sane default page.
  - `/import` triggers an import and `/transactions` reflects new rows.
- Frontend unit
  - `lib/format` formats CHF/USD as expected (edge cases covered).
  - `DataState` renders loading/error/empty/content correctly.
  - `SummaryCard` and `CurrencyToggle` render and update as intended.
- Frontend integration (mocked APIs)
  - Dashboard integration: shows CHF summary; after currency toggle, refetches and updates to USD.
  - Activity integration: renders rows, empty state, and error state.
  - apiClient integration: uses baseURL and propagates errors consistently.

How to run (Windows PowerShell):
- Backend unit/integration
  ```powershell
  # from repo root
  python -m venv .venv
  .\.venv\Scripts\Activate.ps1
  pip install -r requirements.txt
  # plus dev deps once added: pytest httpx freezegun
  pytest tests/backend -q
  ```
- Frontend unit/integration
  ```powershell
  cd frontend
  npm install
  npm run test
  ```

Notes:
- Keep tests fast; prefer small, targeted assertions.
- Use the real `transactions_v3.xlsx` for importer/API tests; no synthetic Excel fixtures.
- Frontend integration tests should mock network via MSW; do not require a running backend.

## risk and edge cases to watch

- Data parsing: malformed rows in Excel (handle try/except and log rejected rows).
- Idempotent imports: avoid duplicated entries on repeated `POST /import`.
- FX availability: Alpha Vantage limits; cache the rate and display fallback when hitting limits.
- Display currency: If `/settings/display-currency` isn’t implemented, keep it client-side only for MVP.
- CORS: Without it, the browser will block calls even though curl/Postman work.

## mapping Wealthfolio patterns to your app

- Wealthfolio’s Tauri command layer → your `api/client.ts`. Keep hook names/call sites similar for easy later migration.
- Wealthfolio’s UI kits/components → import as-is, don’t re-style. If a piece is missing, pull from `packages/ui/src/components/ui` and `.../common`.
- Wealthfolio’s charts/tables → reuse with minimal prop changes; just adapt to your data shape.

## how to try it (once done)

Backend:
```powershell
cd c:\Users\UrsHu\Documents\sync\Learn\Business\Investments\finance_dash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

Frontend:
```powershell
cd c:\Users\UrsHu\Documents\sync\Learn\Business\Investments\finance_dash\frontend
npm install
npm run dev
```

Open the Vite dev URL (usually http://localhost:5173). Import data, view dashboard and activity, toggle currency, and refresh FX.

## questions before I proceed

- For the MVP pages, do you want just Dashboard + Activity + minimal Settings, or should we also include Holdings (using BTC/VTI proxies) now?
- Is it okay to keep display currency as a client-side preference for MVP, or should I implement the `/settings/display-currency` backend endpoints if not yet present?
- Any specific summary stats you want on the dashboard cards (e.g., total inflow/outflow/net only, or include “current value” estimates using last quotes)?
- Confirm that copying from Wealthfolio is acceptable under its license for your local project (it appears to be open-source; I’ll preserve attribution and the license headers where applicable).

I’ll wait for your answers and then apply the plan, copying only the necessary Wealthfolio files and wiring them to your FastAPI to get an end-to-end MVP running.