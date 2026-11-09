# Cash withdrawals

When the captain takes cash out, they record the amount, the date and an optional note on the Update page. The last five records are listed with a delete button. Cash counts as spent in its month (shown on the Dashboard as `CHF … cash`) but never changes net worth; a matching ATM debit within 3 days is counted once.

## Sub-features

- `cash-record` stores an amount, a date and a note.
- `cash-list` shows the last five records, newest first.
- `cash-delete` removes a record.
- `cash-invalid` refuses an empty, zero or non-numeric amount.
- `cash-spending` adds the amount to that month's spending without changing net worth.

## How to get to it (user POV)

- On the Update page (`link "✏️ Update"` or `/update`), the `Cash withdrawal` section: `textbox "Amount (CHF)"`, the `Date` field (today by default), `textbox "Note"`, `button "Record cash"`.
- Delete with `button "Delete <YYYY-MM-DD> withdrawal"` next to a listed record.

## Driving it with control.sh

Preconditions:

- Baseline instance, 390 px wide, no cash recorded.

- **Open the Update page.** Run `$S browser $RUN open "$($S url $RUN)/update"`.
- **Invalid amount.** Choose record with the amount empty. Run `$S browser $RUN click "$($S ref $RUN 'button "Record cash"')"`. The status reads `Enter the amount in CHF.` and `$S sql $RUN "select count(*) from cash_withdrawals"` prints `0`.
- **Record.** Run `$S browser $RUN fill "$($S ref $RUN 'textbox "Amount (CHF)"')" 200`, `$S browser $RUN fill "$($S ref $RUN 'textbox "Note"')" "ATM verify"`, `$S browser $RUN click "$($S ref $RUN 'button "Record cash"')"`, then `$S browser $RUN wait "cash recorded"`. The status reads `CHF 200 cash recorded.` and the list shows `"<today>"`, `" · ATM verify"`, `"CHF 200"` and `button "Delete <today> withdrawal"`.
- **Stored.** `$S sql $RUN "select date, amount_chf, note from cash_withdrawals"` prints `<today>|200.0|ATM verify`.
- **Spending, not net worth.** Open `/`. The current month reads `Spent in <Month> CHF 200` with `CHF 200 cash`, and the net worth total is unchanged from before the record.
- **Delete.** Back on `/update`, run `$S browser $RUN click "$($S ref $RUN 'button "Delete <today> withdrawal"')"` with today's date. The row disappears and the `sql` query prints no rows.
- **Proof.** The snapshot after `Record cash`, a screenshot of the list, the Dashboard spending screenshot, and the `sql` outputs before and after delete.

## Gotchas

- To record another date, click `spinbutton "Month Month"` and `type MMDDYYYY`; `fill` on the date field does not reach the form.
- Delete has no confirmation and is immediate.
- Two records on the same date have the same button name; the first match is the newest.
- The matching with ATM debits needs Neon or Wise rows within 3 days of the cash date; the June fixtures do not overlap today's date, so `cash-spending` here shows the cash alone.
