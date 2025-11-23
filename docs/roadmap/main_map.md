ATTENTION: Roadmap subject to change.

# Executive summary
Developer-ready, phased todo list to autonomously fetch authenticated balances/transactions across all providers (exchanges, brokers, on-chain wallets, pension portals without APIs). Phases: Discovery → MVP → Expand → Harden → Operate. Includes per-provider tasks, fallback automation for providers without APIs, and authoritative links.

---

# Phase 0 — Discovery (P1)
- Inventory providers, required permissions, and required API scopes for each provider.
- Store secrets plan: choose Vault or local dev alternative; define TLS & storage requirements.
- Save canonical provider docs into repo `docs/providers/`.
- Create repo skeleton: `connectors/`, basic Postgres schema plan, CI checklist.

# Phase 1 — MVP (P1)
Goal: fetch authenticated balances + transactions for primary providers and present unified portfolio snapshot.
- Implement connectors (read-only where possible) and a DB ingest pipeline for:
  - Binance (spot + futures)
  - Alchemy (EVM cold wallets)
  - Phantom (Solana wallet flow + indexer)
  - Interactive Brokers (Client Portal or IB Gateway)
  - KuCoin, Bitget, OKX, MEXC, CoinEx, Bybit
  - Cold wallets (EVM + Solana)
- Implement fallback for pension/portal providers with no API:
  - SwissBorg, Frankly, Finpension — IMAP/statement ingest + Playwright as last resort
- Expose minimal API: `/api/portfolio/overview`, account & connector endpoints.
- Local dev: docker-compose skeleton and DB migration plan.

# Phase 2 — Expand (P2)
- Add derivatives/futures endpoints & user websocket order streams for exchanges that support them.
- Reconciliation jobs: reconcile exchange deposits/withdrawals with on-chain receipts.
- Price enrichment (CoinGecko primary, OpenFIGI for equities).

# Phase 3 — Harden (P2/P3)
- Secrets rotation policy (schedule, Vault usage).
- Network hardening: IP allowlists, egress policies, TLS/mTLS where required.
- Robust retry/backoff, circuit breaker, rate-limit handling, and connector isolation.

# Phase 4 — Operate (P2)
- Monitoring & alerting (Prometheus/Grafana metrics per connector).
- Backfill & idempotency rules; reprocess CLI for historical ingestion.
- Operational runbooks: connector onboarding, failure recovery, credential rotation.

---

# Per-provider minimal todos (keep provider list and canonical docs)
- Binance: implement signed REST calls and user data stream; IP allowlist; observe weights/rate limits. [1]
- Alchemy: token balances, token metadata, asset transfer history for EVM cold wallets. [2]
- Interactive Brokers: run IB Gateway/Client Portal locally; use CP Web API or TWS/ib_insync. [3][12]
- KuCoin, Bitget, OKX, MEXC, CoinEx, Bybit: implement read-only connectors; provider-specific signing. [4]
- Phantom (Solana): Wallet Adapter flow to get user address; use Helius/QuickNode or RPC for token accounts. [6][13]
- CoinGecko: canonical price provider for crypto/token prices. [5]
- BloFin: treat as exchange if API available; confirm docs. [11]
- SwissBorg, Frankly, Finpension: treat as no-public-API — implement IMAP + PDF ingestion and Playwright fallback with explicit consent and legal check. [7]

---

# On-chain wallets & canonicalization
- Use Alchemy / QuickNode / Helius for indexing; canonicalize tokens by (chain, contract). Resolve decimals & metadata; map to CoinGecko ID where possible. [2][13]

# Fallback automation for providers without APIs
- Primary: obtain user consent and request forwarded statements via dedicated email (IMAP).
- Secondary: Playwright headless automation only after TOS/legal check and explicit consent; store consent records and encrypt credentials.

# Data model & operations (high level)
- Minimal tables: accounts, assets, positions, transactions, price_cache, connector_state, audit_logs.
- Idempotency: dedupe on provider_tx_id; provide reprocess CLI.
- Expose connector metrics and connector_last_success timestamps.

# Security & legal
- Minimum scope: read-only API keys; never enable withdrawals.
- Store secrets in Vault or equivalent; encrypt at rest; rotate keys regularly.
- Require explicit user consent for scraping or credential storage; check TOS before Playwright usage.

# Quick wins (first 48 hours)
- Seed Vault with Binance + Alchemy keys (dev).
- Implement Alchemy cold-wallet balance ingest.
- Implement Binance account balance ingest.
- Expose `/api/portfolio/overview` and wire simple frontend skeleton.

---

# References (canonical docs)
[1]: https://developers.binance.com/docs/binance-spot-api-docs/rest-api/account-endpoints?utm_source=chatgpt.com "Binance Account Endpoints"  
[2]: https://www.alchemy.com/docs/data/token-api/token-api-endpoints/alchemy-get-token-balances?utm_source=chatgpt.com "Alchemy token balances"  
[3]: https://www.interactivebrokers.com/campus/ibkr-api-page/twsapi-doc/?utm_source=chatgpt.com "Interactive Brokers TWS API"  
[4]: https://www.kucoin.com/docs-new/authentication?utm_source=chatgpt.com "KuCoin Authentication"  
[5]: https://docs.coingecko.com/reference/simple-price?utm_source=chatgpt.com "CoinGecko simple/price"  
[6]: https://docs.phantom.com/solana/establishing-a-connection?utm_source=chatgpt.com "Phantom Developer Documentation"  
[7]: https://roadmap.swissborg.com/1048?utm_source=chatgpt.com "SwissBorg Roadmap"  
[8]: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/?utm_source=chatgpt.com "IBKR Client Portal Web API"  
[9]: https://developers.binance.com/docs/derivatives/usds-margined-futures/account/rest-api/Account-Information-V3?utm_source=chatgpt.com "Binance Futures Account Info"  
[10]: https://developers.binance.com/docs/binance-spot-api-docs/rest-api?utm_source=chatgpt.com "Binance General API Info"  
[11]: https://docs.blofin.com/index.html?utm_source=chatgpt.com "BloFin API docs"  
[12]: https://interactivebrokers.github.io/cpwebapi/?utm_source=chatgpt.com "Client Portal API Documentation"  
[13]: https://docs.phantom.com/introduction?utm_source=chatgpt.com "Phantom Introduction"

---

If you want, I can now generate:
- a minimal todo checklist as individual issues, or
- full connector task templates per provider (no code).
Which do you want next?
