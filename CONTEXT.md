# finance_dash

A local-first, privacy-first net-worth dashboard. This glossary fixes the
vocabulary used across the backend, frontend, and data sources so the same word
always means the same thing.

## Language

### Neon (CSV source)

**Anchor**:
A one-time *starting balance* (amount + date) the user sets for a CSV source.
The current balance is always derived as `Anchor + sum of Transactions on or
after the anchor date`. Conceptually set **once**; it stays editable in Settings
but any change triggers a "this recomputes your whole balance — are you sure?"
confirmation, since it should rarely change after the first save.
_Avoid_: opening balance, seed, baseline.

**Transaction**:
A single dated movement parsed from a Neon CSV row (`date` + signed `amount`).
Transactions are persisted and deduplicated so that re-uploading a file or
uploading overlapping monthly exports never double-counts.
_Avoid_: entry, line, movement.

**Space**:
A higher-interest savings pocket *inside* the same Neon account. It is still the
same money, so its Transactions are **merged into the single Neon balance** — no
separate line, and the `Spaces` CSV column is ignored. The Neon balance =
`Anchor + sum of all Transactions on or after the anchor date`.
_Avoid_: pot, sub-account, separate holding.

### Holdings & net worth

**Holding**:
A single valued line on the dashboard (e.g. `Neon (main)`, `Neon – Space`,
`Finpension`, a Binance asset). `value_chf` is signed; negative = liability.

**Liquidity bucket**:
A runtime classification of each Holding into **Disponible** (available),
**Investi** (invested), or **Bloqué** (locked), derived from `asset_class`.
Never persisted.

## Example dialogue

> **Dev:** When the May CSV says `600.00 … Spaces=yes`, does that add to the Neon balance?
> **Expert:** Yes — a *Space* is just a higher-interest pocket of the same
> account. Same money. Merge it straight into the one Neon balance; ignore the
> Spaces column.
> **Dev:** And if you upload June next month?
> **Expert:** Just add it. I set the *Anchor* once back in May; I never want to
> touch it again. The balance should stay correct on its own forever.
