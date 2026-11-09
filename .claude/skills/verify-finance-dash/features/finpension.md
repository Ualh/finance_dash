# Finpension value

Finpension has no API, so once a month the captain types the value shown in the Finpension app on the Update page. The figure replaces the previous one, gets today's date, and moves the Dashboard total at once.

## Sub-features

- `fin-save` stores a new Finpension value and confirms it.
- `fin-hint` shows the current value as the field's placeholder.
- `fin-invalid` refuses an entry that is not a number.

## How to get to it (user POV)

- On the Update page (`link "✏️ Update"` or `/update`), the `Finpension (CHF)` field under `This month`, then `button "Save"`.
- From the Dashboard, choose the orange `link "Finpension …"` row (stale Finpension), which opens the Update page.

## Driving it with control.sh

Preconditions:

- Baseline instance, 390 px wide.

- **Open the Update page.** Run `$S browser $RUN open "$($S url $RUN)/update"`. The snapshot has `textbox "Finpension (CHF)"` and `button "Save"`.
- **Invalid entry.** Fill `abc` and save. Run `$S browser $RUN fill "$($S ref $RUN 'textbox "Finpension (CHF)"')" abc` and `$S browser $RUN click "$($S ref $RUN 'button "Save"')"`. The status reads `Enter the value in CHF.` and `$S sql $RUN "select count(*) from holdings where source='finpension'"` prints `0`.
- **Save.** Fill `42000` and save, then `$S browser $RUN wait "Finpension saved"`. The status reads `Finpension saved: CHF 42'000.` and the field is empty again.
- **Stored.** `$S sql $RUN "select value_chf, last_updated from holdings where source='finpension'"` prints `42000.0` and today's timestamp.
- **Hint.** Reload the page (`open` it again). The field's placeholder is `42000`: `$S browser $RUN eval "document.getElementById('finpension').placeholder"`.
- **Dashboard.** Open `/`. The row `"Finpension"` shows today's date and `CHF 42'000` and is no longer a link (not stale); the total includes it.
- **Proof.** Save the snapshot printed after `Save`, a screenshot of the status line, the `sql` read-back, and a screenshot of the Dashboard.

## Gotchas

- `button "Save"` must match exactly; `button "Save holding"` further down is the Other holding form.
- Saving again replaces the value; it never adds a second Finpension row.
- The status line disappears on reload; screenshot it before navigating.
