# finance_dash

Local-first personal finance dashboard for Swiss banking. Ingest CSV exports,
Binance crypto balances, and manual holdings into a single SQLite database, then
view everything through a clean React dashboard.

## Architecture

```
┌────────────────────┐     ┌──────────────────────────────┐
│  React + Vite      │────▶│  FastAPI backend             │
│  (frontend/)       │HTTP │  (backend/)                  │
│                    │     │                              │
│  Dev :5173         │     │  GET  /dashboard             │
│  Prod: served by   │     │  POST /sync/all              │
│        FastAPI     │     │  POST /holdings/neon/upload  │
│                    │     │  POST /holdings/finpension   │
│                    │     │  GET  /holdings              │
│                    │     │  PUT  /holdings/:id          │
│                    │     │  GET  /settings/:key         │
│                    │     │  PUT  /settings/:key         │
└────────────────────┘     │  GET  /health                │
                           └──────────┬───────────────────┘
                                      │
                           ┌──────────▼───────────────────┐
                           │  SQLite (finance_dash.db)     │
                           │  Tables:                     │
                           │  - holdings                  │
                           │  - nw_snapshots              │
                           │  - fx_rates                  │
                           │  - sync_log                  │
                           │  - settings                  │
                           └──────────────────────────────┘
```

## Data sources

| Source | Type | How it works |
|--------|------|-------------|
| **Neon** | CSV upload | Upload your account statement CSV via the UI; balance is derived automatically |
| **Finpension** | Manual input | Enter your pension account CHF value in the Update page |
| **Binance** | API (read-only) | Configure keys in `.env`, sync fetches balances and converts to CHF |

## Prerequisites

- Python 3.11+
- Node.js 18+
- A Tailscale network (for mobile / remote access)

Optional:
- Binance API key + secret (read-only, for crypto balance sync)

## Quick start (development)

### 1. Backend

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Optional: copy and edit .env with your Binance read-only keys
cp .env.example .env

python main.py
```

The API is now at `http://127.0.0.1:8000` — visit `/docs` for Swagger UI.

### 2. Frontend (development mode)

```bash
cd frontend
npm install
npm run dev
```

The Vite dev server starts at `http://127.0.0.1:5173`. API calls are made
directly to `http://127.0.0.1:8000` (configured via `VITE_API_BASE_URL`).

### 3. Verify

```bash
curl http://127.0.0.1:8000/health
# {"status":"ok"}
```

## Production deployment (single process)

Build the frontend and let FastAPI serve it as static files:

```bash
cd frontend && npm run build && cd ..

# Keep VITE_API_BASE_URL empty so the frontend calls the same origin
VITE_API_BASE_URL="" cd frontend && npm run build && cd ..

python main.py
```

Now both the API and the frontend are served from `http://127.0.0.1:8000`. No
separate Vite process needed.

## Access via Tailscale (mobile / remote)

1. Install Tailscale on your Linux machine and your phone.
2. Both devices must be on the same Tailscale network.
3. Run the backend as described above (listening on `127.0.0.1:8000`).
4. From your phone, open `http://<tailscale-ip>:8000` in the browser.

**No port is exposed to the public internet** — only Tailscale peers can reach
the service.

## Daily sync (cron)

A system cron job runs every day at 06:00 to synchronise all data sources:

```
0 6 * * * curl http://localhost:8000/sync/all
```

This triggers `POST /sync/all` (the endpoint also responds to GET). No embedded
Python scheduler is used — if FastAPI is down, the cron job simply fails
harmlessly and retries the next day.

### Manual sync

Click the refresh button on the Dashboard page, or:

```bash
curl -X POST http://localhost:8000/sync/all
```

## SQLite backup (cron)

Backup the database to a secondary disk with a simple `cp` cron entry:

```
0 7 * * * cp /path/to/finance_dash.db /mnt/backup/finance_dash_$(date +\%Y\%m\%d).db
```

Replace `/mnt/backup/` with your actual backup mount point. The database is a
single file and can be copied safely while the app is running (SQLite handles
concurrent reads). For a consistent snapshot, use `sqlite3`:

```
0 7 * * * sqlite3 /path/to/finance_dash.db ".backup '/mnt/backup/finance_dash_$(date +\%Y\%m\%d).db'"
```

## Configuration

| Environment variable | Required | Default | Description |
|---------------------|----------|---------|-------------|
| `BINANCE_API_KEY` | For Binance sync | — | Binance read-only API key |
| `BINANCE_API_SECRET` | For Binance sync | — | Binance read-only API secret |
| `FINANCE_DASH_DB_FILE` | No | `./finance_dash.db` | Path to SQLite database file |
| `VITE_API_BASE_URL` | No | `http://127.0.0.1:8000` | API base URL for frontend (set to empty for same-origin prod) |

## Project structure

```
finance_dash/
├── backend/             # FastAPI app
│   ├── api.py           # Routes
│   ├── config.py        # App configuration
│   ├── database.py      # SQLite repository
│   ├── csv_source/      # Neon CSV parser
│   ├── fx/              # FX rate service
│   ├── sources/         # Binance API sync adapter
│   ├── sync/            # Sync engine
│   └── tests/           # Pytest test suite
├── frontend/            # React + Vite app
│   └── src/
│       ├── api/         # API client
│       ├── components/  # Shared UI components
│       ├── context/     # Theme + currency providers
│       ├── hooks/       # Custom React hooks
│       ├── lib/         # Shared types
│       └── pages/       # Dashboard, Update, Settings
├── docs/
│   └── v1_plan.md       # PRD v1 scope reference
├── main.py              # Uvicorn launcher
└── requirements.txt     # Python dependencies
```

## Testing

```bash
python -m pytest -q
```

## License

MIT
