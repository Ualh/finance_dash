from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from backend.database import SQLiteRepository
from backend.snapshots import record_snapshot
from backend.sources import binance, ibkr, wise

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AutomaticSource:
    """A source the daily sync can refresh on its own, given credentials in the environment."""

    name: str
    is_configured: Callable[[], bool]
    sync: Callable[[SQLiteRepository], object]


AUTOMATIC_SOURCES: list[AutomaticSource] = [
    AutomaticSource("binance", binance.is_configured, lambda repo: binance.sync_binance(repo)),
    AutomaticSource("wise", wise.is_configured, lambda repo: wise.sync_wise(repo)),
    AutomaticSource("ibkr", ibkr.is_configured, lambda repo: ibkr.sync_ibkr(repo)),
]


def get_syncable_sources() -> list[AutomaticSource]:
    """Every automatic source whose credentials are set, whether or not it has holdings yet.

    Selecting by existing holdings meant a fresh source (no row yet) was never synced,
    so it could never get its first row.
    """
    return [s for s in AUTOMATIC_SOURCES if s.is_configured()]


def run_sync_all(repo: SQLiteRepository) -> dict[str, list[str]]:
    ok_sources: list[str] = []
    error_sources: list[str] = []

    for source in get_syncable_sources():
        started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        repo.log_sync_start(source.name, started_at)
        try:
            source.sync(repo)
            repo.log_sync_end(source.name, "ok", "sync completed", started_at)
            ok_sources.append(source.name)
        except Exception as exc:
            logger.exception("sync failed for %s", source.name)
            repo.log_sync_end(source.name, "error", str(exc), started_at)
            error_sources.append(source.name)

    record_snapshot(repo)
    return {"ok": ok_sources, "error": error_sources}
