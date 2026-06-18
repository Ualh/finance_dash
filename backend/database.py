from __future__ import annotations

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

            CREATE TABLE IF NOT EXISTS neon_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                amount REAL NOT NULL,
                created_at TEXT NOT NULL
            );
        """)
        self._connection.commit()

    def upsert_holding(self, source: str, source_type: str, asset_class: str, value_chf: float, label: Optional[str] = None) -> dict:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        label = label or ""
        cursor = self._connection.cursor()
        cursor.execute("""
            INSERT INTO holdings (source, source_type, asset_class, value_chf, label, last_updated)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, source_type, label) DO UPDATE SET
                value_chf = excluded.value_chf,
                last_updated = excluded.last_updated
        """, (source, source_type, asset_class, value_chf, label, now))
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

    def replace_neon_transactions_in_date_range(self, min_date: str, max_date: str, rows: list[dict]) -> None:
        cursor = self._connection.cursor()
        cursor.execute(
            "DELETE FROM neon_transactions WHERE date >= ? AND date <= ?",
            (min_date, max_date),
        )
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cursor.executemany(
            "INSERT INTO neon_transactions (date, amount, created_at) VALUES (?, ?, ?)",
            [(r["date"], r["amount"], now) for r in rows],
        )
        self._connection.commit()

    def get_all_neon_transactions(self) -> list[dict]:
        rows = self._connection.execute(
            "SELECT date, amount FROM neon_transactions ORDER BY date"
        ).fetchall()
        return [dict(r) for r in rows]
