# Neon CSV upload

Once a month the captain exports the Neon statement CSV in the Neon app and uploads it on the Update page. The transactions of a file not imported before are stored, the Neon balance becomes the anchor plus all stored transactions, and the Dashboard's Neon row, total and `Neon CSV imported` line move at once. Uploading the same file again adds nothing and says so. The anchor (a known balance on a date) is set in Settings.

## Sub-features

- `neon-upload` stores the transactions of a new statement and updates the Neon balance.
- `neon-reupload` accepts the same file again without storing anything twice.
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
- **Reject.** Copy the June fixture to `<proof>/neon-june.txt` and upload it: `$S browser $RUN upload "$($S ref $RUN 'button "Upload Neon CSV"')" "<proof>/neon-june.txt"`. The status reads `Only .csv files are accepted.` and `$S sql $RUN "select count(*) from neon_uploads"` prints `0`.
- **Upload.** Pick the June fixture. Run `$S browser $RUN upload "$($S ref $RUN 'button "Upload Neon CSV"')" "$PWD/backend/tests/fixtures/2026_6_account_statements_neon.csv"` (absolute path), then `$S browser $RUN wait "Neon CSV uploaded"`. The status reads `Neon CSV uploaded: 9 new transaction(s), balance = CHF 1'350.00.`
- **Stored once.** Read back. `$S sql $RUN "select count(*), sum(amount) from neon_transactions"` prints `9|1350.0`; `$S api $RUN GET /holdings` has a `neon` holding with `value_chf` `1350.0`; a new file appears in `data/csv_archive/neon/` in the checkout.
- **Re-upload.** Upload the same file again with the same command, then `$S browser $RUN wait "already imported"`. The status reads `This file was already imported — nothing to add. Balance unchanged at CHF 1'350.00.`, the count is still `9` and `select count(*) from neon_uploads` still prints `1`.
- **Dashboard.** Open `/`. `Neon CSV imported today HH:MM`, `link "Neon 16 Jun CHF 1'350"`, and the total includes `1'350`.
- **Anchor.** Set a known balance. Run `$S browser $RUN open "$($S url $RUN)/settings"`, `$S browser $RUN click "$($S ref $RUN 'spinbutton "Month"')"`, `$S browser $RUN type 06012026`, `$S browser $RUN fill "$($S ref $RUN 'textbox "e.g. 5000.00"')" 1000`, `$S browser $RUN click "$($S ref $RUN 'button "Set Anchor"')"`, then `$S browser $RUN wait "Anchor saved"`. The status reads `Anchor saved. Neon balance recomputed: CHF 2'350.00 (9 transactions).` (1000 plus the transactions dated on or after 2026-06-01; the count is every stored transaction), `Current anchor: 2026-06-01 — CHF 1'000.00` appears, and `$S sql $RUN "select key, value from settings where key like 'neon_anchor%'"` prints both values.
- **Change the anchor.** Click `spinbutton "Month"`, `type 06102026`, then `button "Update Anchor"`. A dialog reads `Change Neon Anchor?` with `button "Cancel"` and `button "Confirm"`. Choose `Confirm` and `wait "Anchor saved"`: the status reads `… CHF 3'110.00 (9 transactions).` and the `sql` query prints `2026-06-10`. `Cancel` closes the dialog and stores nothing.
- **Proof.** After the upload and after the re-upload: `$S browser $RUN snapshot --full | tee <proof>/neon-NN.aria.txt`, `$S browser $RUN screenshot <proof>/neon-NN.png`, and the `sql` and `api` outputs saved next to them.

## Gotchas

- Every accepted upload copies the file into `<checkout>/data/csv_archive/neon/` (not into the scratch dir), a re-upload of the same file included. `$S stop $RUN` removes only the copies this run added; files that were there before launch stay. Never run this from the captain's checkout.
- A file counts as already imported only when it is byte-for-byte the same file. A different file that repeats some transactions stores them again; the fixtures do not overlap, so this recipe does not show it.
- The fixtures are from 2026, May and June; on the Dashboard Neon stays stale (orange, a link) because Neon's date is its latest transaction, not the upload day. That is the product's rule, not a failed upload.
- `upload` needs an absolute path and the ref of the hidden file input, which the snapshot names `button "Upload Neon CSV"`. Go through `$S browser`: it runs the upload from the file's directory, which `chrome-devtools-axi` requires.
- A file not ending in `.csv` is refused in the page (`Only .csv files are accepted.`) before any request.
- Once an anchor exists, `Update Anchor` opens a confirmation (`Change Neon Anchor?`): choose `button "Confirm"`.
- `Current anchor: …` echoes the date and amount typed in the form, saved or not: after `Cancel` it still shows the unsaved values. Read the stored anchor with `sql`, never from that line.
