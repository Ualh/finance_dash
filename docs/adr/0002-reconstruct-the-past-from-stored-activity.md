# Reconstruct the past from stored activity, and show a gap where it does not add up

## Status

accepted

## Context & decision

Recorded snapshots start the day each source was connected, but the history backfill keeps
years of raw activity (Binance flows from 2022, the Wise activity feed, Neon statements). The
curve should start at each account's first activity. We rebuild one **Reconstructed point**
per account and month-end from that activity, store it in `nw_snapshots` flagged
`reconstructed`, and never write it over a **Recorded snapshot**. Rebuilding is an offline
step (`python -m backend.history`, `--reconstruct-only`), not part of a request, because it
fetches public prices.

The stored activity is incomplete: Binance serves trades only for pairs still listed, and
the Wise feed does not say whether a transfer was paid from the balance or from a bank. So
each walk through the activity starts from a balance known for certain and stops where the
balance it computes cannot have happened (an asset short by more than a dollar, a Wise
balance below zero, a payment the feed does not split). What lies between is a **Gap**:
stored, listed under the curve, and left out of the months it covers.

## Considered options

- **Replay forward from zero only** — exact at the start, but one missing trade skews
  every later month by the price moves since; on the real data Binance went negative.
  Rejected as the only walk; kept for the months before the backward walk stops holding up.
- **Walk backward from a known balance only** — tied to a real balance (the earliest
  stored Binance daily snapshot), but a missing inflow shows up as holdings before the
  account existed. Kept for the months it holds up.
- **Fill gaps by guessing** (spread the unexplained amount, assume transfers were paid
  from the balance) — rejected: a made-up number on the curve reads as fact.

## Consequences

- `nw_snapshots.reconstructed` and the `history_gaps` table; the curve sums the recorded
  total and the reconstructed sources it did not cover, per month.
- Months every account misses are holes; partial months name the accounts they leave out.
- Prices are cached in `fx_rates` (Binance month closes as `asset/USD`, ECB rates as
  `currency/CHF`), so a later rebuild only fetches new months and coins Binance does not quote.
