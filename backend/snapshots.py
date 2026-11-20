"""Net-worth snapshots: one row per source and one `total` row per day, feeding the monthly curve."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from backend.database import SQLiteRepository
from backend.months import month_end, next_month


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


def _gaps_before_recording(gaps: list[dict], first_recorded: dict[str, str]) -> list[dict]:
    """Gaps cut back to the day before their source was first recorded, in case it was recorded after the rebuild."""
    clipped = []
    for gap in gaps:
        first = first_recorded.get(gap["source"])
        if first is not None and (gap["end"] is None or gap["end"] >= first):
            gap = {**gap, "end": (date.fromisoformat(first) - timedelta(days=1)).isoformat()}
        if gap["start"] is None or gap["end"] is None or gap["start"] <= gap["end"]:
            clipped.append(gap)
    return clipped


def _unknown_on(day: str, gaps: list[dict]) -> list[str]:
    """The sources whose value on `day` falls in a gap: not counted in that day's net worth."""
    return sorted({g["source"] for g in gaps
                   if (g["start"] is None or g["start"] <= day) and (g["end"] is None or day <= g["end"])})


def monthly_history(repo: SQLiteRepository, current_total: float, today: Optional[date] = None) -> dict:
    """Net worth at the end of each month, plus the change since the end of last month.

    A month's value is its last recorded snapshot, plus the reconstructed month-end value of every
    source that snapshot did not cover yet; a month with no recorded snapshot is the sum of the
    reconstructed sources. The current month is the live total. `missing` names the sources in a
    gap on that day; a month every source misses has no value (`total_chf` is None).
    """
    today = today or datetime.now(timezone.utc).date()
    current_month = today.strftime("%Y-%m")
    recorded: dict[str, dict] = {}
    covered: dict[str, set[str]] = defaultdict(set)
    rebuilt: dict[str, dict[str, dict]] = defaultdict(dict)
    for snap in repo.list_snapshots():  # ordered by date, so the last one of a month wins
        month = snap["snapshot_date"][:7]
        if snap["reconstructed"]:
            rebuilt[month][snap["source"]] = snap
        elif snap["source"] == "total":
            recorded[month] = snap
        else:
            covered[snap["snapshot_date"]].add(snap["source"])
    gaps = _gaps_before_recording(repo.list_history_gaps(), repo.first_recorded_snapshot_dates())

    months = []
    with_data = sorted(m for m in {*recorded, *rebuilt} if m < current_month)
    month = with_data[0] if with_data else current_month
    while month < current_month:
        snap = recorded.get(month)
        seen = covered[snap["snapshot_date"]] if snap else set()
        filled = [s for source, s in rebuilt[month].items() if source not in seen]
        if snap or filled:
            day = max([s["snapshot_date"] for s in filled] + ([snap["snapshot_date"]] if snap else []))
            total = round((snap["total_chf"] if snap else 0.0) + sum(s["total_chf"] for s in filled), 2)
            months.append({"month": month, "date": day, "total_chf": total, "reconstructed": bool(filled),
                           "missing": _unknown_on(day, gaps)})
        elif _unknown_on(month_end(month).isoformat(), gaps):
            day = month_end(month).isoformat()
            months.append({"month": month, "date": day, "total_chf": None, "reconstructed": False,
                           "missing": _unknown_on(day, gaps)})
        month = next_month(month)

    previous = next((m for m in reversed(months) if m["total_chf"] is not None), None)
    months.append({"month": current_month, "date": today.isoformat(), "total_chf": current_total,
                   "reconstructed": False, "missing": _unknown_on(today.isoformat(), gaps)})

    change = None
    if previous is not None:
        change = {
            "amount_chf": round(current_total - previous["total_chf"], 2),
            "since": previous["date"],
            "pct": round((current_total - previous["total_chf"]) / previous["total_chf"] * 100, 2)
            if previous["total_chf"] else None,
        }
    return {"months": months, "change_since_last_month": change, "gaps": gaps}
