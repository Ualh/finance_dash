"""How old each source's figure is, and what to do about the stale ones.

Feeds the per-source dates on the dashboard (orange when stale) and `GET /freshness`,
which the monthly reminder reads to know what to ask for.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from backend.database import SQLiteRepository
from backend.sync.engine import AUTOMATIC_SOURCES

STALE_AFTER_DAYS = 35

LABELS = {"neon": "Neon", "finpension": "Finpension", "binance": "Binance", "wise": "Wise", "ibkr": "IBKR"}
MANUAL_ACTIONS = {
    "neon": "Upload last month's Neon CSV on the Update page",
    "finpension": "Type the current Finpension value on the Update page",
}
# Always listed, even before their first entry: the monthly ritual needs both.
EXPECTED_MANUAL = ("neon", "finpension")


def _as_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    return datetime.fromisoformat(value[:10]).date()


def _entry(source: str, label: str, kind: str, as_of: Optional[str], today: date, action: str) -> dict:
    as_of_date = _as_date(as_of)
    age = (today - as_of_date).days if as_of_date else None
    return {
        "source": source,
        "label": label,
        "kind": kind,
        "as_of": as_of_date.isoformat() if as_of_date else None,
        "age_days": age,
        "stale": age is None or age > STALE_AFTER_DAYS,
        "action": action,
    }


def source_freshness(repo: SQLiteRepository, today: Optional[date] = None) -> list[dict]:
    today = today or datetime.now(timezone.utc).date()
    holdings = repo.list_holdings()
    by_source: dict[str, list[dict]] = {}
    for h in holdings:
        by_source.setdefault(h["source"], []).append(h)

    def last_updated(source: str) -> Optional[str]:
        rows = by_source.get(source, [])
        return max((h["last_updated"] for h in rows), default=None)

    entries = []
    # Neon is only as fresh as its latest transaction, not the day a CSV was uploaded.
    neon_as_of = repo.get_latest_neon_transaction_date() or last_updated("neon")
    entries.append(_entry("neon", "Neon", "manual", neon_as_of, today, MANUAL_ACTIONS["neon"]))
    entries.append(_entry("finpension", "Finpension", "manual", last_updated("finpension"), today,
                          MANUAL_ACTIONS["finpension"]))

    automatic = {s.name: s for s in AUTOMATIC_SOURCES}
    for name, src in automatic.items():
        if not src.is_configured() and name not in by_source:
            continue
        as_of = repo.get_last_successful_sync(name) or last_updated(name)
        action = (f"Check the {LABELS[name]} sync (keys in .env, sync log)" if src.is_configured()
                  else f"Add the {LABELS[name]} API keys to .env")
        entries.append(_entry(name, LABELS[name], "automatic", as_of, today, action))

    for source, rows in sorted(by_source.items()):
        if source in EXPECTED_MANUAL or source in automatic:
            continue
        label = rows[0]["label"] or source
        entries.append(_entry(source, label, "manual", last_updated(source), today,
                              f"Update {label} on the Update page"))
    return entries
