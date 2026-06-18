# Persist Neon transactions and derive the balance from a one-time anchor

## Status

accepted

## Context & decision

The v1 PRD modelled each CSV source as a single derived **balance** and stored no
transactions, on the assumption that one uploaded file contains every transaction
since a starting point. Neon exports are **per-month**, so re-deriving from the
file just uploaded silently dropped every prior month (uploading June overwrote
May). To make "set the starting balance once, then it stays correct forever"
true, we now **persist every parsed Neon Transaction** and derive the balance as
`Anchor + sum of all stored Transactions on or after the anchor date`. The Neon
**Space** is treated as the same money and merged into this single balance (the
`Spaces` CSV column is ignored).

## Considered options

- **Re-anchor each month** — user resets the anchor to the previous month-end
  before each upload. Rejected: manual, error-prone, breaks "set once".
- **Require one cumulative export** — user always exports the full range since the
  anchor. Rejected: fights the natural monthly-export habit.
- **Persist transactions, accumulate** (chosen) — robust to any upload cadence and
  to re-uploads.

## Consequences

- New `neon_transactions` table (the PRD's 5-table schema becomes 6). This is the
  deliberate deviation from the "balances only" stance.
- Re-uploads are made idempotent by **replace-by-date-range**: importing a file
  deletes all stored Transactions whose date falls within that file's
  `[min_date, max_date]` span, then inserts the file's rows. Months accumulate;
  re-uploading a month cleanly replaces it; genuine same-day duplicates within a
  file are preserved.
- The **Anchor** stays editable in Settings but a change triggers a
  "this recomputes your whole balance" confirmation, since changing it re-derives
  everything.
