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
        self._connection = sqlite3.connect(database_path, detect_types=sqlite3.PARSE_DECLTYPES)
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
                total_chf REAL NOT NULL,
                available_chf REAL NOT NULL,
                invested_chf REAL NOT NULL,
                locked_chf REAL NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(snapshot_date)
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
        """)
        self._connection.commit()

    def upsert_holding(self, source: str, source_type: str, asset_class: str, value_chf: float, label: Optional[str] = None) -> dict:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cursor = self._connection.cursor()
        cursor.execute("""
            INSERT INTO holdings (source, source_type, asset_class, value_chf, label, last_updated)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, source_type, COALESCE(label, '')) DO UPDATE SET
                value_chf = excluded.value_chf,
                last_updated = excluded.last_updated
        """, (source, source_type, asset_class, value_chf, label, now))
        self._connection.commit()
        row = cursor.execute(
            "SELECT * FROM holdings WHERE source = ? AND source_type = ? AND COALESCE(label, '') = ?",
            (source, source_type, label or ""),
        ).fetchone()
        return dict(row)

    def list_holdings(self) -> list[dict]:
        cursor = self._connection.cursor()
        rows = cursor.execute("SELECT * FROM holdings ORDER BY last_updated DESC").fetchall()
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
