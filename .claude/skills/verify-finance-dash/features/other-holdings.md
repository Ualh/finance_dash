# Other holdings

Any account without an API (a fund, a pillar 3a, a foreign account) is added by hand on the Update page: a name, a category that decides whether it counts as available, invested or locked, an amount and a currency (converted to CHF). It then has its own row on the Dashboard, and its value can be edited later in Settings under `Manual Holdings`.

## Sub-features

- `hold-add` stores a holding with name, category, amount and currency.
- `hold-fx` converts a non-CHF amount to CHF and says which rate was used.
- `hold-invalid` refuses a missing name or a non-numeric amount.
- `hold-dashboard` shows the holding as its own source row and in the total.
- `hold-edit` changes the CHF value from Settings.

## How to get to it (user POV)

- On the Update page (`link "✏️ Update"` or `/update`), the `Other holding` section: `textbox "Name"`, `combobox "Category"`, `textbox "Amount"`, `combobox "Currency"`, `button "Save holding"`.
- In Settings (`/settings`), `Manual Holdings`: `button "Edit"` next to a holding, then the value textbox, `button "Save"` or `button "Cancel"`.

## Driving it with control.sh

Preconditions:

- Baseline instance, 390 px wide, no holding named `Verify fund`.

- **Open the Update page.** Run `$S browser $RUN open "$($S url $RUN)/update"`.
- **Missing name.** Choose `button "Save holding"` with every field empty. The status reads `Please enter a name for the holding.`
- **Add.** Run `$S browser $RUN fill "$($S ref $RUN 'textbox "Name"')" "Verify fund"`, `$S browser $RUN fill "$($S ref $RUN 'combobox "Category"')" "ETF / fund — invested"`, `$S browser $RUN fill "$($S ref $RUN 'textbox "Amount"')" 12000`, `$S browser $RUN click "$($S ref $RUN 'button "Save holding"')"`, then `$S browser $RUN wait "Saved"`. The status reads `Saved "Verify fund" — CHF 12'000.00.`
- **Stored.** `$S sql $RUN "select source, asset_class, value_chf, native_currency from holdings where label='Verify fund'"` prints `verify_fund|etf|12000.0|CHF`.
- **Dashboard.** Open `/`. A `"Verify fund"` row shows today's date and `CHF 12'000`, and the total includes it.
- **Edit in Settings.** Open `/settings` by URL. `Manual Holdings` lists `"Verify fund"`, `"etf"`, `"verify_fund"`, `"12'000"`. Choose `$S ref $RUN 'button "Edit"'`, fill `$S ref $RUN 'textbox value="12000"'` with `15000`, choose `button "Save"`. The row shows `15'000` and `sql` prints `value_chf` `15000.0`.
- **Proof.** The snapshot after `Save holding`, the `sql` read-back, the Dashboard row screenshot, and the Settings row before and after the edit.

## Gotchas

- A non-CHF currency asks the FX service. With outbound blocked (the default) the status ends `(USD → CHF @ 1, stale rate)` and the CHF value equals the amount: that proves the fallback, not a real conversion. Launch with `FD_VERIFY_ALLOW_FX=1` to prove `hold-fx` with a live rate.
- The holding's id is its name in lower case with underscores; saving the same name again replaces it instead of adding a second row.
- In Settings the edit textbox has no label; find it by its current value (`textbox value="12000"`).
- Reach Settings by URL at phone width: the `Noter` pill covers the centre of the Settings tab.
