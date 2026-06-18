from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

EXPECTED_COLUMNS = [
    "Date", "Amount", "Original amount", "Original currency",
    "Exchange rate", "Description", "Subject", "Category",
    "Tags", "Wise", "Spaces",
]


class NeonParseError(Exception):
    pass


def parse_neon_csv(content: str | bytes) -> list[dict]:
    if isinstance(content, bytes):
        content = content.decode("utf-8-sig")
    content = content.lstrip("\ufeff")

    reader = csv.DictReader(io.StringIO(content), delimiter=";", quoting=csv.QUOTE_ALL)

    if not reader.fieldnames:
        raise NeonParseError("Empty CSV: no header row found")

    normalized = [c.strip() for c in reader.fieldnames]
    missing = [c for c in EXPECTED_COLUMNS if c not in normalized]
    if missing:
        raise NeonParseError(f"Missing required columns: {', '.join(missing)}")

    rows = []
    for i, row in enumerate(reader, start=2):
        cleaned = {k.strip(): v.strip() for k, v in row.items()}
        date_str = cleaned.get("Date", "")
        amount_str = cleaned.get("Amount", "")
        if not date_str or not amount_str:
            logger.warning("Skipping row %d: missing Date or Amount", i)
            continue
        try:
            amount = float(amount_str)
        except ValueError:
            raise NeonParseError(f"Row {i}: invalid Amount value {amount_str!r}")
        rows.append({"date": date_str, "amount": amount})

    return rows


def get_archive_dir(project_root: Path) -> Path:
    archive = project_root / "data" / "csv_archive" / "neon"
    archive.mkdir(parents=True, exist_ok=True)
    return archive


def archive_csv(project_root: Path, content: bytes) -> Path:
    archive = get_archive_dir(project_root)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    dest = archive / f"{timestamp}.csv"
    dest.write_bytes(content)
    logger.info("Archived Neon CSV to %s", dest)
    return dest
