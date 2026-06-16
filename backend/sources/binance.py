from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from typing import Optional

import requests

from backend.database import SQLiteRepository
from backend.fx.service import FrankfurterClient, get_fx_rate

logger = logging.getLogger(__name__)

BINANCE_API_BASE = "https://api.binance.com"

BINANCE_API_KEY = os.environ.get("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.environ.get("BINANCE_API_SECRET", "")

NON_ZERO_BALANCE_CACHE: dict[str, tuple[float, int]] = {}


def _signed_request(endpoint: str, params: dict | None = None, base_url: str = BINANCE_API_BASE) -> dict:
    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        raise RuntimeError("BINANCE_API_KEY and BINANCE_API_SECRET must be set in environment")

    params = dict(params or {})
    params["timestamp"] = int(time.time() * 1000)
    query_string = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    signature = hmac.new(
        BINANCE_API_SECRET.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    params["signature"] = signature

    url = f"{base_url}{endpoint}"
    resp = requests.get(url, params=params, headers={"X-MBX-APIKEY": BINANCE_API_KEY}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_account_balances() -> list[dict]:
    data = _signed_request("/api/v3/account")
    balances: list[dict] = []
    for bal in data.get("balances", []):
        free = float(bal.get("free", 0))
        locked = float(bal.get("locked", 0))
        total = free + locked
        if total > 0:
            balances.append({"asset": bal["asset"], "free": free, "locked": locked, "total": total})
    return balances


def get_usdt_price(asset: str) -> Optional[float]:
    if asset == "USDT":
        return 1.0
    try:
        data = _signed_request("/api/v3/ticker/price", {"symbol": f"{asset}USDT"})
        return float(data["price"])
    except Exception:
        try:
            data = _signed_request("/api/v3/ticker/price", {"symbol": f"{asset}USDC"})
            usdc_price = float(data["price"])
            usdc_usdt = get_usdt_price("USDC")
            if usdc_usdt:
                return usdc_price * usdc_usdt
        except Exception:
            pass
        logger.warning("Could not fetch USDT price for %s", asset)
        return None


def sync_binance(repo: SQLiteRepository, fx_client: Optional[FrankfurterClient] = None) -> int:
    balances = get_account_balances()
    if not balances:
        logger.info("No non-zero Binance balances found")
        return 0

    fx_rate_info = get_fx_rate(repo, "USD", "CHF", fx_client)
    usd_to_chf = fx_rate_info["rate"]

    synced_count = 0
    for bal in balances:
        asset = bal["asset"]
        total = bal["total"]

        if asset == "USDT":
            value_usd = total
        else:
            price_usdt = get_usdt_price(asset)
            if price_usdt is None:
                logger.warning("Skipping %s: could not determine USDT price", asset)
                continue
            value_usd = total * price_usdt

        value_chf = round(value_usd * usd_to_chf, 2)

        label = f"Binance {asset}"
        repo.upsert_holding(
            source="binance",
            source_type="api",
            asset_class="crypto",
            value_chf=value_chf,
            label=label,
        )
        synced_count += 1

    return synced_count
