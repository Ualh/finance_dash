"""Backfill Binance and Wise history into the local database, then rebuild the reconstructed past.

    python -m backend.history                  # every configured source, all reachable history
    python -m backend.history --source binance
    python -m backend.history --since 2021-01-01
    python -m backend.history --restart        # ignore saved positions, re-read everything
    python -m backend.history --reconstruct-only  # skip the backfill, only rebuild the past

Safe to stop and re-run: it resumes from the last saved batch and never stores a row twice.
Every run ends by rebuilding each account's month-end values from the stored activity
(`backend.history.reconstruct`), which needs no credentials, only public prices.
Uses the same .env and database (FINANCE_DASH_DB_FILE) as the app. Exits 1 if any dataset
or the rebuild failed.
"""
from __future__ import annotations

import argparse
import logging
import sys

from backend.config import load_config
from backend.database import SQLiteRepository
from backend.history.binance import backfill_binance
from backend.history.engine import date_to_ms
from backend.history.reconstruct import rebuild
from backend.history.wise import backfill_wise
from backend.sources import binance, wise

SOURCES = {
    "binance": (binance.is_configured, backfill_binance),
    "wise": (wise.is_configured, backfill_wise),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend.history", description=__doc__.splitlines()[0])
    parser.add_argument("--source", choices=[*SOURCES, "all"], default="all")
    parser.add_argument("--since", help="oldest day to read, YYYY-MM-DD (default: as far back as the API allows)")
    parser.add_argument("--restart", action="store_true", help="ignore saved positions and re-read everything")
    parser.add_argument("--reconstruct-only", action="store_true",
                        help="skip the backfill and only rebuild the reconstructed past from what is stored")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    since_ms = date_to_ms(args.since) if args.since else None
    repo = SQLiteRepository(load_config().database_file)
    repo.initialise_schema()
    failed = False
    try:
        for name, (is_configured, backfill) in SOURCES.items():
            if args.reconstruct_only or args.source not in ("all", name):
                continue
            if not is_configured():
                print(f"{name}: skipped, no credentials in the environment")
                continue
            try:
                results = backfill(repo, since_ms=since_ms, restart=args.restart)
            except Exception as exc:
                print(f"{name}: error, {exc}")
                failed = True
                continue
            for result in results:
                print(result.line())
                failed = failed or result.status == "error"
        try:
            for line in rebuild(repo):
                print(f"reconstructed {line}")
        except Exception as exc:
            logging.exception("rebuilding the reconstructed past failed")
            print(f"reconstruction: error, {exc}; the previous reconstruction is kept")
            failed = True
    finally:
        repo.close()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
