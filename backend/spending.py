"""Money spent per calendar month: Neon and Wise outflows plus cash withdrawals, each counted once.

- Neon: negative transactions, except moves into or out of a Space (same account).
- Wise: stored debits, except conversions and moves between the user's own balances
  (the API no longer provides statements, so only previously stored lines count).
- Cash: a withdrawal is spending in the month it was taken out. When the matching
  ATM debit is already in Neon or Wise (same amount within 3 days) that debit is the
  spending and the cash record only labels it, so nothing is counted twice whether
  the bank data arrives before or after the cash is recorded.

Net worth is never adjusted by a cash record: the bank balance already fell when the
cash left it, and cash in hand is treated as spent.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta

from backend.database import SQLiteRepository
from backend.sources.wise import INTERNAL_DETAIL_TYPES

MATCH_WINDOW_DAYS = 3


def _month_bounds(month: str) -> tuple[date, date]:
    year, mon = (int(p) for p in month.split("-"))
    return date(year, mon, 1), date(year, mon, monthrange(year, mon)[1])


def month_spending(repo: SQLiteRepository, month: str) -> dict:
    first, last = _month_bounds(month)
    window = timedelta(days=MATCH_WINDOW_DAYS)
    debits = repo.list_bank_debits((first - window).isoformat(), (last + window).isoformat(), INTERNAL_DETAIL_TYPES)
    cash = repo.list_cash_withdrawals((first - window).isoformat(), (last + window).isoformat())

    # Pair each cash withdrawal with at most one bank debit of the same amount nearby.
    unused = sorted(debits, key=lambda d: d["date"])
    matched_debit_ids: set[int] = set()
    unmatched_cash = []
    for c in sorted(cash, key=lambda c: (c["date"], c["id"])):
        c_date = date.fromisoformat(c["date"])
        match = next(
            (i for i, d in enumerate(unused)
             if i not in matched_debit_ids
             and abs(abs(d["amount_chf"]) - c["amount_chf"]) < 0.005
             and abs((date.fromisoformat(d["date"]) - c_date).days) <= MATCH_WINDOW_DAYS),
            None,
        )
        if match is None:
            unmatched_cash.append(c)
        else:
            matched_debit_ids.add(match)

    in_month = lambda d: first.isoformat() <= d <= last.isoformat()  # noqa: E731
    bank_total = sum(-d["amount_chf"] for d in unused if in_month(d["date"]))
    extra_cash = sum(c["amount_chf"] for c in unmatched_cash if in_month(c["date"]))
    cash_total = sum(c["amount_chf"] for c in cash if in_month(c["date"]))
    return {
        "month": month,
        "total_chf": round(bank_total + extra_cash, 2),
        "cash_chf": round(cash_total, 2),
    }


def recent_spending(repo: SQLiteRepository, today: date) -> list[dict]:
    """This month and last month, newest first."""
    this_month = today.strftime("%Y-%m")
    last_month = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    return [month_spending(repo, this_month), month_spending(repo, last_month)]
