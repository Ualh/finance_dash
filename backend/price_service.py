"""Market data helpers for the finance_dash backend."""
from __future__ import annotations

from datetime import date
from typing import Optional

import requests

from .config import AppConfig
from .models import FxRate, Quote


class PriceService:
    """Fetch live FX rates and quotes from external providers."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    # ------------------------------------------------------------------
    # FX utilities (Alpha Vantage)
    # ------------------------------------------------------------------
    def fetch_latest_fx_rate(self, base: str, quote: str) -> Optional[FxRate]:
        """Return the latest FX rate between two currencies using Alpha Vantage.

        The function gracefully degrades to ``None`` when the API key is not
        configured or when the external service does not return the expected
        payload structure.
        """

        if not self._config.alpha_vantage_key:
            return None

        params = {
            "function": "CURRENCY_EXCHANGE_RATE",
            "from_currency": base.upper(),
            "to_currency": quote.upper(),
            "apikey": self._config.alpha_vantage_key,
        }
        response = requests.get(self._config.alpha_vantage_endpoint, params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
        key = "Realtime Currency Exchange Rate"
        if key not in payload:
            return None
        body = payload[key]
        rate_str = body.get("5. Exchange Rate")
        if rate_str is None:
            return None
        try:
            rate = float(rate_str)
        except ValueError:
            return None
        return FxRate(
            base=base.upper(),
            quote=quote.upper(),
            valuation_date=date.today(),
            rate=rate,
            source="alpha_vantage",
        )

    # ------------------------------------------------------------------
    # Equity quotes (Alpha Vantage)
    # ------------------------------------------------------------------
    def fetch_equity_quote(self, symbol: str) -> Optional[Quote]:
        if not self._config.alpha_vantage_key:
            return None

        params = {
            "function": "GLOBAL_QUOTE",
            "symbol": symbol,
            "apikey": self._config.alpha_vantage_key,
        }
        response = requests.get(self._config.alpha_vantage_endpoint, params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
        quote_section = payload.get("Global Quote")
        if not quote_section:
            return None

        price_str = quote_section.get("05. price")
        currency = quote_section.get("08. currency", "USD")
        if price_str is None:
            return None
        try:
            price = float(price_str)
        except ValueError:
            return None
        return Quote(
            symbol=symbol.upper(),
            valuation_date=date.today(),
            price=price,
            currency=currency.upper(),
            source="alpha_vantage",
        )

    # ------------------------------------------------------------------
    # Crypto quotes (Coinranking)
    # ------------------------------------------------------------------
    def fetch_crypto_quote(self, symbol: str) -> Optional[Quote]:
        """Fetch the current price for a crypto asset using Coinranking.

        Coinranking requires a RapidAPI key and a UUID per asset.  For the first
        iteration we assume ``symbol`` already refers to a UUID provided by the
        user.  Future improvements can add symbol-to-UUID resolution.
        """

        if not self._config.coinranking_key:
            return None

        url = f"https://{self._config.coinranking_host}/coin/{symbol}"
        response = requests.get(
            url,
            headers={
                "X-RapidAPI-Key": self._config.coinranking_key,
                "X-RapidAPI-Host": self._config.coinranking_host,
            },
            params={"timePeriod": "24h"},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        coin = payload.get("data", {}).get("coin")
        if not coin:
            return None
        price_str = coin.get("price")
        if price_str is None:
            return None
        try:
            price = float(price_str)
        except ValueError:
            return None
        return Quote(
            symbol=coin.get("symbol", symbol).upper(),
            valuation_date=date.today(),
            price=price,
            currency=coin.get("symbol", "USD").upper(),
            source="coinranking",
        )
