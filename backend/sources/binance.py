"""Binance: total value of every wallet (Spot, Funding, Earn, ...) from a read-only API key.

Uses `GET /sapi/v1/asset/wallet/balance` (USER_DATA, signed), which returns one
valuation per wallet in BTC, then the public BTCUSDT price to reach USD, then CHF.
Docs: https://developers.binance.com/docs/wallet/asset/query-user-wallet-balance
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from typing import Optional
from urllib.parse import urlencode

import requests

from backend.database import SQLiteRepository
from backend.fx.service import FrankfurterClient, get_fx_rate

logger = logging.getLogger(__name__)

BINANCE_API_BASE = "https://api.binance.com"
SOURCE = "binance"


def _credentials() -> tuple[str, str]:
    # Read at call time so keys from .env / the systemd EnvironmentFile are always seen.
    return os.environ.get("BINANCE_API_KEY", "").strip(), os.environ.get("BINANCE_API_SECRET", "").strip()


def is_configured() -> bool:
    key, secret = _credentials()
    return bool(key and secret)


def _signed_request(endpoint: str, params: dict | None = None, base_url: str = BINANCE_API_BASE):
    key, secret = _credentials()
    if not key or not secret:
        raise RuntimeError("BINANCE_API_KEY and BINANCE_API_SECRET must be set in environment")

    params = dict(params or {})
    params["timestamp"] = int(time.time() * 1000)
    # Sign exactly the query string that is sent.
    query_string = urlencode(params)
    signature = hmac.new(secret.encode("utf-8"), query_string.encode("utf-8"), hashlib.sha256).hexdigest()
    url = f"{base_url}{endpoint}?{query_string}&signature={signature}"
    resp = requests.get(url, headers={"X-MBX-APIKEY": key}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _public_request(endpoint: str, params: dict | None = None, base_url: str = BINANCE_API_BASE):
    resp = requests.get(f"{base_url}{endpoint}", params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_wallet_balances() -> list[dict]:
    """Non-empty wallets as `{"wallet": name, "btc": value}`."""
    data = _signed_request("/sapi/v1/asset/wallet/balance", {"quoteAsset": "BTC"})
    wallets: list[dict] = []
    for wallet in data:
        value = float(wallet.get("balance") or 0)
        if value > 0:
            wallets.append({"wallet": wallet.get("walletName") or "Wallet", "btc": value})
    return wallets


def get_btc_usdt_price() -> float:
    data = _public_request("/api/v3/ticker/price", {"symbol": "BTCUSDT"})
    return float(data["price"])


def sync_binance(repo: SQLiteRepository, fx_client: Optional[FrankfurterClient] = None) -> int:
    wallets = get_wallet_balances()
    holdings: list[dict] = []
    if wallets:
        usd_to_chf = get_fx_rate(repo, "USD", "CHF", fx_client)["rate"]
        btc_usdt = get_btc_usdt_price()
        for w in wallets:
            holdings.append({
                "label": f"Binance {w['wallet']}",
                "asset_class": "crypto",
                "value_chf": round(w["btc"] * btc_usdt * usd_to_chf, 2),
                "native_amount": w["btc"],
                "native_currency": "BTC",
            })
    else:
        logger.info("No non-zero Binance wallet found")
    repo.replace_source_holdings(SOURCE, "api", holdings)
    return len(holdings)
