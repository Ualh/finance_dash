"""Daily SQLite backup: a consistent copy via the SQLite backup API, oldest copies pruned.

Run as `python -m backend.backup` (the finance-dash-backup systemd unit does this).
Configuration comes from the same environment as the app:
- FINANCE_DASH_DB_FILE: database to copy (default ./finance_dash.db)
- FINANCE_DASH_BACKUP_DIR: where copies go (default ~/backups/finance_dash)
- FINANCE_DASH_BACKUP_KEEP: how many daily copies to keep (default 30)
"""
from __future__ import annotations

import os
import sqlite3
import sys
from datetime import date
from pathlib import Path
from typing import Optional

from backend.config import load_config

PREFIX = "finance_dash_"


def backup_database(database: Path, backup_dir: Path, keep: int, today: Optional[date] = None) -> Path:
    if not database.is_file():
        raise FileNotFoundError(f"database not found: {database}")
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"{PREFIX}{(today or date.today()).strftime('%Y%m%d')}.db"
    partial = target.with_suffix(".db.partial")

    source = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    dest = sqlite3.connect(partial)
    try:
        source.backup(dest)
    finally:
        dest.close()
        source.close()
    partial.replace(target)

    copies = sorted(backup_dir.glob(f"{PREFIX}*.db"))
    for old in copies[:-keep] if keep > 0 else []:
        old.unlink()
    return target


def main() -> int:
    database = load_config().database_file
    backup_dir = Path(os.environ.get("FINANCE_DASH_BACKUP_DIR") or Path.home() / "backups" / "finance_dash")
    keep = int(os.environ.get("FINANCE_DASH_BACKUP_KEEP") or 30)
    target = backup_database(database, backup_dir, keep)
    print(f"backed up {database} to {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
