# Roadmap v2

This document lists high-confidence next steps after the initial Excel-backed
backend MVP. The tasks are grouped by thematic tracks so the work can progress
in parallel when needed.

## 1. Front-end integration (React + Wealthfolio UI)
- Extract the Wealthfolio React components (layout, dashboard, holdings, activity)
  into a new `frontend/` workspace managed with Vite and PNPM.
- Replace Tauri-specific APIs with REST calls to the FastAPI backend (`/summary`,
  `/transactions`, `/import`).
- Implement a DataProvider context that reads the display currency setting from
  `/settings/display-currency` and exposes a toggle in the header.
- Reuse the existing charts (`performance-chart`, `donut-chart`) once the API
  delivers the required datasets; otherwise add placeholder visualisations.
- Style: keep typography and spacing while swapping the Wealthfolio logo with a
  finance_dash specific asset.

## 2. Transaction enrichment
- Add rule-based mapping that identifies broker transfers versus day-to-day
  spending (by analysing `descr_*` fields). Use these signals to build account
  mapping tables (e.g., UBS ↔ Interactive Brokers ↔ Binance).
- Introduce categorisation confidence scores so manual review steps can focus on
  uncertain transactions.
- Implement reconciliation views in the frontend to mark transactions as
  "reviewed"; persist this flag in a new column (e.g., `review_status`).

## 3. Holdings & portfolio reconstruction
- Extend the importer to ingest trade-level exports from each broker and attach
  them to the existing cash movements by transaction number.
- Derive position lots (quantity, average cost) and expose them through a new
  `positions` table. Use this dataset to populate the holdings page.
- Compute daily portfolio balances by combining cash flows with fetched quotes.
  Consider a background job (`APScheduler`) to refresh quotes once per day.

## 4. Market data platform hardening
- Cache Alpha Vantage and Coinranking responses in the SQLite database with TTL
  metadata to respect rate limits.
- Implement graceful fallbacks (e.g., CoinGecko for crypto prices, ECB for FX)
  when premium providers are unreachable.
- Add API endpoints to list stored quotes and trigger manual refreshes for a
  watchlist of tickers.

## 5. Desktop packaging (optional later phase)
- Bundle the FastAPI backend into a minimal executable using `pyinstaller` or
  `briefcase` so Windows users can launch the service without managing Python.
- Package the React frontend using Tauri or NeutralinoJS to keep the local-only
  story while benefiting from auto-updates and OS integration.
- Introduce a supervisor process that starts both the backend and frontend and
  opens the default browser automatically.

## 6. Quality engineering
- Add pytest-based unit tests for the importer, classifier, and summary
  calculations. Use fixtures with anonymised bank transactions.
- Configure a GitHub Actions workflow that runs linting (`ruff`, `mypy`), tests
  and builds the frontend artefacts on every push.
- Document a data anonymisation process to create shareable sample workbooks for
  integration testing without exposing sensitive information.
