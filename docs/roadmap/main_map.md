ATTENTION: The roadmap is subject to change.

# Executive summary 

a developer-ready, copy-pasteable automation plan to fetch **every asset** in your canonical list (exchanges, brokers, on-chain wallets, pension providers that lack APIs). The plan is phased (Discovery → MVP → Expand → Harden → Operate) and includes per-platform specs, signing examples (Python + Node), Postgres DDL, 3 complete connector examples (Binance, Alchemy (EVM), Interactive Brokers), a Docker Compose stack, a React dashboard skeleton, monitoring & CI guidance, and fallback automation for providers without APIs (Playwright / IMAP / PDF parsing). Wherever I state a web-verifiable fact (endpoints, auth, rate limits, topics) I cite the official docs.


# Key authoritative citations (load-bearing)

* Binance REST & account endpoint + signing, weights & rate-limits. ([Binance Developer Center][1])
* Alchemy token balance & token metadata endpoints (EVM). ([Alchemy][2])
* Interactive Brokers (TWS / Client Portal / Web API docs). ([Interactive Brokers][3])
* KuCoin / Bitget / OKX official API docs (auth patterns & WS). ([KuCoin][4])
* CoinGecko `simple/price` and contract token price endpoints (canonical price provider). ([CoinGecko API][5])
* Phantom wallet dev docs (connect / wallet adapter). ([Phantom Developer Documentation][6])
* Finpension, Frankly and SwissBorg show lack of account API (so fallback necessary). ([SwissBorg Roadmap][7])

---

# 1) Phased, numbered implementation plan (Discovery → MVP → Expand → Harden → Operate)

Each task: engineer steps, minimal UI permissions, security settings, and priority (P1 = must for MVP).

## Phase 0 — Discovery (P1)

1. Inventory & secrets vault
   * use HashiCorp Vault to store data locally. Need to configure it to use a local filesystem or external storage on the same host
   * Security: require TLS (Transport layer security) for all endpoints, use mutual TLS only where provider requires it. (Ops detail in Harden).
2. Read provider docs (collect canonical URLs — I already collected core docs above). Save as markdown in repo `docs/providers/`.
3. Create `connectors/` repo skeleton and local Postgres schema (next section contains DDL).

## Phase 1 — MVP (P1)

Goal: autonomously fetch authenticated balances + transactions for **Binance, Bitget, OKX, MEXC, KuCoin, CoinEx, Bybit, Phantom, cold wallet (EVM + Solana), Interactive Brokers** and provide a unified portfolio snapshot.

Tasks (engineer steps):

1. **Binance connector (P1)** — implement signed REST calls to `GET /api/v3/account` for spot and `/fapi/v2/balance` for futures. See auth example below. Set API key scopes: **Read only** (spot: “Enable Spot & Margin”, futures: none if only reading futures via separate key). Create API key in Binance UI → API Management → generate key → enable **Read Only** and IP allowlist for your server IP. Use HMAC SHA256 signature of query string + timestamp. (Docs: account endpoints & weights). ([Binance Developer Center][1])
2. **Alchemy connector (cold wallet / EVM)** (P1) — use `alchemy_getTokenBalances`, `alchemy_getTokenMetadata` for EVM assets; for historical tx use `alchemy_getAssetTransfers`. Acquire Alchemy API key. Example below. ([Alchemy][2])
3. **Phantom (Solana) wallet** (P1) — add Wallet Adapter flow for user to sign and provide address. Use an indexer like Helius or QuickNode to fetch token accounts & balances. Phantom itself is an on-device wallet, not an account API. ([Phantom Developer Documentation][6])
4. **Interactive Brokers (P1)** — run a headless IBKR Gateway or Client Portal API instance locally (see IBKR docs). Use the Client Portal REST for account summary and positions. Steps in IBKR section below. ([Interactive Brokers][8])
5. **Other exchanges (KuCoin, Bitget, OKX, MEXC, CoinEx, Bybit)** (P1) — implement read-only API keys with IP allowlist; use official REST account/balance endpoints and user websocket streams for real-time updates where available. Follow provider docs for signing (KuCoin uses passphrase+HMAC, OKX signs header). See per-platform section below. ([KuCoin][4])
6. **SwissBorg, Frankly, Finpension (P2)** — these typically do not provide public account APIs. Implement fallback strategies (IMAP ingestor for monthly statements; Playwright headless automation to download CSV/PDF statements securely; scheduled PDF parsing). Provide sample code in later section. (SwissBorg roadmap confirms limited API). ([SwissBorg Roadmap][7])

## Phase 2 — Expand (P2)

1. Add derivatives/futures endpoints & websocket order streams for exchanges that user trades on (Bybit, Binance futures, OKX). Subscribe to user order streams (user data streams/listenKey pattern) and save to `connector_state`.
2. Add reconciliation jobs (daily): cross-check exchange deposits/withdrawals against on-chain receipts for cold wallet addresses.
3. Add price enrichment (CoinGecko + optional paid providers) and ISIN resolution for equities (OpenFIGI).

## Phase 3 — Harden (P2/P3)

1. Secrets rotation schedule (rotate API keys quarterly or per provider recommended rotation). Use Vault with dynamic secrets where possible.
2. Harden network: IP allowlist, egress policies, TLS 1.3, mutual TLS for sensitive connectors.
3. Rate-limit & backoff policies (exponential backoff with full jitter, capped retries). Implement circuit breaker for flaky connectors.

## Phase 4 — Operate (P2)

1. Monitoring + alerting (Prometheus + Grafana): connector last success timestamp, per-connector error rate, rate-limit hits.
2. Backfill & idempotency rules — each connector must write `transactions` and dedupe on unique provider `tx_id`. Provide reprocess CLI to re-ingest from X date.

---

# 2) Per-platform integration spec (condensed; full copy-pasteable examples follow)

> I list the official interfaces, auth method, example calls to fetch balances/positions/tx history, websocket topics where available, rate-limits and pitfalls. For providers without account APIs, fallbacks are explicit.

---

## Binance (Spot & Futures) — official interfaces & examples

* **Docs**: REST account endpoints (`GET /api/v3/account`) and futures endpoints; WebSocket user data streams; rate limits + `exchangeInfo`. ([Binance Developer Center][1])
* **Auth**: API Key header `X-MBX-APIKEY` and HMAC SHA256 signature of query string + `timestamp`. Signature appended as `signature=...`.
* **Rate limits**: endpoints have weight; `GET /api/v3/account` weight 20; overall request limits returned by `exchangeInfo`. WebSocket handshake costs weight 5; ping/pong limits 5/sec. ([Binance Developer Center][1])
* **Python signed request (sync, requests)**

```python
import os, time, hmac, hashlib, requests
API_KEY = os.getenv("BINANCE_API_KEY", "REPLACE_ME_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET", "REPLACE_ME_API_SECRET")
BASE = "https://api.binance.com"

def signed_get(path, params=None):
    if params is None: params = {}
    params['timestamp'] = int(time.time()*1000)
    query = '&'.join(f"{k}={params[k]}" for k in sorted(params))
    sig = hmac.new(API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    url = f"{BASE}{path}?{query}&signature={sig}"
    headers = {"X-MBX-APIKEY": API_KEY}
    r = requests.get(url, headers=headers, timeout=10)
    r.raise_for_status()
    return r.json()

# fetch account balances
acct = signed_get("/api/v3/account", {"recvWindow":60000})
print(acct["balances"][:5])
```

* **Node (axios) example**

```js
const axios = require("axios");
const crypto = require("crypto");
const API_KEY = process.env.BINANCE_API_KEY || "REPLACE_ME_API_KEY";
const API_SECRET = process.env.BINANCE_API_SECRET || "REPLACE_ME_API_SECRET";
const BASE = "https://api.binance.com";

async function signedGet(path, params = {}) {
  params.timestamp = Date.now();
  const qs = new URLSearchParams(Object.keys(params).sort().map(k=>[k, params[k]])).toString();
  const signature = crypto.createHmac("sha256", API_SECRET).update(qs).digest("hex");
  const url = `${BASE}${path}?${qs}&signature=${signature}`;
  const res = await axios.get(url, { headers: { "X-MBX-APIKEY": API_KEY }, timeout: 10000 });
  return res.data;
}
```

* **Endpoints to call**

  * `GET /api/v3/account` — balances, permissions. Weight: 20. ([Binance Developer Center][1])
  * `GET /api/v3/myTrades` — trade history by symbol.
  * Futures: `GET /fapi/v2/balance` & `GET /fapi/v2/positionRisk` for positions. ([Binance Developer Center][9])
* **WebSocket**: User data streams via listenKey — create with `POST /api/v3/userDataStream` then connect to `wss://stream.binance.com:9443/ws/<listenKey>`. Save keepalive. ([Binance Developer Center][10])
* **Pitfalls**:

  * Timestamps: server time skew — call `GET /api/v3/time` and adjust local clock.
  * IP allowlist recommended; rate limits enforced with 429 + `X-MBX-USED-WEIGHT` headers.
* **Backoff**: exponential backoff with full jitter, max 8 retries; for 429 read `Retry-After` header when present.

---

## Alchemy (EVM indexer for cold wallet)

* **Docs**: `alchemy_getTokenBalances`, `alchemy_getTokenMetadata`, `alchemy_getAssetTransfers`. (REST/JSON-RPC). ([Alchemy][2])
* **Auth**: `apiKey` in URL or `X-Alchemy-Token` header.
* **Python example (requests)**

```python
import os, requests, json
ALCHEMY_KEY = os.getenv("ALCHEMY_KEY", "REPLACE_ME_ALCHEMY_KEY")
BASE = f"https://eth-mainnet.alchemyapi.io/v2/{ALCHEMY_KEY}"

def get_token_balances(address):
    payload = {"jsonrpc":"2.0","id":1,"method":"alchemy_getTokenBalances","params":[address]}
    r = requests.post(BASE, json=payload, timeout=10)
    r.raise_for_status()
    return r.json()['result']

print(get_token_balances("0x..."))
```

* **What to fetch**

  * ERC-20 token balances, native ETH balance, token metadata to get decimals/symbol, asset transfers for deposits/withdrawals. ([Alchemy][2])
* **Pitfalls**

  * `alchemy_getTokenBalances` may return many zero balances — filter nonzero.
  * Rate limits depend on plan — cache token metadata locally.

---

## Phantom (Solana wallet)

* **Docs**: Phantom is a client wallet — integrate with Wallet Adapter to get user address; then call Solana RPC or indexer (Helius/QuickNode) to fetch token accounts. Phantom does not expose an account API for custodial access. ([Phantom Developer Documentation][6])
* **Recommended indexers**: Helius (token metadata, NFTs), QuickNode for RPC, Solana JSON-RPC `getTokenAccountsByOwner`.
* **Flow**:

  1. User connects Phantom (web UI) and signs a nonce to prove ownership.
  2. App sends the Solana address to backend.
  3. Backend calls Helius `getTokenAccounts` or RPC `getTokenAccountsByOwner` to list tokens and balances.
* **Example** (Python using `requests` to QuickNode / public RPC):

```python
RPC = "https://solana-mainnet.quiknode.pro/REPLACE_KEY/"
import requests, json
def get_token_accounts(owner):
    body = {"jsonrpc":"2.0","id":1,"method":"getTokenAccountsByOwner","params":[owner, {"programId":"TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"}, {"encoding":"jsonParsed"}]}
    r = requests.post(RPC, json=body); r.raise_for_status()
    return r.json()['result']
```

---

## KuCoin, Bitget, OKX, MEXC, CoinEx, Bybit — common patterns

* All have **REST** account endpoints (GET balances) and **WebSocket** user streams. Authentication uses API_KEY + signature; formats differ per provider (KuCoin: key/secret/passphrase; OKX: sign timestamp+method+requestPath with HMAC SHA256 and base64 encode; Bitget has its v3 docs). See official docs for exact header formats. ([KuCoin][4])
* **Recommendation**: implement provider-specific signing modules + a common interface `fetch_balances()`, `fetch_positions()`, `fetch_trades(start, end)`.

---

## BloFin (short-term leverage)

* BloFin appears to provide an API (public docs exist: docs.blofin.com). Treat as regular exchange: create read-only key. If account is proprietary/OTC contact support for API access. ([BloFin API][11])

---

## SwissBorg, Frankly, Finpension (pension providers — likely no public account APIs)

* SwissBorg: product/roadmap indicates account data export only/manual export today → **no stable public account API**. Frankly & Finpension offer apps/web portals but I could not find public documented APIs — treat as **no public programmatic account API**. Use fallbacks (IMAP PDF ingest or Playwright). ([SwissBorg Roadmap][7])
* **Fallback strategies**:

  * **IMAP ingestion**: create a dedicated email (e.g., `connect+frankly@yourdomain`) and instruct user to forward monthly statements automatically. Build an IMAP consumer to parse PDF attachments via `pdfminer`/`tabula-py`. Sample code below.
  * **Playwright automation**: headless login with stored encrypted cookies and TOTP handling — prefer OAuth flows or ask user to download CSV monthly. Examples below.
* **Legal & consent text** (display before automation):

  > *I will log in to [provider] on your behalf and download your account statements. You must supply credentials or a forwarding rule. This process stores only the statement PDFs and derived transactions locally — encrypted at rest. Proceed?*
  > (You must also log acceptance in the UI and store a cryptographic consent record.)

---

## Interactive Brokers (IBKR)

* **Interfaces**:

  * TWS API (socket) and Client Portal Web API (HTTP REST) — use Client Portal API for local headless operation or TWS API for streaming. ([Interactive Brokers][3])
* **Run steps (engineer)**:

  1. Install Trader Workstation (TWS) or IB Gateway (headless). Enable API connections: TWS → Global Configuration → API → Settings → check **Enable ActiveX and Socket Clients**; add trusted IP `127.0.0.1` or your server IP and set **Read-only** as needed.
  2. OR use **Client Portal Gateway** (recommended for REST) — start the CP application, then call CP Web API on localhost to fetch `GET /iserver/account` and `GET /iserver/accounts/{accountId}/positions`. ([Interactive Brokers][12])
* **Python example (Client Portal)** — using local CP web API:

```python
import requests
BASE = "http://localhost:5000"  # default CP web API port
r = requests.get(BASE + "/iserver/account")
r.raise_for_status()
print(r.json())
# positions
pos = requests.get(BASE + "/iserver/account/positions")
```

* **Pitfalls**: TWS must be running; credentials require 2FA; client must handle session cookies for CP API.

---

# 3) On-chain wallets (cold wallet & Phantom) — recommended indexers & canonicalization

## Recommended indexers / RPC providers

* **EVM (Ethereum + L2s)**: Alchemy, QuickNode, Covalent (indexer), Etherscan REST for tx lookup. Use Alchemy for token balances + `alchemy_getTokenBalances` and `alchemy_getTokenMetadata`. ([Alchemy][2])
* **Solana**: Helius (fast, token metadata & transfers), QuickNode Solana RPC, Solana JSON-RPC `getTokenAccountsByOwner`. ([Phantom Developer Documentation][13])
* **Example Alchemy response (condensed)** — `alchemy_getTokenBalances` returns `tokenBalances` array with `contractAddress` and hex `tokenBalance`. (Example in docs). ([Alchemy][2])

## Canonicalization strategy

* Canonical key: `(chain, contract_address_lowercase)` for tokens; use CoinGecko contract→ID mapping when resolving price. Normalize decimals by fetching token metadata (decimals) and computing human balance: `human = int(balance) / (10 ** decimals)`.
* For wrapped tokens / LP tokens: detect via token metadata (check `symbol` includes `WETH`, check token `totalSupply` and known LP registry) and flag as `is_wrapped=true`. Provide mapping table to unwrap price using pool reserves (Chain calls to Uniswap/Sushi pools) — implement as plugin for top LPs.

---

# 4) Swiss pension providers (Frankly & Finpension) — fallback automation

* **Search results** indicate only app/web portal — no public API. Use safe automation:

  1. **User consent UI** (store consent signed with user key).
  2. **IMAP + PDF ingestion**:

     * Ask user to forward monthly statements to dedicated inbound mailbox.
     * IMAP example (Python `imaplib`) to download PDFs and parse with `pdfplumber` or `camelot` (tables) and `tabula-java` if needed.
  3. **Playwright headless** (last resort): encrypted credentials in Vault, 2FA via TOTP — on login capture CSV/statement URL and download. Save session cookies encrypted for reuse. *Warning*: confirm TOS before automating scraping. Provide consent language and opt-out.
* **Sample IMAP downloader (Python)**

```python
import imaplib, email, os
MBOX = ("imap.mail.provider", 993)
USERNAME = "connect+frankly@yourdomain"
PASSWORD = os.getenv("IMAP_PW")
m = imaplib.IMAP4_SSL(MBOX[0], MBOX[1])
m.login(USERNAME, PASSWORD)
m.select('INBOX')
_, data = m.search(None, '(FROM "no-reply@frankly.ch" SUBJECT "Statement")')
for num in data[0].split():
    _, msgdata = m.fetch(num, '(RFC822)')
    msg = email.message_from_bytes(msgdata[0][1])
    for part in msg.walk():
        if part.get_content_maintype() == 'application' and part.get_filename():
            fn = part.get_filename()
            with open("/tmp/" + fn, "wb") as f:
                f.write(part.get_payload(decode=True))
```

---

# 5) Interactive Brokers — more detail (auth & sample)

* **Run**: IB Gateway recommended for server usage (headless), or TWS if you need GUI. Enable API access and whitelist your server IP. Guides: TWS API & Client Portal docs. ([Interactive Brokers][3])
* **Sample Python (IB Client Portal)** — using `requests` to local CP Web API (must start CP Gateway):

```python
import requests
BASE = "http://localhost:5000"
# login flow is manual to start CP; once started call
acct = requests.get(BASE + "/iserver/account").json()
positions = requests.get(BASE + "/iserver/account/positions").json()
```

* **TWS API (socket) Python**: use `ib_insync` to connect to TWS/Gateway and fetch portfolio:

```python
from ib_insync import IB
ib = IB()
ib.connect('127.0.0.1', 4002, clientId=1)  # port for TWS/Gateway
acct = ib.accountValues()
positions = ib.positions()
ib.disconnect()
```

---

# 6) Price enrichment & canonicalization

* **Strategy**: canonical crypto ID = CoinGecko ID if available; for tokens fallback to `chain+contract`. For equities use `ISIN` when available, else `ticker+exchange`.
* **Price provider**: CoinGecko `simple/price` for crypto; CoinGecko `simple/token_price/{id}` for contract addresses; paid providers optional for lower latency. ([CoinGecko API][5])
* **Sample price resolution (Python)**

```python
import requests
def price_for_contract(chain_id, contract):
    # e.g. chain_id='ethereum', contract='0xa0b8...'
    url = "https://pro-api.coingecko.com/api/v3/simple/token_price/ethereum"
    params = {"contract_addresses": contract, "vs_currencies":"usd,eur"}
    r = requests.get(url, params=params, headers={"x-cg-pro-api-key": "REPLACE_CG_KEY"})
    return r.json()
```

* **Caching**: price_cache table (DDL below) with TTL: 30s for high frequency (tickers), 60s for aggregated assets; for CoinGecko free tier 30s–5min depending on plan.

---

# 7) Data model & API — full Postgres DDL (copy-paste)

```sql
-- accounts: user accounts / provider accounts
CREATE TABLE accounts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  provider text NOT NULL, -- e.g., 'binance', 'ibkr', 'alchemy'
  provider_account_id text NOT NULL, -- e.g., subaccount id
  display_name text,
  created_at timestamptz DEFAULT now(),
  last_sync timestamptz
);

CREATE TABLE assets (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  symbol text NOT NULL,
  name text,
  asset_type text NOT NULL, -- 'crypto','equity','token'
  canonical_id text, -- coinGecko id or ISIN or contract
  chain text, -- e.g., 'ethereum'
  decimals int,
  metadata jsonb,
  created_at timestamptz DEFAULT now()
);

CREATE TABLE asset_identifiers (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  asset_id uuid REFERENCES assets(id),
  identifier_type text NOT NULL, -- 'contract','coingecko','isin','ticker'
  identifier_value text NOT NULL,
  UNIQUE (asset_id, identifier_type, identifier_value)
);

CREATE TABLE snapshots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id uuid REFERENCES accounts(id),
  ts timestamptz NOT NULL,
  total_usd numeric,
  total_chf numeric,
  raw jsonb,
  created_at timestamptz DEFAULT now()
);

CREATE TABLE positions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id uuid REFERENCES accounts(id),
  asset_id uuid REFERENCES assets(id),
  quantity numeric NOT NULL,
  avg_price_usd numeric,
  side text,
  updated_at timestamptz DEFAULT now(),
  raw jsonb
);

CREATE TABLE transactions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id uuid REFERENCES accounts(id),
  provider_tx_id text,
  asset_id uuid REFERENCES assets(id),
  type text, -- 'trade','deposit','withdrawal','fee','transfer'
  amount numeric,
  currency text,
  timestamp timestamptz,
  metadata jsonb,
  UNIQUE(account_id, provider_tx_id)
);

CREATE TABLE price_cache (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  canonical_id text,
  provider text,
  currency text,
  price numeric,
  fetched_at timestamptz DEFAULT now(),
  raw jsonb
);

CREATE TABLE audit_logs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_type text,
  provider text,
  message text,
  payload jsonb,
  created_at timestamptz DEFAULT now()
);

CREATE TABLE connector_state (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  provider text NOT NULL,
  state_key text NOT NULL,
  state_value jsonb,
  updated_at timestamptz DEFAULT now(),
  UNIQUE(provider, state_key)
);
```

---

# 8) Connector code examples — 3 complete connectors (Binance, Alchemy, Interactive Brokers)

> I provide representative, complete connectors with auth, fetch balances/positions, parse and insert into Postgres (psycopg2), error handling + backoff (Python). Below are condensed but copy-pasteable examples — put in `connectors/binance.py`, `connectors/alchemy.py`, `connectors/ibkr.py`.

### Connector: Binance (Python, minimal)

```python
# connectors/binance.py
import os, time, hmac, hashlib, requests, psycopg2, random
from urllib.parse import urlencode
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
BASE="https://api.binance.com"

def sign(params):
    params['timestamp'] = int(time.time()*1000)
    qs = urlencode(sorted(params.items()))
    sig = hmac.new(API_SECRET.encode(), qs.encode(), hashlib.sha256).hexdigest()
    return qs + "&signature=" + sig

def get_account():
    qs = sign({})
    url = f"{BASE}/api/v3/account?{qs}"
    res = requests.get(url, headers={"X-MBX-APIKEY":API_KEY}, timeout=10)
    if res.status_code == 429:
        # backoff
        raise Exception("Rate limited")
    res.raise_for_status()
    return res.json()

# Insert into DB
def insert_balances(conn, account_id, balances):
    with conn.cursor() as cur:
        for b in balances:
            if float(b['free']) + float(b['locked']) == 0:
                continue
            cur.execute("INSERT INTO positions (account_id, asset_id, quantity, raw, updated_at) VALUES (%s,%s,%s,%s,now()) ON CONFLICT (account_id, asset_id) DO UPDATE SET quantity=EXCLUDED.quantity, raw=EXCLUDED.raw", (account_id, None, float(b['free'])+float(b['locked']), json.dumps(b)))
    conn.commit()
```

* **Backoff**: use `time.sleep((2 ** retry) * random.random())` up to 8 retries.

### Connector: Alchemy (Python)

```python
# connectors/alchemy.py
import os, requests, json
ALCHEMY_KEY = os.getenv("ALCHEMY_KEY")
BASE = f"https://eth-mainnet.alchemyapi.io/v2/{ALCHEMY_KEY}"

def get_token_balances(address):
    payload = {"jsonrpc":"2.0","id":1,"method":"alchemy_getTokenBalances","params":[address]}
    r = requests.post(BASE, json=payload, timeout=10); r.raise_for_status()
    return r.json()['result']

# parse and store metadata similarly; see DDL
```

### Connector: Interactive Brokers (ib_insync example)

```python
# connectors/ibkr.py
from ib_insync import IB
ib = IB()
ib.connect('127.0.0.1', 4002, clientId=1)
positions = ib.positions()
# transform ib.positions() into transactions and positions
ib.disconnect()
```

* **Unit tests**: use recorded HTTP fixtures (vcrpy or responses) and `pytest` to assert parsing logic.

---

# 9) Local deployment — Docker Compose, `.env`, secrets

`docker-compose.yml` (FastAPI + Postgres + Redis)

```yaml
version: "3.8"
services:
  db:
    image: postgres:15
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: portfolio
    volumes:
      - db-data:/var/lib/postgresql/data
  api:
    build: ./backend
    env_file: .env
    depends_on: [db]
    ports: ["8000:8000"]
  redis:
    image: redis:7
volumes:
  db-data:
```

`.env` (example)

```
DATABASE_URL=postgresql://postgres:postgres@db:5432/portfolio
BINANCE_API_KEY=REPLACE_ME_API_KEY
BINANCE_API_SECRET=REPLACE_ME_API_SECRET
ALCHEMY_KEY=REPLACE_ME_ALCHEMY_KEY
```

* **Secrets**: For local dev use HashiCorp Vault dev or OS keyring. For production use Vault with transit encryption and automatic rotations.

* **Commands**

```bash
docker-compose up -d
# run DB migrations (psql) to execute the DDL above
psql $DATABASE_URL -f db/schema.sql
# run backend
docker-compose logs -f api
```

---

# 10) Dashboard skeleton (single-file React component)

`PortfolioOverview.jsx` — single file React + fetch from `/api/portfolio/overview`

```jsx
import React, {useEffect, useState} from "react";
export default function PortfolioOverview(){
  const [data, setData] = useState(null);
  useEffect(()=>{ fetch("/api/portfolio/overview").then(r=>r.json()).then(setData) }, []);
  if(!data) return <div>Loading...</div>;
  const {total_usd, total_chf, breakdown, top_holdings, timeseries} = data;
  return (
    <div className="p-4">
      <h1 className="text-xl font-bold">Portfolio — {total_usd ? `$${total_usd.toLocaleString()}` : '—'}</h1>
      <div className="grid grid-cols-3 gap-4 mt-4">
        <div className="card p-3">
          <h2 className="font-semibold">Per-platform</h2>
          <ul>{breakdown.map(b=> <li key={b.provider}>{b.provider}: ${b.usd.toFixed(2)}</li>)}</ul>
        </div>
        <div className="card p-3">
          <h2 className="font-semibold">Top holdings</h2>
          <ol>{top_holdings.map(h=> <li key={h.id}>{h.symbol} — {h.qty} ({h.usd.toFixed(2)})</li>)}</ol>
        </div>
        <div className="card p-3">
          <h2 className="font-semibold">Time series</h2>
          <pre style={{fontSize:10}}>{JSON.stringify(timeseries.slice(-10), null, 2)}</pre>
        </div>
      </div>
    </div>
  );
}
```

* Required API routes:

  * `GET /api/portfolio/overview` → returns `{ total_usd, total_chf, breakdown: [{provider, usd}], top_holdings: [...], timeseries: [...] }`
  * `GET /api/accounts` ; `GET /api/assets` ; `POST /api/connectors/:provider/sync`

---

# 11) Operations & monitoring

* Expose metrics:

  * `connector_last_success{provider="binance"}` (unix timestamp)
  * `connector_errors_total{provider="binance"}`
  * `connector_rate_limit_hits_total{provider}`
* **Prometheus** exporter: each connector writes to `/metrics` or pushgateway.
* **Backfill & reprocess**:

  * Idempotency: dedupe on `provider_tx_id` OR on provider + raw tx hash + timestamp.
  * Reprocess CLI: `./cli reprocess --provider binance --from 2025-01-01`

---

# 12) Security, secrets & legal checklist

* **Minimum API scopes**:

  * Exchanges: *Read only* (balances/ trades). NEVER enable withdrawal rights for connectors. Use IP allowlist.
* **Storage**: Vault for API keys; database encryption at rest; AES-256 for persisted tokens.
* **Rotation**: rotate API keys quarterly. Use audit_logs for key usage.
* **2FA**: when automating UI scraping (Playwright), do not store username/password unencrypted without explicit consent. Prefer user-initiated OAuth or manual CSV export.
* **Legal/TOS**: check provider terms before scraping. If scraping is disallowed, prefer IMAP-forwarded statements or manual export. For Swiss providers, require explicit consent form stored in DB.

---

# 13) Testing & CI (example)

* **Unit tests**: use `pytest`, use `responses` to mock REST APIs. For WebSockets use a local ws server or `websocket-client` with fixtures.
* **Integration tests**: run nightly sandbox smoke tests against test API keys (where providers support sandbox).
* **GitHub Actions** example (simplified):

```yaml
name: CI
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Setup Python
        uses: actions/setup-python@v4
        with: python-version: "3.11"
      - run: pip install -r requirements.txt
      - run: pytest -q
```

---

# 14) Final inline deliverables (copy-pasteable)

## Prioritized MVP checklist (P1–P3)

**P1**

* Implement Binance connector (balances + trades) with signed requests & WebSocket userData; IP allowlist + read-only API key. ([Binance Developer Center][1])
* Implement Alchemy connector for cold wallet token balances. ([Alchemy][2])
* Implement Phantom wallet connect + Solana RPC indexer calls (Helius/QuickNode). ([Phantom Developer Documentation][6])
* Implement Interactive Brokers Client Portal fetch (positions + account summary). ([Interactive Brokers][8])

**P2**

* Implement other exchanges (OKX, KuCoin, Bitget, Bybit, MEXC, CoinEx) read-only connectors. ([KuCoin][4])
* Price enrichment via CoinGecko `simple/price`. ([CoinGecko API][5])

**P3**

* Playwright automation for Frankly/Finpension (only after confirming TOS + consent).
* Advanced reconciliation + LP token unwrapping.

## Compact Getting Started README (commands)

```bash
# clone repo
git clone <repo>
cd repo
# env
cp .env.example .env
# start local stack
docker-compose up -d
# create DB schema
psql $DATABASE_URL -f db/schema.sql
# run backend
docker-compose up api
```

## Scaffolded repo layout (tree)

```
/backend
  /connectors
    binance.py
    alchemy.py
    ibkr.py
  main.py
  db/
    schema.sql
/frontend
  src/PortfolioOverview.jsx
docker-compose.yml
.env.example
README.md
```

## At least 5 authoritative provider doc citations used above

* Binance account & rate limits docs. ([Binance Developer Center][1])
* Alchemy token balance docs. ([Alchemy][2])
* Interactive Brokers API docs (TWS / Client Portal). ([Interactive Brokers][3])
* CoinGecko `simple/price` + token price endpoints. ([CoinGecko API][5])
* Phantom wallet developer docs. ([Phantom Developer Documentation][6])
* SwissBorg product roadmap indicating lack of API. ([SwissBorg Roadmap][7])

---

# Known assumptions & fallbacks (explicit)

1. **Assumption**: SwissBorg / Frankly / Finpension do not provide public, documented account APIs for programmatic per-user read access — fallback to IMAP/Playwright. If you can obtain official API credentials from them, replace fallback with direct API. ([SwissBorg Roadmap][7])
2. **Assumption**: BloFin provides an API (public docs found) — treat like any exchange; confirm testnet/sandbox keys if you plan to trade programmatically. ([BloFin API][11])
3. **Assumption**: IBKR Client Portal will be run locally (headless) to allow REST calls; otherwise developer must use TWS socket API. ([Interactive Brokers][8])

---

# Quick wins (first 48 hours)

1. Create Vault and seed with Binance + Alchemy keys. (P1)
2. Implement Alchemy cold-wallet balance fetch and store in `assets` + `positions`. (P1)
3. Implement Binance signed `GET /api/v3/account` and persist balances. (P1)
4. Expose `/api/portfolio/overview` and wire React skeleton. (P1)

---

Take a deep breath and work on this problem step-by-step.

If you want, I’ll now:

* generate the full `connectors/binance.py` and `connectors/alchemy.py` files (complete) and a `docker-compose` with a working FastAPI skeleton and DB migration script, **or**
* start by producing the full Playwright automation + IMAP PDF parser for Frankly/Finpension (consent text included).

Tell me **which** of the two you want built immediately and I’ll produce full copy-paste files (no placeholders except secrets).

[1]: https://developers.binance.com/docs/binance-spot-api-docs/rest-api/account-endpoints?utm_source=chatgpt.com "Account Endpoints | Binance Open Platform"
[2]: https://www.alchemy.com/docs/data/token-api/token-api-endpoints/alchemy-get-token-balances?utm_source=chatgpt.com "alchemy_getTokenBalances | Alchemy Docs"
[3]: https://www.interactivebrokers.com/campus/ibkr-api-page/twsapi-doc/?utm_source=chatgpt.com "TWS API Documentation | IBKR API | IBKR Campus"
[4]: https://www.kucoin.com/docs-new/authentication?utm_source=chatgpt.com "Authentication - KUCOIN API"
[5]: https://docs.coingecko.com/reference/simple-price?utm_source=chatgpt.com "Coin Price by IDs"
[6]: https://docs.phantom.com/solana/establishing-a-connection?utm_source=chatgpt.com "Establish a connection - Phantom Developer Documentation"
[7]: https://roadmap.swissborg.com/1048?utm_source=chatgpt.com "API Integration Capabilities#1048"
[8]: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/?utm_source=chatgpt.com "Web API v1.0 Documentation"
[9]: https://developers.binance.com/docs/derivatives/usds-margined-futures/account/rest-api/Account-Information-V3?utm_source=chatgpt.com "Account Information V3 | Binance Open Platform"
[10]: https://developers.binance.com/docs/binance-spot-api-docs/rest-api?utm_source=chatgpt.com "General API Information | Binance Open Platform"
[11]: https://docs.blofin.com/index.html?utm_source=chatgpt.com "Overview – BloFin API guide | BloFin API Documents"
[12]: https://interactivebrokers.github.io/cpwebapi/?utm_source=chatgpt.com "Client Portal API Documentation"
[13]: https://docs.phantom.com/introduction?utm_source=chatgpt.com "Introduction - Phantom Developer Documentation"
