"""Domain models used by the finance_dash backend.

The classes defined here are intentionally lightweight data containers that do
not know anything about persistence or transport concerns.  Keeping the domain
model pure makes it easier to test the business logic and enables future reuse
by different adapters (for example a desktop variant or a cloud API).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from uuid import UUID, uuid4
from typing import Optional


@dataclass(slots=True)
class BankTransactionRecord:
    """Representation of a single row inside the Excel workbook.

    Attributes mirror the source data closely so we can keep an auditable copy
    of the original values even after normalisation.  The :attr:`id` field is a
    locally generated UUID that guarantees global uniqueness across imports and
    enables safe upserts into SQLite.
    """

    id: UUID = field(default_factory=uuid4)
    sheet_name: str = ""
    account_id: str = ""
    account_name: str = ""
    account_holder: str = ""
    transaction_date: Optional[date] = None
    transaction_time: Optional[str] = None
    accounting_date: Optional[date] = None
    amount_chf: Optional[float] = None
    debit: Optional[float] = None
    credit: Optional[float] = None
    balance: Optional[float] = None
    transaction_currency: Optional[str] = None
    fx_rate: Optional[float] = None
    description: str = ""
    transaction_number: Optional[str] = None
    category: Optional[str] = None
    sub_category: Optional[str] = None
    micro_category: Optional[str] = None
    raw_payload: dict[str, object] = field(default_factory=dict)

    def signed_amount(self) -> float:
        """Return the cash impact of the row in CHF.

        The function prefers the explicit :attr:`amount_chf`.  If the column is
        missing, it derives the value by subtracting :attr:`debit` from
        :attr:`credit`.  ``None`` values are treated as zero to simplify the
        computation.
        """

        if self.amount_chf is not None:
            return self.amount_chf
        debit = self.debit or 0.0
        credit = self.credit or 0.0
        return credit - debit


@dataclass(slots=True)
class NormalisedTransaction:
    """Higher-level view of a transaction after applying classification rules."""

    id: UUID
    sheet_name: str
    account_id: str
    account_name: str
    account_holder: str
    transaction_date: Optional[date]
    transaction_time: Optional[str]
    accounting_date: Optional[date]
    transaction_currency: str
    amount_chf: float
    amount_native: Optional[float]
    fx_rate: Optional[float]
    balance: Optional[float]
    description: str
    transaction_number: Optional[str]
    category: Optional[str]
    sub_category: Optional[str]
    micro_category: Optional[str]
    inferred_type: str
    inferred_counterparty: Optional[str]
    notes: Optional[str]
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass(slots=True)
class FxRate:
    """FX rate as persisted in the local database."""

    base: str
    quote: str
    valuation_date: date
    rate: float
    source: str


@dataclass(slots=True)
class Quote:
    """Market quote for an asset."""

    symbol: str
    valuation_date: date
    price: float
    currency: str
    source: str


__all__ = [
    "BankTransactionRecord",
    "NormalisedTransaction",
    "FxRate",
    "Quote",
]
