# finance_dash

Local-first tooling to ingest Swiss bank transactions, persist them in SQLite
and expose a small API that powers a Wealthfolio-inspired front end.

## Current capabilities (MVP)

- Parse the workbook `data/transactions_v3.xlsx` (sheets `crypto_transac` and
	`stocks_transac`) that contains UBS cash movements.
- Clean messy values (Swiss date formats, thousand separators, "[$]" prefixes)
	and normalise them into a consistent schema.
- Persist the enriched data inside a local SQLite database that lives next to
	the project and can be backed up easily.
- Provide REST endpoints (FastAPI) for health checks, importing, listing recent
	transactions and computing cash summaries in CHF or USD.
- Optional live FX and price refresh using Alpha Vantage and Coinranking API
	keys (stored locally via environment variables).

## Project structure

```
finance_dash/
├── backend/                 # FastAPI app, workbook importer, SQLite access
├── data/                    # Raw data files (Excel workbook)
├── docs/roadmap/            # Strategy documents (including map_v2 next steps)
├── finance_dash.db          # Created on first run (local SQLite database)
├── main.py                  # Convenience runner for the FastAPI app
└── requirements.txt         # Python dependencies for the backend
```

## Prerequisites

- Windows PowerShell 5.1 (default shell) or Windows Terminal
- Python 3.11 or newer available on your PATH (`python --version`)

Optional (for live prices):

- Alpha Vantage API key (`ALPHAVANTAGE_API_KEY`)
- Coinranking RapidAPI key (`COINRANKING_API_KEY`)

Create a `.env` file in the project root if you want to store the keys locally:

```
ALPHAVANTAGE_API_KEY=your_alpha_vantage_key
COINRANKING_API_KEY=your_coinranking_key
```

## Quick start

1. **Create a virtual environment and install dependencies**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

2. **Verify the sample workbook is present**

Ensure `data/transactions_v3.xlsx` exists. Replace it with your own export if
needed but keep the sheet names (`crypto_transac`, `stocks_transac`).

3. **Run the FastAPI backend (with auto-reload for development)**

```powershell
python main.py
```

The server listens on `http://127.0.0.1:8000`. Visit
`http://127.0.0.1:8000/docs` to explore the interactive OpenAPI documentation.

4. **Import the Excel workbook**

From the Swagger UI or any REST client, call:

- `POST /import` (imports both sheets by default)
- `GET /transactions` to list the latest rows
- `GET /summary?display_currency=USD` to view totals converted to USD (requires
	a valid CHF→USD FX rate; trigger `POST /fx/refresh?base=CHF&quote=USD` once to
	cache the value).

## API overview

| Endpoint | Verb | Description |
|----------|------|-------------|
| `/health` | GET | Simple heartbeat for monitoring |
| `/import` | POST | Parse the Excel workbook and upsert transactions |
| `/transactions` | GET | Return the latest transactions (limit configurable) |
| `/summary` | GET | Aggregate cash flows in CHF or USD |
| `/fx/refresh` | POST | Fetch latest FX rate via Alpha Vantage |
| `/quotes/equity/{symbol}` | POST | Fetch and store a single equity quote |
| `/quotes/crypto/{uuid}` | POST | Fetch and store a crypto price via Coinranking |
| `/settings/display-currency` | GET/PUT | Retrieve or update the UI display currency |

The SQLite database lives in `finance_dash.db`. You can inspect it with tools
like SQLiteStudio or `sqlite3` from the command line.

## Planned work

- Wire the Wealthfolio front end (React/Vite) to the new REST API.
- Enrich classification rules to automatically match transfers to broker
	accounts.
- Introduce holdings reconstruction once trade-level exports are available.
- Package the backend and frontend into a unified desktop experience for
	non-technical users.

See `docs/roadmap/map_v2.md` for a detailed execution plan.
