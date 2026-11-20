"""Calendar months as the curve counts them: month keys ("2026-11") and their last days."""
from __future__ import annotations

from datetime import date, timedelta


def last_day_of_month(day: date) -> date:
    return date(day.year + day.month // 12, day.month % 12 + 1, 1) - timedelta(days=1)


def month_end(month: str) -> date:
    """"2026-11" → 2026-11-30."""
    return last_day_of_month(date.fromisoformat(f"{month}-01"))


def next_month(month: str) -> str:
    return (month_end(month) + timedelta(days=1)).strftime("%Y-%m")


def month_ends(first: date, stop: date) -> list[date]:
    """The last day of every month from `first`'s month on, keeping only days before `stop`."""
    days: list[date] = []
    end = last_day_of_month(first)
    while end < stop:
        days.append(end)
        end = last_day_of_month(end + timedelta(days=1))
    return days
