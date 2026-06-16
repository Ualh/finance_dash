from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Optional

import requests

from backend.database import SQLiteRepository

logger = logging.getLogger(__name__)

FRANKFURTER_BASE = "https://api.frankfurter.dev"

SUPPORTED_QUOTES = {"CHF", "USD"}


class FrankfurterClient:
    def __init__(self, base_url: str = FRANKFURTER_BASE, timeout: int = 10) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def fetch_rate(self, base: str, quote: str, valuation_date: str) -> Optional[float]:
        url = f"{self._base_url}/{valuation_date}"
        params = {"base": base, "symbols": quote, "to": quote}
        try:
            resp = requests.get(url, params=params, timeout=self._timeout)
            resp.raise_for_status()
            data = resp.json()
            return float(data["rates"][quote])
        except Exception:
            logger.exception("Frankfurter fetch failed for %s->%s on %s", base, quote, valuation_date)
            return None


def get_fx_rate(repo: SQLiteRepository, base: str, quote: str, client: Optional[FrankfurterClient] = None) -> dict:
    today = date.today().isoformat()
    cached = repo.get_cached_fx_rate(base, quote, today)
    if cached is not None:
        return {"rate": cached, "stale": False, "source": "cache"}

    fc = client or FrankfurterClient()
    rate = fc.fetch_rate(base, quote, today)

    if rate is not None:
        repo.put_fx_rate(base, quote, today, rate)
        return {"rate": rate, "stale": False, "source": "frankfurter"}

    latest = repo.get_latest_fx_rate(base, quote)
    if latest is not None:
        return {"rate": latest, "stale": True, "source": "stale"}

    return {"rate": 1.0, "stale": True, "source": "fallback"}


def convert(repo: SQLiteRepository, amount_chf: float, target: str, client: Optional[FrankfurterClient] = None) -> dict:
    if target == "CHF":
        return {"amount": amount_chf, "rate": 1.0, "stale": False, "currency": target}

    result = get_fx_rate(repo, "CHF", target, client)
    return {"amount": round(amount_chf * result["rate"], 2), "rate": result["rate"], "stale": result["stale"], "currency": target}
