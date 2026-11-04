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
│  Prod: served by   │     │  GET  /freshness             │
│        FastAPI     │     │  POST /sync/all              │
│                    │     │  POST /holdings/neon/upload  │
│                    │     │  POST /holdings/finpension   │
│                    │     │  POST /holdings              │
│                    │     │  GET  /holdings              │
│                    │     │  PUT  /holdings/:id          │
│                    │     │  POST /cash-withdrawals      │
│                    │     │  GET  /cash-withdrawals      │
│                    │     │  DEL  /cash-withdrawals/:id  │
│                    │     │  GET  /settings/:key         │
│                    │     │  PUT  /settings/:key         │
└────────────────────┘     │  GET  /health                │
                           └──────────┬───────────────────┘
                                      │
                           ┌──────────▼───────────────────┐
                           │  SQLite (finance_dash.db)     │
                           │  holdings, nw_snapshots,      │
                           │  neon_uploads,                │
                           │  neon_transactions,           │
                           │  wise_transactions,           │
                           │  cash_withdrawals, fx_rates,  │
                           │  sync_log, settings           │
                           └──────────────────────────────┘
```

The dashboard is one screen: net worth, the change since the end of last month,
the month-by-month curve, each source with the date its figure is valid for
(orange when older than 35 days), and what was spent this month and last month.

## Data sources

| Source | Type | How it works |
|--------|------|-------------|
| **Neon** | CSV upload, monthly | Export the month's statement CSV in the Neon app and upload it on the Update page. Balance = anchor + all stored transactions. |
| **Finpension** | Manual, monthly | Type the value shown in the Finpension app on the Update page. |
| **Binance** | Automatic | Read-only API key. Every wallet (Spot, Funding, Earn, …) is valued through `GET /sapi/v1/asset/wallet/balance`, one line per wallet. |
| **Wise** | Automatic | Personal API token. Balances count in net worth; statement lines count as spending. |
| **IBKR** | Automatic | Flex Web Service token + Activity Flex Query; the account's net asset value. |
| **Cash withdrawals** | Manual | Amount, date and an optional note on the Update page. |
| **Other holdings** | Manual | Any account in any currency (converted to CHF) from the Update page. |

Neon and Finpension have no API for individuals, so they stay a two-minute
monthly gesture. Automatic sources are synced only when their credentials are in
`.env`, including the very first time (no existing row is needed).

### Spending and cash

Spending for a month = Neon outflows (except moves into or out of a Space) +
Wise debits (except conversions and moves between your own balances) + cash
withdrawals that have no matching bank line. A cash withdrawal and an ATM debit
of the same amount within 3 days are the same money and are counted once,
whether the bank data arrives before or after the cash is recorded. Cash records
never change net worth: the bank balance already fell when the cash left it, and
cash in hand is treated as spent.

### Getting the keys

- **Binance**: API Management → Create API → tick only *Enable Reading* (no
  trading, no withdrawals) and restrict it to the server's IP. Put
  `BINANCE_API_KEY` / `BINANCE_API_SECRET` in `.env`.
- **Wise**: Settings → API tokens → Add new token, *Read only*. Put it in
  `WISE_API_TOKEN`. Outside US/AU/NZ/SG/CA/MY, Wise asks for strong customer
  authentication on statements (at most every 90 days): generate a key pair
  (`openssl genrsa -out wise_private.pem 2048` and
  `openssl rsa -pubout -in wise_private.pem -out wise_public.pem`), upload the
  public key under API tokens → Manage public keys, and set
  `WISE_PRIVATE_KEY_PATH` to the private key. Without it, balances still sync
  and the sync log explains why spending was skipped.
- **IBKR**: Client Portal → Performance & Reports → Flex Queries. Create an
  Activity Flex Query (XML, period *Last Business Day*) with the section
  *Net Asset Value (NAV) in Base* (or *Change in NAV*); note its Query ID. Then
  in *Flex Web Service Configuration* enable the service and generate a token
  (optionally IP-restricted). The token only reads reports. Put them in
  `IBKR_FLEX_TOKEN` / `IBKR_FLEX_QUERY_ID`.

## Prerequisites

- Python 3.11+
- Node.js 22.18+ (the frontend unit tests use Node's built-in TypeScript support)
- A Tailscale network (for mobile / remote access)
- `curl` and `openssl` on the server

## Quick start (development)

### 1. Backend

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Optional: copy and fill in the keys of the sources you use
cp .env.example .env

python main.py
```

The dev API is now at `http://127.0.0.1:8000`; visit `/docs` for Swagger UI.

### 2. Frontend (development mode)

```bash
cd frontend
npm install
npm run dev
```

The Vite dev server starts at `http://127.0.0.1:5173` and calls the dev API at
`http://127.0.0.1:8000`.

### 3. Verify

```bash
curl http://127.0.0.1:8000/health
# {"status":"ok"}
```

## Production deployment

The live app runs on **stella** as one process on **port 8001**: FastAPI serves
the API and the built frontend. It runs from the checkout at
`~/Projects/finance_dash` on `main`, with its virtualenv in `.venv`, under the
systemd user unit `finance-dash.service` (uvicorn on `0.0.0.0:8001`, `.env`
loaded as an optional `EnvironmentFile`, restarted on failure).

### Deploying a change

```bash
cd ~/Projects/finance_dash
git pull
(cd frontend && npm ci && npm run build)   # frontend/dist is not committed
systemctl --user restart finance-dash.service
```

Run `.venv/bin/pip install -r requirements.txt` before the restart when
`requirements.txt` changed, and restart after any `.env` change. Leave
`VITE_API_BASE_URL` unset (or empty) for the build so the page calls the host
it was loaded from. Check the service with
`systemctl --user status finance-dash.service` and
`journalctl --user -u finance-dash.service`.

### First install

```bash
cp deploy/systemd/finance-dash.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now finance-dash.service
```

### Daily sync and backup (planned, not installed yet)

`deploy/systemd/` also holds two timers that are **not installed on stella
yet**, so nothing syncs or backs up on its own today; automatic sources sync
when you press sync on the dashboard (`POST /sync/all`).

| Unit | What it will do |
|------|-----------------|
| `finance-dash-sync.timer` | 06:00 daily (catches up after downtime): `POST /sync/all` syncs Binance, Wise and IBKR and writes the day's snapshot |
| `finance-dash-backup.timer` | 06:30 daily: `python -m backend.backup`, a consistent SQLite copy in `~/backups/finance_dash/`, last 30 kept |

To install them later: copy `finance-dash-*.service` and `finance-dash-*.timer`
to `~/.config/systemd/user/`, run `systemctl --user daemon-reload`, then
`systemctl --user enable --now finance-dash-sync.timer finance-dash-backup.timer`.
Without `loginctl enable-linger $USER`, user timers only run while you are
logged in.

### Access via Tailscale (mobile / remote)

From the phone, open `http://<tailscale-ip>:8001`. The port must not be exposed
to the public internet; only Tailscale peers should reach it.

## Monthly reminder

On the 1st of each month: upload last month's Neon CSV and type the Finpension
value on the Update page. A reminder (for example a card filed by firstmate)
reads `GET /freshness`:

```json
{
  "stale_after_days": 35,
  "stale": ["neon", "finpension"],
  "actions": ["Upload last month's Neon CSV on the Update page",
              "Type the current Finpension value on the Update page"],
  "sources": [{"source": "neon", "label": "Neon", "kind": "manual",
               "as_of": "2026-06-03", "age_days": 151, "stale": true,
               "action": "Upload last month's Neon CSV on the Update page"}]
}
```

Neon and Finpension are always listed, even before their first entry. A
source is stale when its figure is more than 35 days old (Neon counts from its
latest transaction, not the upload day; automatic sources from their last good
sync). An empty `stale` list means nothing to ask for.

Every change (upload, manual value, sync) rewrites today's snapshot, so the
curve and "since last month" move as soon as the monthly entry is done.

## Configuration

| Environment variable | Required | Default | Description |
|---------------------|----------|---------|-------------|
| `BINANCE_API_KEY` / `BINANCE_API_SECRET` | For Binance | — | Read-only Binance key |
| `WISE_API_TOKEN` | For Wise | — | Wise personal token (read only) |
| `WISE_PROFILE_ID` | No | personal profile | Wise profile to read |
| `WISE_PRIVATE_KEY_PATH` | For Wise spending outside US/AU/NZ/SG/CA/MY | — | Private key signing Wise's one-time SCA token |
| `IBKR_FLEX_TOKEN` / `IBKR_FLEX_QUERY_ID` | For IBKR | — | Flex Web Service token and Activity Flex Query id |
| `FINANCE_DASH_DB_FILE` | No | `./finance_dash.db` | Path to SQLite database file |
| `FINANCE_DASH_BACKUP_DIR` | No | `~/backups/finance_dash` | Backup destination |
| `FINANCE_DASH_BACKUP_KEEP` | No | `30` | Daily backups kept |
| `VITE_API_BASE_URL` | No | same origin (prod), `http://127.0.0.1:8000` (dev) | API base URL baked into the frontend build |

## Project structure

```
finance_dash/
├── backend/             # FastAPI app
│   ├── api.py           # Routes
│   ├── config.py        # App configuration
│   ├── database.py      # SQLite repository
│   ├── csv_source/      # Neon CSV parser
│   ├── fx/              # FX rate service
│   ├── sources/         # Binance, Wise, IBKR adapters
│   ├── sync/            # Sync engine (automatic sources)
│   ├── snapshots.py     # Daily snapshots + monthly curve
│   ├── freshness.py     # Per-source age, stale list for the reminder
│   ├── spending.py      # Monthly spending, cash matched once
│   ├── backup.py        # Daily SQLite backup
│   └── tests/           # Pytest test suite
├── frontend/            # React + Vite app
│   └── src/
│       ├── api/         # API client
│       ├── components/  # Shared UI components
│       ├── context/     # Theme + currency providers
│       ├── hooks/       # Custom React hooks
│       ├── lib/         # Shared types
│       └── pages/       # Dashboard, Update, Settings
├── deploy/systemd/      # User units: app, daily sync, daily backup
├── docs/
│   └── v1_plan.md       # PRD v1 scope reference
├── main.py              # Uvicorn launcher
└── requirements.txt     # Python dependencies
```

## Testing

```bash
python -m pytest -q          # backend
(cd frontend && npm test)    # frontend unit tests (node:test)
```

No test reaches a real account: every source is exercised against mocked
responses shaped after the official API docs.

## License

MIT
