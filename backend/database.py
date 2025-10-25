"""SQLite persistence layer for the finance_dash backend.

The repository provides a small, well-typed API that hides SQL details from the
rest of the code.  It purposely relies on the standard library :mod:`sqlite3`
module to keep dependencies lightweight while still following object-oriented
principles.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from .models import FxRate, NormalisedTransaction, Quote


class SQLiteRepository:
    """Encapsulates all SQLite access for the application."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._connection = sqlite3.connect(database_path, detect_types=sqlite3.PARSE_DECLTYPES)
        self._connection.execute("PRAGMA foreign_keys = ON;")
        self._connection.row_factory = sqlite3.Row

    def close(self) -> None:
        """Close the underlying SQLite connection."""

        self._connection.close()

    # ------------------------------------------------------------------
    # Schema management
    # ------------------------------------------------------------------
    def initialise_schema(self) -> None:
        """Create all tables required by the application if they do not exist."""

        cursor = self._connection.cursor()
        cursor.executescript(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id TEXT PRIMARY KEY,
                sheet_name TEXT NOT NULL,
                account_id TEXT,
                account_name TEXT,
                account_holder TEXT,
                transaction_date TEXT,
                transaction_time TEXT,
                accounting_date TEXT,
                transaction_currency TEXT,
                amount_chf REAL,
                amount_native REAL,
                fx_rate REAL,
                debit REAL,
                credit REAL,
                balance REAL,
                description TEXT,
                transaction_number TEXT,
                category TEXT,
                sub_category TEXT,
                micro_category TEXT,
                inferred_type TEXT,
                inferred_counterparty TEXT,
                notes TEXT,
                raw_payload TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS fx_rates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                base TEXT NOT NULL,
                quote TEXT NOT NULL,
                valuation_date TEXT NOT NULL,
                rate REAL NOT NULL,
                source TEXT NOT NULL,
                UNIQUE(base, quote, valuation_date, source)
            );

            CREATE TABLE IF NOT EXISTS quotes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                valuation_date TEXT NOT NULL,
                price REAL NOT NULL,
                currency TEXT NOT NULL,
                source TEXT NOT NULL,
                UNIQUE(symbol, valuation_date, source)
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        self._connection.commit()

    # ------------------------------------------------------------------
    # Transaction persistence
    # ------------------------------------------------------------------
    def upsert_transactions(self, transactions: Iterable[NormalisedTransaction], raw_lookup: dict[str, dict[str, object]]) -> None:
        """Insert or update a list of transactions inside the database.

        Args:
            transactions: Sequence of normalised transactions to persist.
            raw_lookup: Mapping between transaction IDs and their original raw
                payload.  The information is stored alongside the normalised
                data to provide an audit trail.
        """

        cursor = self._connection.cursor()
        for tx in transactions:
            payload = raw_lookup.get(str(tx.id), {})
            cursor.execute(
                """
                INSERT INTO transactions (
                    id, sheet_name, account_id, account_name, account_holder,
                    transaction_date, transaction_time, accounting_date,
                    transaction_currency, amount_chf, amount_native, fx_rate,
                    debit, credit, balance, description, transaction_number,
                    category, sub_category, micro_category, inferred_type,
                    inferred_counterparty, notes, raw_payload, created_at
                ) VALUES (
                    :id, :sheet_name, :account_id, :account_name, :account_holder,
                    :transaction_date, :transaction_time, :accounting_date,
                    :transaction_currency, :amount_chf, :amount_native, :fx_rate,
                    :debit, :credit, :balance, :description, :transaction_number,
                    :category, :sub_category, :micro_category, :inferred_type,
                    :inferred_counterparty, :notes, :raw_payload, :created_at
                )
                ON CONFLICT(id) DO UPDATE SET
                    sheet_name=excluded.sheet_name,
                    account_id=excluded.account_id,
                    account_name=excluded.account_name,
                    account_holder=excluded.account_holder,
                    transaction_date=excluded.transaction_date,
                    transaction_time=excluded.transaction_time,
                    accounting_date=excluded.accounting_date,
                    transaction_currency=excluded.transaction_currency,
                    amount_chf=excluded.amount_chf,
                    amount_native=excluded.amount_native,
                    fx_rate=excluded.fx_rate,
                    debit=excluded.debit,
                    credit=excluded.credit,
                    balance=excluded.balance,
                    description=excluded.description,
                    transaction_number=excluded.transaction_number,
                    category=excluded.category,
                    sub_category=excluded.sub_category,
                    micro_category=excluded.micro_category,
                    inferred_type=excluded.inferred_type,
                    inferred_counterparty=excluded.inferred_counterparty,
                    notes=excluded.notes,
                    raw_payload=excluded.raw_payload,
                    created_at=excluded.created_at
                ;
                """,
                {
                    "id": str(tx.id),
                    "sheet_name": tx.sheet_name,
                    "account_id": tx.account_id,
                    "account_name": tx.account_name,
                    "account_holder": tx.account_holder,
                    "transaction_date": _date_to_iso(tx.transaction_date),
                    "transaction_time": tx.transaction_time,
                    "accounting_date": _date_to_iso(tx.accounting_date),
                    "transaction_currency": tx.transaction_currency,
                    "amount_chf": tx.amount_chf,
                    "amount_native": tx.amount_native,
                    "fx_rate": tx.fx_rate,
                    "debit": payload.get("debit"),
                    "credit": payload.get("credit"),
                    "balance": tx.balance,
                    "description": tx.description,
                    "transaction_number": tx.transaction_number,
                    "category": tx.category,
                    "sub_category": tx.sub_category,
                    "micro_category": tx.micro_category,
                    "inferred_type": tx.inferred_type,
                    "inferred_counterparty": tx.inferred_counterparty,
                    "notes": tx.notes,
                    "raw_payload": json.dumps(payload, default=str),
                    "created_at": tx.created_at.isoformat(timespec="seconds"),
                },
            )
        self._connection.commit()

    def list_transactions(self, limit: int = 200) -> list[dict[str, object]]:
        """Return the most recent transactions stored in the database."""

        cursor = self._connection.cursor()
        rows = cursor.execute(
            """
            SELECT * FROM transactions
            ORDER BY transaction_date DESC, accounting_date DESC, created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def cash_summary(self, display_currency: str = "CHF") -> dict[str, float]:
        """Aggregate cash flows and balances for high-level dashboards.

        The function converts the CHF totals to :paramref:`display_currency`
        when possible.  Conversion uses the latest FX rate stored in the
        database.  If the rate is missing the method falls back to returning the
        CHF total only while annotating the payload with an ``fx_missing`` flag.
        """

        cursor = self._connection.cursor()
        row = cursor.execute(
            """
            SELECT
                COALESCE(SUM(amount_chf), 0.0) AS total_chf,
                COUNT(*) AS transaction_count
            FROM transactions
            """
        ).fetchone()

        total_chf = row["total_chf"] if row else 0.0
        payload = {
            "total_chf": total_chf,
            "transaction_count": row["transaction_count"] if row else 0,
        }

        if display_currency.upper() == "CHF":
            payload["display_currency"] = "CHF"
            payload["display_total"] = total_chf
            payload["fx_missing"] = False
            return payload

        rate = self.get_latest_fx_rate("CHF", display_currency.upper())
        if rate is None:
            payload["display_currency"] = display_currency.upper()
            payload["display_total"] = total_chf
            payload["fx_missing"] = True
            return payload

        payload["display_currency"] = display_currency.upper()
        payload["display_total"] = total_chf * rate
        payload["fx_missing"] = False
        payload["fx_rate"] = rate
        return payload

    # ------------------------------------------------------------------
    # FX rates and quotes
    # ------------------------------------------------------------------
    def upsert_fx_rates(self, rates: Iterable[FxRate]) -> None:
        cursor = self._connection.cursor()
        for rate in rates:
            cursor.execute(
                """
                INSERT OR REPLACE INTO fx_rates (base, quote, valuation_date, rate, source)
                VALUES (:base, :quote, :valuation_date, :rate, :source)
                """,
                {
                    "base": rate.base.upper(),
                    "quote": rate.quote.upper(),
                    "valuation_date": rate.valuation_date.isoformat(),
                    "rate": rate.rate,
                    "source": rate.source,
                },
            )
        self._connection.commit()

    def get_latest_fx_rate(self, base: str, quote: str) -> Optional[float]:
        cursor = self._connection.cursor()
        row = cursor.execute(
            """
            SELECT rate
            FROM fx_rates
            WHERE base = ? AND quote = ?
            ORDER BY date(valuation_date) DESC
            LIMIT 1
            """,
            (base.upper(), quote.upper()),
        ).fetchone()
        if row is None:
            return None
        return float(row["rate"])

    def log_quotes(self, quotes: Iterable[Quote]) -> None:
        cursor = self._connection.cursor()
        for quote in quotes:
            cursor.execute(
                """
                INSERT OR REPLACE INTO quotes (symbol, valuation_date, price, currency, source)
                VALUES (:symbol, :valuation_date, :price, :currency, :source)
                """,
                {
                    "symbol": quote.symbol.upper(),
                    "valuation_date": quote.valuation_date.isoformat(),
                    "price": quote.price,
                    "currency": quote.currency.upper(),
                    "source": quote.source,
                },
            )
        self._connection.commit()

    # ------------------------------------------------------------------
    # Settings helpers
    # ------------------------------------------------------------------
    def set_setting(self, key: str, value: str) -> None:
        self._connection.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )
        self._connection.commit()

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self._connection.execute(
            "SELECT value FROM settings WHERE key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return default
        return str(row["value"])


def _date_to_iso(value: Optional[datetime | str]) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    return str(value)
