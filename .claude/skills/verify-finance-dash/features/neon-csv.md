# Neon CSV upload

Once a month the captain exports the Neon statement CSV in the Neon app and uploads it on the Update page. Every new transaction is stored once, the Neon balance becomes the anchor plus all stored transactions, and the Dashboard's Neon row, total and `Neon CSV imported` line move at once. Uploading the same file again adds nothing and says so. The anchor (a known balance on a date) is set in Settings.

## Sub-features

- `neon-upload` stores the transactions of a new statement and updates the Neon balance.
- `neon-reupload` accepts a file already imported without storing anything twice.
- `neon-reject` refuses a file that is not a CSV.
- `neon-anchor` sets or changes the anchor in Settings and recomputes the balance.

## How to get to it (user POV)

- On the Update page (`link "✏️ Update"` or `/update`), choose `Upload Neon CSV` under `This month` and pick the file.
- From the Dashboard, choose the orange `link "Neon …"` row (stale Neon), which opens the Update page.
- In Settings (`/settings`), the `Neon Anchor` card: `Anchor Date`, `Anchor Amount (CHF)` and `button "Set Anchor"` (`button "Update Anchor"` once one exists, behind a `Change Neon Anchor?` confirmation).

## Driving it with control.sh

Preconditions:

- Baseline instance, 390 px wide, no Neon transactions yet.
- Statement files: the repo's fixtures `backend/tests/fixtures/2026_6_account_statements_neon.csv` (9 transactions, June 2026, sum `1350.00`) and `backend/tests/fixtures/2026_5_account_statements_neon.csv` (May 2026). Never upload a real statement.

- **Open the Update page.** Run `$S browser $RUN open "$($S url $RUN)/update"`. The snapshot has `heading "This month"` and `button "Upload Neon CSV" value="No file chosen"`.
- **Upload.** Pick the June fixture. Run `$S browser $RUN upload "$($S ref $RUN 'button "Upload Neon CSV"')" "$PWD/backend/tests/fixtures/2026_6_account_statements_neon.csv"` (absolute path), then `$S browser $RUN wait "Neon CSV uploaded"`. The status reads `Neon CSV uploaded: 9 new transaction(s), balance = CHF 1'350.00.`
- **Stored once.** Read back. `$S sql $RUN "select count(*), sum(amount) from neon_transactions"` prints `9|1350.0`; `$S api $RUN GET /holdings` has a `neon` holding with `value_chf` `1350.0`; a new file appears in `data/csv_archive/neon/` in the checkout.
- **Re-upload.** Upload the same file again with the same command, then `$S browser $RUN wait "already imported"`. The status reads `This file was already imported — nothing to add. Balance unchanged at CHF 1'350.00.` and the count is still `9`.
- **Dashboard.** Open `/`. `Neon CSV imported today HH:MM`, `link "Neon 16 Jun CHF 1'350"`, and the total includes `1'350`.
- **Anchor.** Open `/settings`. Click `$S ref $RUN 'spinbutton "Month"'`, run `$S browser $RUN type 06012026`, fill `$S ref $RUN 'textbox "e.g. 5000.00"'` with `1000`, choose `button "Set Anchor"`, then `wait "Anchor saved"`. The status reads `Anchor saved. Neon balance recomputed: CHF …` with the transaction count, `Current anchor: 2026-06-01 — CHF 1'000.00` appears, and `$S sql $RUN "select key, value from settings where key like 'neon_anchor%'"` prints both values. The Neon balance is now 1000 plus the transactions dated on or after 2026-06-01.
- **Proof.** After the upload and after the re-upload: `$S browser $RUN snapshot --full | tee <proof>/neon-NN.aria.txt`, `$S browser $RUN screenshot <proof>/neon-NN.png`, and the `sql` and `api` outputs saved next to them.

## Gotchas

- Every upload copies the file into `<checkout>/data/csv_archive/neon/` (not into the scratch dir). `$S stop $RUN` removes only the copies this run added; files that were there before launch stay. Never run this from the captain's checkout.
- The fixtures are from 2026, May and June; on the Dashboard Neon stays stale (orange, a link) because Neon's date is its latest transaction, not the upload day. That is the product's rule, not a failed upload.
- `upload` needs an absolute path and the ref of the hidden file input, which the snapshot names `button "Upload Neon CSV"`.
- A file not ending in `.csv` is refused in the page (`Only .csv files are accepted.`) before any request; prove `neon-reject` with a copy of a fixture renamed to `.txt` in your proof dir.
- Once an anchor exists, `Update Anchor` opens a confirmation (`Change Neon Anchor?`): choose `button "Confirm"`.
