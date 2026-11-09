# Dashboard

The Dashboard is the one screen the captain reads: net worth, the change since the end of last month with a month-by-month curve, when the last sync and the last Neon import happened, one row per source with the date its figure is valid for (orange and a link to the Update page when a manual source is older than 35 days), and what was spent this month and last month. It can show amounts in CHF or USD and has a sync button.

## Sub-features

- `dash-total` shows net worth as the sum of every source.
- `dash-sources` lists Neon and Finpension always, plus every other holding, each with its date and amount; a stale manual source links to `/update`.
- `dash-last-updates` shows `Synced …` and `Neon CSV imported …`, orange when missing or old.
- `dash-spending` shows `Spent in <this month>` and `Spent in <last month>`, with a `CHF … cash` note when cash was recorded.
- `dash-currency` switches every amount between CHF and USD.
- `dash-sync` runs the sync of the automatic sources (Binance, Wise, IBKR); a dry run in this stand-in.
- `dash-curve` shows the month-by-month curve and `… since last month` once a previous month has a snapshot.

## How to get to it (user POV)

- Open the app root `/`.
- Choose `link "📊 Dashboard"` in the bottom tab bar (phone width).
- Choose a USD or CHF button in the Dashboard header, or in Settings under `Display Currency`.
- Choose `button "Sync now"` in the Dashboard header (on the phone, a pull-down from the top also syncs).

## Driving it with control.sh

Preconditions:

- Baseline instance, page at `/` and 390 px wide.
- For a non-empty dashboard, first run the [Finpension](./finpension.md) and [Neon CSV](./neon-csv.md) recipes.

- **Fresh state.** Open the root. Run `$S browser $RUN open "$($S url $RUN)/"`. The snapshot has `heading "Net worth"`, `"CHF 0"`, `"Synced"` … `"never"`, `"Neon CSV imported"` … `"never"`, `link "Neon Never —"` and `link "Finpension Never —"` (both stale, so both link to `/update`), and two `Spent in` lines at `CHF 0`.
- **Totals after updates.** After saving Finpension `42000` and uploading the June Neon fixture, reopen `/`. The total reads `CHF 43'350`; `Neon CSV imported today HH:MM`; `link "Neon 16 Jun CHF 1'350"` (still stale: the fixture's last transaction is in June); `"Finpension"` with today's date and `CHF 42'000`, not a link. Read back with `$S api $RUN GET /dashboard`: `total_chf` is `43350.0`.
- **Currency.** Choose USD. Run `$S browser $RUN click "$($S ref $RUN 'button "USD"')"`. The total shows `$` and `"Old exchange rate"` appears: outbound HTTP is blocked, so the rate falls back to 1.0. `$S sql $RUN "select value from settings where key='display_currency'"` prints `USD`. Choose `button "CHF"` to restore.
- **Sync (dry run).** Choose sync. Run `$S browser $RUN click "$($S ref $RUN 'button "Sync now"')"`. The page reloads its data and still says `Synced never`. `$S sql $RUN "select count(*) from sync_log"` prints `0` (no source was called) and `$S sql $RUN "select snapshot_date, total_chf from nw_snapshots where source='total'"` has a row for today (the sync still writes the day's snapshot).
- **Spending with cash.** After the [cash recipe](./cash-withdrawals.md) records `200` today, reopen `/`. The current month's line reads `Spent in <Month> CHF 200` with `CHF 200 cash`.
- **Proof.** Capture the populated state. Run `$S browser $RUN snapshot --full | tee <proof>/dashboard.aria.txt` and `$S browser $RUN screenshot <proof>/dashboard.png --full-page`.

## Gotchas

- `dash-curve` and `… since last month` need a snapshot from a previous month. A fresh instance only has today's, and no user path writes a past date, so both stay hidden. Report `dash-curve` as not verified: precondition "a snapshot from an earlier month" cannot be created through the app in a fresh instance. Do not write rows into the database to get around it.
- The sync never contacts a source here, so `Synced` stays `never` and no red dot appears. Real syncs, their errors and the Wise note are not verifiable in this stand-in.
- USD amounts use the fallback rate 1.0 unless the instance was launched with `FD_VERIFY_ALLOW_FX=1`. Do not report USD figures as correct conversions without it.
- The currency choice is stored server-side (`display_currency` setting) and survives reloads; restore CHF before driving other recipes that assert `CHF` amounts.
- At phone width the floating `Noter` pill covers the centre of `link "⚙️ Settings"`: a click on that tab opens the notes panel instead. Open `/settings` by URL and record that you did.
