# finance_dash — v1 Plan

*Last updated: 2026-06-17*

This document mirrors the PRD v1 scope for agent context and human reference.

## Scope v1

Local-first personal finance dashboard. No cloud hosting, no user accounts, no
auth. Single-user, single-machine, zero operational cost beyond the machine
itself.

### Data sources (ingestion)

| Source | Type | Method |
|--------|------|--------|
| Neon | CSV | Manual upload via UI |
| Finpension | Manual | User enters CHF value in form |
| Binance | API | Read-only keys in `.env`, syncable via button/cron |

### Backend

- **Stack:** FastAPI + SQLite (single file)
- **Host:** `127.0.0.1:8000` (dev) or behind Tailscale (prod)
- **Sync:** `POST /sync/all` triggers all configured sources, snapshots net
  worth per source + total
- **FX:** Frankfurter API for CHF↔USD conversion, cached in SQLite

### Frontend

- **Stack:** React + Vite + TypeScript + Tailwind
- **Dev:** Vite dev server on `:5173`, proxied API calls to backend
- **Prod:** Static build served by FastAPI (single process)
- **Pages:** Dashboard (net worth, buckets, delta, sources), Update (manual
  inputs, CSV upload), Settings (theme, currency, inline edit holdings)

### Deployment

- **Machine:** User's Linux machine behind Tailscale
- **No public ports** — access only via Tailscale IP
- **Cron:** Daily 06:00 `curl http://localhost:8000/sync/all` (no embedded
  scheduler)
- **Backup:** `cp` of SQLite file to secondary disk via cron

## Out of scope (explicitly deferred)

- User accounts / auth / multi-tenancy
- Cloud hosting or any public-exposed port
- Embedded Python scheduler (cron is the scheduler)
- Any new data sources beyond Neon, Finpension, Binance
- E2E tests, CI/CD pipeline
- Desktop packaging / Electron
