from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Protocol

from backend.database import SQLiteRepository

logger = logging.getLogger(__name__)


class SourceSync(Protocol):
    name: str

    def sync(self, repo: SQLiteRepository) -> None: ...


class FinpensionSync:
    name = "finpension"

    def sync(self, repo: SQLiteRepository) -> None:
        pass


class CSVUploadSync:
    name = "csv_upload"

    def sync(self, repo: SQLiteRepository) -> None:
        pass


class PostFinanceSync:
    name = "postfinance"

    def sync(self, repo: SQLiteRepository) -> None:
        pass


class CoinRKingSync:
    name = "coinranking"

    def sync(self, repo: SQLiteRepository) -> None:
        pass


class SwissquoteSync:
    name = "swissquote"

    def sync(self, repo: SQLiteRepository) -> None:
        pass


class VIACSync:
    name = "viac"

    def sync(self, repo: SQLiteRepository) -> None:
        pass


SYNC_SOURCES: list[SourceSync] = [
    FinpensionSync(),
    CSVUploadSync(),
    PostFinanceSync(),
    CoinRKingSync(),
    SwissquoteSync(),
    VIACSync(),
]

MANUAL_SOURCES = {"finpension", "csv_upload"}


def get_syncable_sources(repo: SQLiteRepository) -> list[SourceSync]:
    configured = set(repo.list_sources())
    return [s for s in SYNC_SOURCES if s.name in configured]


def run_sync_all(repo: SQLiteRepository) -> dict[str, list[str]]:
    ok_sources: list[str] = []
    error_sources: list[str] = []

    sources = get_syncable_sources(repo)

    for source_module in sources:
        started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        repo.log_sync_start(source_module.name, started_at)
        try:
            source_module.sync(repo)
            repo.log_sync_end(source_module.name, "ok", "sync completed", started_at)
            ok_sources.append(source_module.name)
        except Exception as exc:
            logger.exception("sync failed for %s", source_module.name)
            repo.log_sync_end(source_module.name, "error", str(exc), started_at)
            error_sources.append(source_module.name)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    all_sources = repo.list_sources()
    for src in all_sources:
        agg = repo.get_source_aggregate(src)
        repo.upsert_snapshot(
            snapshot_date=today,
            source=src,
            total_chf=agg["total_chf"],
            available_chf=agg["buckets"]["available"],
            invested_chf=agg["buckets"]["invested"],
            locked_chf=agg["buckets"]["locked"],
        )

    total_agg = repo.get_aggregate_holdings()
    repo.upsert_snapshot(
        snapshot_date=today,
        source="total",
        total_chf=total_agg["total_chf"],
        available_chf=total_agg["buckets"]["available"],
        invested_chf=total_agg["buckets"]["invested"],
        locked_chf=total_agg["buckets"]["locked"],
    )

    return {"ok": ok_sources, "error": error_sources}
