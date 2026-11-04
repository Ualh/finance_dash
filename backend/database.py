from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


LIQUIDITY_BUCKET: dict[str, str] = {
    "cash": "available",
    "crypto": "invested",
    "stock": "invested",
    "etf": "invested",
    "pension": "locked",
    "real_estate": "locked",
    "loan": "locked",
    "other": "locked",
}


class SQLiteRepository:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._connection = sqlite3.connect(database_path, detect_types=sqlite3.PARSE_DECLTYPES, check_same_thread=False)
        self._connection.execute("PRAGMA foreign_keys = ON;")
        self._connection.row_factory = sqlite3.Row

    def close(self) -> None:
        self._connection.close()

    def initialise_schema(self) -> None:
        cursor = self._connection.cursor()
        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS holdings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                source_type TEXT NOT NULL DEFAULT 'manual',
                asset_class TEXT NOT NULL,
                value_chf REAL NOT NULL,
                label TEXT,
                native_amount REAL,
                native_currency TEXT,
                last_updated TEXT NOT NULL,
                UNIQUE(source, source_type, label)
            );

            CREATE TABLE IF NOT EXISTS nw_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_date TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'total',
                total_chf REAL NOT NULL,
                available_chf REAL NOT NULL,
                invested_chf REAL NOT NULL,
                locked_chf REAL NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(snapshot_date, source)
            );

            CREATE TABLE IF NOT EXISTS fx_rates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                base TEXT NOT NULL,
                quote TEXT NOT NULL,
                valuation_date TEXT NOT NULL,
                rate REAL NOT NULL,
                source TEXT NOT NULL DEFAULT 'manual',
                UNIQUE(base, quote, valuation_date, source)
            );

            CREATE TABLE IF NOT EXISTS sync_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                status TEXT NOT NULL,
                message TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS neon_uploads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_hash TEXT NOT NULL UNIQUE,
                filename TEXT NOT NULL,
                uploaded_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS neon_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                amount REAL NOT NULL,
                upload_id INTEGER NOT NULL REFERENCES neon_uploads(id)
            );

            CREATE INDEX IF NOT EXISTS idx_neon_transactions_date ON neon_transactions(date);

            CREATE TABLE IF NOT EXISTS wise_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reference_number TEXT NOT NULL,
                currency TEXT NOT NULL,
                date TEXT NOT NULL,
                amount REAL NOT NULL,
                amount_chf REAL NOT NULL,
                detail_type TEXT,
                description TEXT,
                UNIQUE(reference_number, currency)
            );

            CREATE INDEX IF NOT EXISTS idx_wise_transactions_date ON wise_transactions(date);

            CREATE TABLE IF NOT EXISTS cash_withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                amount_chf REAL NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL
            );
        """)
        self._migrate_holdings_native_columns(cursor)
        self._migrate_neon_transaction_columns(cursor)
        self._connection.commit()

    def _migrate_holdings_native_columns(self, cursor: sqlite3.Cursor) -> None:
        """Add native_amount/native_currency to pre-existing holdings tables (SQLite has no ADD COLUMN IF NOT EXISTS)."""
        existing = {row["name"] for row in cursor.execute("PRAGMA table_info(holdings)").fetchall()}
        if "native_amount" not in existing:
            cursor.execute("ALTER TABLE holdings ADD COLUMN native_amount REAL")
        if "native_currency" not in existing:
            cursor.execute("ALTER TABLE holdings ADD COLUMN native_currency TEXT")

    def _migrate_neon_transaction_columns(self, cursor: sqlite3.Cursor) -> None:
        """Keep the Spaces flag so pocket moves inside Neon are not counted as spending."""
        existing = {row["name"] for row in cursor.execute("PRAGMA table_info(neon_transactions)").fetchall()}
        if "is_space" not in existing:
            cursor.execute("ALTER TABLE neon_transactions ADD COLUMN is_space INTEGER NOT NULL DEFAULT 0")

    def upsert_holding(self, source: str, source_type: str, asset_class: str, value_chf: float,
                       label: Optional[str] = None, native_amount: Optional[float] = None,
                       native_currency: Optional[str] = None) -> dict:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        label = label or ""
        cursor = self._connection.cursor()
        cursor.execute("""
            INSERT INTO holdings (source, source_type, asset_class, value_chf, label, native_amount, native_currency, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, source_type, label) DO UPDATE SET
                asset_class = excluded.asset_class,
                value_chf = excluded.value_chf,
                native_amount = excluded.native_amount,
                native_currency = excluded.native_currency,
                last_updated = excluded.last_updated
        """, (source, source_type, asset_class, value_chf, label, native_amount, native_currency, now))
        self._connection.commit()
        row = cursor.execute(
            "SELECT * FROM holdings WHERE source = ? AND source_type = ? AND label = ?",
            (source, source_type, label),
        ).fetchone()
        return dict(row)

    def list_holdings(self) -> list[dict]:
        cursor = self._connection.cursor()
        rows = cursor.execute("SELECT * FROM holdings ORDER BY last_updated DESC").fetchall()
        return [dict(r) for r in rows]

    def get_holding(self, holding_id: int) -> Optional[dict]:
        row = self._connection.execute(
            "SELECT * FROM holdings WHERE id = ?", (holding_id,)
        ).fetchone()
        return dict(row) if row else None

    def update_holding_value(self, holding_id: int, value_chf: float) -> Optional[dict]:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cursor = self._connection.cursor()
        cursor.execute(
            "UPDATE holdings SET value_chf = ?, last_updated = ? WHERE id = ?",
            (value_chf, now, holding_id),
        )
        if cursor.rowcount == 0:
            return None
        self._connection.commit()
        row = cursor.execute("SELECT * FROM holdings WHERE id = ?", (holding_id,)).fetchone()
        return dict(row)

    def replace_source_holdings(self, source: str, source_type: str, holdings: list[dict]) -> list[dict]:
        """Make `holdings` the complete set of lines for an automatic source.

        Lines the source no longer reports (an emptied wallet, a legacy per-asset label)
        are removed so the total never keeps a stale balance.
        """
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._connection:
            self._connection.execute(
                "DELETE FROM holdings WHERE source = ? AND source_type = ?", (source, source_type)
            )
            self._connection.executemany(
                """INSERT INTO holdings (source, source_type, asset_class, value_chf, label, native_amount, native_currency, last_updated)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (source, source_type, h["asset_class"], h["value_chf"], h.get("label") or "",
                     h.get("native_amount"), h.get("native_currency"), now)
                    for h in holdings
                ],
            )
        rows = self._connection.execute(
            "SELECT * FROM holdings WHERE source = ? AND source_type = ? ORDER BY label", (source, source_type)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_aggregate_holdings(self) -> dict:
        cursor = self._connection.cursor()
        rows = cursor.execute("SELECT asset_class, value_chf FROM holdings").fetchall()
        total = 0.0
        buckets: dict[str, float] = {"available": 0.0, "invested": 0.0, "locked": 0.0}
        sources: dict[str, dict] = {}
        for r in rows:
            ac = r["asset_class"]
            val = r["value_chf"] or 0.0
            total += val
            bucket = LIQUIDITY_BUCKET.get(ac, "locked")
            buckets[bucket] = buckets.get(bucket, 0.0) + val
        rows2 = cursor.execute(
            "SELECT source, SUM(value_chf) as total, MAX(last_updated) as last_updated FROM holdings GROUP BY source"
        ).fetchall()
        for r in rows2:
            sources[r["source"]] = {
                "total_chf": r["total"] or 0.0,
                "last_updated": r["last_updated"],
            }
        return {"total_chf": total, "buckets": buckets, "sources": sources}

    def upsert_snapshot(self, snapshot_date: str, source: str, total_chf: float,
                        available_chf: float, invested_chf: float, locked_chf: float) -> dict:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cursor = self._connection.cursor()
        cursor.execute("""
            INSERT INTO nw_snapshots (snapshot_date, source, total_chf, available_chf, invested_chf, locked_chf, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(snapshot_date, source) DO UPDATE SET
                total_chf = excluded.total_chf,
                available_chf = excluded.available_chf,
                invested_chf = excluded.invested_chf,
                locked_chf = excluded.locked_chf,
                created_at = excluded.created_at
        """, (snapshot_date, source, total_chf, available_chf, invested_chf, locked_chf, now))
        self._connection.commit()
        row = cursor.execute(
            "SELECT * FROM nw_snapshots WHERE snapshot_date = ? AND source = ?",
            (snapshot_date, source),
        ).fetchone()
        return dict(row)

    def get_latest_snapshot_before(self, before_date: str) -> Optional[dict]:
        cursor = self._connection.cursor()
        row = cursor.execute(
            "SELECT * FROM nw_snapshots WHERE source = 'total' AND snapshot_date < ? ORDER BY snapshot_date DESC LIMIT 1",
            (before_date,),
        ).fetchone()
        return dict(row) if row else None

    def get_source_aggregate(self, source: str) -> dict:
        cursor = self._connection.cursor()
        rows = cursor.execute(
            "SELECT asset_class, value_chf FROM holdings WHERE source = ?", (source,)
        ).fetchall()
        total = 0.0
        buckets: dict[str, float] = {"available": 0.0, "invested": 0.0, "locked": 0.0}
        for r in rows:
            val = r["value_chf"] or 0.0
            total += val
            bucket = LIQUIDITY_BUCKET.get(r["asset_class"], "locked")
            buckets[bucket] = buckets.get(bucket, 0.0) + val
        return {"total_chf": total, "buckets": buckets}

    def list_sources(self) -> list[str]:
        rows = self._connection.execute(
            "SELECT DISTINCT source FROM holdings ORDER BY source"
        ).fetchall()
        return [r["source"] for r in rows]

    def get_last_sync_log(self, source: str) -> Optional[dict]:
        row = self._connection.execute(
            "SELECT * FROM sync_log WHERE source = ? ORDER BY started_at DESC LIMIT 1",
            (source,),
        ).fetchone()
        return dict(row) if row else None

    def log_sync_start(self, source: str, started_at: str) -> None:
        self._connection.execute(
            "INSERT INTO sync_log (source, status, started_at) VALUES (?, 'running', ?)",
            (source, started_at),
        )
        self._connection.commit()

    def log_sync_end(self, source: str, status: str, message: str, started_at: str) -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._connection.execute(
            "UPDATE sync_log SET status = ?, message = ?, finished_at = ? WHERE source = ? AND started_at = ?",
            (status, message, now, source, started_at),
        )
        self._connection.commit()

    def get_latest_snapshot(self) -> Optional[dict]:
        cursor = self._connection.cursor()
        row = cursor.execute(
            "SELECT * FROM nw_snapshots ORDER BY snapshot_date DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self._connection.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        return str(row["value"])

    def set_setting(self, key: str, value: str) -> None:
        self._connection.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        self._connection.commit()

    def compute_file_hash(self, content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def is_upload_imported(self, file_hash: str) -> bool:
        row = self._connection.execute(
            "SELECT id FROM neon_uploads WHERE file_hash = ?", (file_hash,)
        ).fetchone()
        return row is not None

    def import_neon_transactions(self, content: bytes, filename: str, rows: list[dict]) -> int:
        file_hash = self.compute_file_hash(content)
        if self.is_upload_imported(file_hash):
            return 0

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cursor = self._connection.cursor()
        cursor.execute(
            "INSERT INTO neon_uploads (file_hash, filename, uploaded_at) VALUES (?, ?, ?)",
            (file_hash, filename, now),
        )
        upload_id = cursor.lastrowid

        cursor.executemany(
            "INSERT INTO neon_transactions (date, amount, upload_id, is_space) VALUES (?, ?, ?, ?)",
            [(r["date"], r["amount"], upload_id, 1 if r.get("is_space") else 0) for r in rows],
        )
        self._connection.commit()
        return len(rows)

    def recompute_neon_balance(self, anchor_date: Optional[str], anchor_amount: Optional[float]) -> float:
        if anchor_date is None or anchor_amount is None:
            row = self._connection.execute(
                "SELECT COALESCE(SUM(amount), 0.0) as total FROM neon_transactions"
            ).fetchone()
            return row["total"]

        row = self._connection.execute(
            "SELECT COALESCE(SUM(amount), 0.0) as total FROM neon_transactions WHERE date >= ?",
            (anchor_date,),
        ).fetchone()
        return anchor_amount + row["total"]

    def get_neon_transaction_count(self) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) as cnt FROM neon_transactions"
        ).fetchone()
        return row["cnt"]

    def get_latest_neon_transaction_date(self) -> Optional[str]:
        row = self._connection.execute("SELECT MAX(date) AS latest FROM neon_transactions").fetchone()
        return row["latest"]

    def list_total_snapshots(self) -> list[dict]:
        rows = self._connection.execute(
            "SELECT snapshot_date, total_chf FROM nw_snapshots WHERE source = 'total' ORDER BY snapshot_date"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_last_successful_sync(self, source: str) -> Optional[str]:
        row = self._connection.execute(
            "SELECT MAX(COALESCE(finished_at, started_at)) AS at FROM sync_log WHERE source = ? AND status = 'ok'",
            (source,),
        ).fetchone()
        return row["at"]

    def get_last_sync_run(self) -> Optional[str]:
        """When the most recent sync of any automatic source ended (or started, if still running)."""
        row = self._connection.execute(
            "SELECT MAX(COALESCE(finished_at, started_at)) AS at FROM sync_log"
        ).fetchone()
        return row["at"]

    def get_last_neon_upload(self) -> Optional[str]:
        row = self._connection.execute("SELECT MAX(uploaded_at) AS at FROM neon_uploads").fetchone()
        return row["at"]

    def import_wise_transactions(self, rows: list[dict]) -> int:
        """Insert Wise statement lines, skipping any already stored (same reference and currency)."""
        cursor = self._connection.cursor()
        cursor.executemany(
            """INSERT OR IGNORE INTO wise_transactions
               (reference_number, currency, date, amount, amount_chf, detail_type, description)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                (r["reference_number"], r["currency"], r["date"], r["amount"], r["amount_chf"],
                 r.get("detail_type"), r.get("description"))
                for r in rows
            ],
        )
        self._connection.commit()
        return cursor.rowcount

    def list_bank_debits(self, start_date: str, end_date: str, wise_internal_types: frozenset[str]) -> list[dict]:
        """Money that left Neon or Wise for the outside world, between two dates inclusive."""
        neon = self._connection.execute(
            "SELECT 'neon' AS source, date, amount AS amount_chf FROM neon_transactions "
            "WHERE amount < 0 AND is_space = 0 AND date BETWEEN ? AND ?",
            (start_date, end_date),
        ).fetchall()
        placeholders = ",".join("?" for _ in wise_internal_types) or "''"
        wise = self._connection.execute(
            "SELECT 'wise' AS source, date, amount_chf FROM wise_transactions "
            f"WHERE amount < 0 AND COALESCE(detail_type, '') NOT IN ({placeholders}) AND date BETWEEN ? AND ?",
            (*sorted(wise_internal_types), start_date, end_date),
        ).fetchall()
        return [dict(r) for r in [*neon, *wise]]

    def add_cash_withdrawal(self, date: str, amount_chf: float, note: Optional[str]) -> dict:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cursor = self._connection.cursor()
        cursor.execute(
            "INSERT INTO cash_withdrawals (date, amount_chf, note, created_at) VALUES (?, ?, ?, ?)",
            (date, amount_chf, note, now),
        )
        self._connection.commit()
        row = cursor.execute("SELECT * FROM cash_withdrawals WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return dict(row)

    def list_cash_withdrawals(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> list[dict]:
        rows = self._connection.execute(
            "SELECT * FROM cash_withdrawals WHERE date BETWEEN ? AND ? ORDER BY date DESC, id DESC",
            (start_date or "0000-00-00", end_date or "9999-12-31"),
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_cash_withdrawal(self, withdrawal_id: int) -> bool:
        cursor = self._connection.execute("DELETE FROM cash_withdrawals WHERE id = ?", (withdrawal_id,))
        self._connection.commit()
        return cursor.rowcount > 0

    def get_cached_fx_rate(self, base: str, quote: str, valuation_date: str) -> Optional[float]:
        row = self._connection.execute(
            "SELECT rate FROM fx_rates WHERE base = ? AND quote = ? AND valuation_date = ? ORDER BY id DESC LIMIT 1",
            (base, quote, valuation_date),
        ).fetchone()
        return row["rate"] if row else None

    def get_latest_fx_rate(self, base: str, quote: str) -> Optional[float]:
        row = self._connection.execute(
            "SELECT rate FROM fx_rates WHERE base = ? AND quote = ? ORDER BY valuation_date DESC LIMIT 1",
            (base, quote),
        ).fetchone()
        return row["rate"] if row else None

    def put_fx_rate(self, base: str, quote: str, valuation_date: str, rate: float, source: str = "frankfurter") -> None:
        self._connection.execute(
            "INSERT OR REPLACE INTO fx_rates (base, quote, valuation_date, rate, source) VALUES (?, ?, ?, ?, ?)",
            (base, quote, valuation_date, rate, source),
        )
        self._connection.commit()

