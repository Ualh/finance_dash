"""High-level application services orchestrating the finance_dash backend."""
from __future__ import annotations

from typing import Iterable, Optional

from .config import AppConfig
from .database import SQLiteRepository
from .importers import BankExcelImporter
from .models import FxRate, Quote
from .price_service import PriceService


class PortfolioService:
    """Coordinates imports, persistence and summarisation logic."""

    def __init__(self, config: AppConfig, repository: SQLiteRepository, price_service: PriceService) -> None:
        self._config = config
        self._repository = repository
        self._price_service = price_service

    # ------------------------------------------------------------------
    # Import workflows
    # ------------------------------------------------------------------
    def import_workbook(self, sheet_names: Iterable[str]) -> int:
        """Import the configured workbook and persist the normalised data.

        Returns the number of transactions persisted.  The method is idempotent:
        running it multiple times keeps the latest normalised view for every
        transaction thanks to ``INSERT OR REPLACE`` semantics in the repository.
        """

        importer = BankExcelImporter(self._config.data_file)
        transactions, raw_lookup = importer.load(sheet_names)
        self._repository.upsert_transactions(transactions, raw_lookup)
        return len(transactions)

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------
    def recent_transactions(self, limit: int = 200) -> list[dict[str, object]]:
        return self._repository.list_transactions(limit)

    def cash_summary(self, display_currency: str = "CHF") -> dict[str, object]:
        return self._repository.cash_summary(display_currency)

    # ------------------------------------------------------------------
    # Market data utilities
    # ------------------------------------------------------------------
    def refresh_fx_rate(self, base: str, quote: str) -> Optional[FxRate]:
        rate = self._price_service.fetch_latest_fx_rate(base, quote)
        if rate:
            self._repository.upsert_fx_rates([rate])
        return rate

    def refresh_equity_quote(self, symbol: str) -> Optional[Quote]:
        quote = self._price_service.fetch_equity_quote(symbol)
        if quote:
            self._repository.log_quotes([quote])
        return quote

    def refresh_crypto_quote(self, symbol: str) -> Optional[Quote]:
        quote = self._price_service.fetch_crypto_quote(symbol)
        if quote:
            self._repository.log_quotes([quote])
        return quote
