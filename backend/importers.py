"""Excel importers for bank transaction workbooks."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Iterable, Iterator, Tuple

import pandas as pd
from dateutil import parser as date_parser

from .models import BankTransactionRecord, NormalisedTransaction


@dataclass(slots=True)
class ClassificationResult:
    """Outcome of applying classification rules to a transaction."""

    inferred_type: str
    inferred_counterparty: str | None
    notes: str | None


class TransactionClassifier:
    """Encapsulates rule-based classification for bank transactions."""

    def classify(self, record: BankTransactionRecord) -> ClassificationResult:
        description = record.description.lower()
        category = (record.category or "").lower()
        sub_category = (record.sub_category or "").lower()

        # Fees contain very explicit keywords in the UBS exports.  We treat them
        # first because the amount sign alone would mark them as withdrawals.
        if "frais" in description or "fee" in description or "frais" in category:
            return ClassificationResult("FEE", record.account_name, "Identified bank fee")

        if self._is_inflow(record):
            counterparty = self._extract_counterparty(record)
            return ClassificationResult("DEPOSIT", counterparty, None)

        if self._is_outflow(record):
            counterparty = self._extract_counterparty(record)
            return ClassificationResult("WITHDRAWAL", counterparty, None)

        return ClassificationResult("UNKNOWN", None, "Unable to infer direction")

    @staticmethod
    def _is_inflow(record: BankTransactionRecord) -> bool:
        return (record.credit or 0.0) > 0 and (record.debit or 0.0) == 0

    @staticmethod
    def _is_outflow(record: BankTransactionRecord) -> bool:
        return (record.debit or 0.0) > 0 and (record.credit or 0.0) == 0

    @staticmethod
    def _extract_counterparty(record: BankTransactionRecord) -> str | None:
        if record.description:
            primary_segment = record.description.split(",", 1)[0]
            return primary_segment.strip() or None
        return None


class BankExcelImporter:
    """Load and normalise bank transactions from UBS exports.

    The importer performs three tasks:

    1. Read each sheet in the workbook into :class:`BankTransactionRecord`
       instances while preserving the raw values.
    2. Apply classification rules to derive a :class:`NormalisedTransaction`.
    3. Return both representations so callers can persist an auditable record
       of the input data and consume the enriched information simultaneously.
    """

    def __init__(self, workbook_path: str | bytes) -> None:
        self.workbook_path = workbook_path
        self.classifier = TransactionClassifier()

    def load(self, sheet_names: Iterable[str]) -> Tuple[list[NormalisedTransaction], dict[str, dict[str, object]]]:
        """Load one or more sheets and return normalised transactions.

        Args:
            sheet_names: Names of workbook sheets to load, e.g.
                ``{"crypto_transac", "stocks_transac"}``.

        Returns:
            A tuple containing the list of normalised transactions and a
            mapping from transaction IDs to raw payloads.
        """

        transactions: list[NormalisedTransaction] = []
        raw_lookup: dict[str, dict[str, object]] = {}

        for sheet in sheet_names:
            dataframe = self._load_sheet(sheet)
            for record in self._iter_records(sheet, dataframe):
                raw_lookup[str(record.id)] = record.raw_payload
                classification = self.classifier.classify(record)
                normalised = self._normalise_record(record, classification)
                transactions.append(normalised)
        return transactions, raw_lookup

    def _load_sheet(self, sheet_name: str) -> pd.DataFrame:
        """Read a sheet from the workbook into a :class:`~pandas.DataFrame`."""

        dataframe = pd.read_excel(self.workbook_path, sheet_name=sheet_name, dtype=str)
        dataframe.columns = [column.strip() for column in dataframe.columns]
        return dataframe

    def _iter_records(self, sheet_name: str, dataframe: pd.DataFrame) -> Iterator[BankTransactionRecord]:
        """Yield :class:`BankTransactionRecord` objects for each DataFrame row."""

        for _, row in dataframe.iterrows():
            payload = row.fillna("").to_dict()
            record = BankTransactionRecord(
                sheet_name=sheet_name,
                account_id=row.get("account_id", ""),
                account_name=row.get("account_name", ""),
                account_holder=row.get("account_holder", ""),
                transaction_date=_parse_date(row.get("transac_date")),
                transaction_time=_clean_string(row.get("transac_hour")),
                accounting_date=_parse_date(row.get("accounting_date")),
                amount_chf=_parse_decimal(row.get("amount_chf")),
                debit=_parse_decimal(row.get("debit")),
                credit=_parse_decimal(row.get("credit")),
                balance=_parse_decimal(row.get("balance")),
                transaction_currency=_clean_string(row.get("transac_currency")) or "CHF",
                fx_rate=_parse_decimal(row.get("rate")),
                description=_collapse_description(row),
                transaction_number=_clean_string(row.get("transac_nbr")),
                category=_clean_string(row.get("category")),
                sub_category=_clean_string(row.get("sub_category")),
                micro_category=_clean_string(row.get("micro_category")),
                raw_payload=payload,
            )
            yield record

    def _normalise_record(
        self,
        record: BankTransactionRecord,
        classification: ClassificationResult,
    ) -> NormalisedTransaction:
        amount_native = None
        if record.transaction_currency and record.transaction_currency.upper() != "CHF" and record.fx_rate:
            try:
                amount_native = record.signed_amount() / record.fx_rate
            except ZeroDivisionError:
                amount_native = None

        return NormalisedTransaction(
            id=record.id,
            sheet_name=record.sheet_name,
            account_id=record.account_id,
            account_name=record.account_name,
            account_holder=record.account_holder,
            transaction_date=record.transaction_date,
            transaction_time=record.transaction_time,
            accounting_date=record.accounting_date,
            transaction_currency=record.transaction_currency or "CHF",
            amount_chf=record.signed_amount(),
            amount_native=amount_native,
            fx_rate=record.fx_rate,
            balance=record.balance,
            description=record.description,
            transaction_number=record.transaction_number,
            category=record.category,
            sub_category=record.sub_category,
            micro_category=record.micro_category,
            inferred_type=classification.inferred_type,
            inferred_counterparty=classification.inferred_counterparty,
            notes=classification.notes,
        )


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _clean_string(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _parse_decimal(value: object) -> float | None:
    if value is None:
        return None
    stringified = str(value).strip()
    if not stringified:
        return None
    normalised = stringified.replace("'", "").replace(" ", "").replace(",", ".")
    try:
        return float(Decimal(normalised))
    except (InvalidOperation, ValueError):
        return None


def _parse_date(value: object) -> date | None:
    if value is None:
        return None
    stringified = str(value).strip()
    if not stringified or stringified in {"NaT", "nan"}:
        return None
    stringified = stringified.replace("[$]", "")
    try:
        parsed = date_parser.parse(stringified, dayfirst=True)
        return parsed.date()
    except (ValueError, OverflowError):
        return None


def _collapse_description(row: pd.Series) -> str:
    parts = [
        _clean_string(row.get("descr_1")),
        _clean_string(row.get("descr_2")),
        _clean_string(row.get("descr_3")),
    ]
    return ", ".join([part for part in parts if part])
