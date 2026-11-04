"""Net-worth snapshots: one row per source and one `total` row per day, feeding the monthly curve."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from backend.database import SQLiteRepository


def record_snapshot(repo: SQLiteRepository, day: Optional[str] = None) -> None:
    """Write (or overwrite) today's snapshot so the curve reflects every change, not just syncs."""
    day = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for src in repo.list_sources():
        agg = repo.get_source_aggregate(src)
        repo.upsert_snapshot(day, src, agg["total_chf"], agg["buckets"]["available"],
                             agg["buckets"]["invested"], agg["buckets"]["locked"])
    total = repo.get_aggregate_holdings()
    repo.upsert_snapshot(day, "total", total["total_chf"], total["buckets"]["available"],
                         total["buckets"]["invested"], total["buckets"]["locked"])


def monthly_history(repo: SQLiteRepository, current_total: float, today: Optional[date] = None) -> dict:
    """Net worth at the end of each month, plus the change since the end of last month.

    A month's value is its last snapshot; the current month is the live total.
    """
    today = today or datetime.now(timezone.utc).date()
    current_month = today.strftime("%Y-%m")
    by_month: dict[str, dict] = {}
    for snap in repo.list_total_snapshots():
        by_month[snap["snapshot_date"][:7]] = snap  # ordered by date, so the last one wins

    months = [
        {"month": m, "date": s["snapshot_date"], "total_chf": s["total_chf"]}
        for m, s in sorted(by_month.items())
        if m < current_month
    ]
    previous = months[-1] if months else None
    months.append({"month": current_month, "date": today.isoformat(), "total_chf": current_total})

    change = None
    if previous is not None:
        change = {
            "amount_chf": round(current_total - previous["total_chf"], 2),
            "since": previous["date"],
            "pct": round((current_total - previous["total_chf"]) / previous["total_chf"] * 100, 2)
            if previous["total_chf"] else None,
        }
    return {"months": months, "change_since_last_month": change}
