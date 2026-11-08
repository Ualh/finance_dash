"""Resumable, idempotent history backfill: walk a provider's past in small batches.

Two shapes cover every history endpoint we read:
- `WindowedDataset`: the API takes a start and end time and caps how wide the window
  may be (Binance deposits: under 90 days). We walk from the oldest reachable date to
  now one window at a time. When a window comes back as a full page it may have been
  truncated, so it is split in two and both halves are fetched instead.
- `IdPagedDataset`: the API pages by increasing record id (Binance trades, `fromId`).

After every batch the rows and the resume position are written in one transaction
(`SQLiteRepository.save_history_batch`), so an interrupted run resumes where it stopped
and re-running adds no duplicates: rows are keyed by (source, dataset, record_id).
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional, Union

import requests

from backend.database import SQLiteRepository

logger = logging.getLogger(__name__)

MS_PER_DAY = 86_400_000
# Re-read this much before the saved position on the next run, so late arrivals and
# status changes (a pending deposit that got credited) are picked up.
DEFAULT_OVERLAP_MS = 3 * MS_PER_DAY
# A window narrower than this that still fills a page cannot be split further.
MIN_SPLIT_MS = 1_000
RATE_LIMIT_STATUSES = (418, 429)
MAX_RATE_LIMIT_RETRIES = 5


class ProviderRefused(Exception):
    """The provider will not serve this dataset to this credential (e.g. Wise SCA). Not retried."""


class WindowTooDense(Exception):
    """A window that cannot be split any further still returns a full page."""


class Pacer:
    """Keeps at least `min_interval` seconds between calls, to stay inside the provider's rate limits."""

    def __init__(self, min_interval: float, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.min_interval = min_interval
        self._sleep, self._clock = sleep, clock
        self._last: Optional[float] = None

    def wait(self) -> None:
        if self._last is not None:
            delay = self._last + self.min_interval - self._clock()
            if delay > 0:
                self._sleep(delay)
        self._last = self._clock()


def with_rate_limit_retry(call: Callable[[], object], sleep: Callable[[float], None] = time.sleep):
    """Run `call`; on HTTP 429/418 wait the Retry-After the provider asked for, then try again."""
    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        try:
            return call()
        except requests.HTTPError as exc:
            response = exc.response
            if response is None or response.status_code not in RATE_LIMIT_STATUSES or attempt == MAX_RATE_LIMIT_RETRIES:
                raise
            try:
                wait = float(response.headers.get("Retry-After") or 60)
            except ValueError:
                wait = 60.0
            logger.warning("rate limited (HTTP %s), waiting %.0fs", response.status_code, wait)
            sleep(wait)
    raise AssertionError("unreachable")


def ms_to_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat(timespec="seconds")


def date_to_ms(day: str) -> int:
    return int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)


def normalise_time(value: Union[int, float, str, None]) -> Optional[str]:
    """Epoch milliseconds or a provider date string, as an ISO 8601 UTC string."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return ms_to_iso(int(value))
    text = str(value).strip()
    if text.isdigit():
        return ms_to_iso(int(text))
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)  # Binance and Wise date strings are UTC
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class WindowedDataset:
    source: str
    name: str
    # Rows whose time falls in [start_ms, end_ms], both inclusive.
    fetch: Callable[[int, int], list[dict]]
    record_id: Callable[[dict], str]
    occurred_at: Callable[[dict], object]
    window_ms: int
    earliest_ms: int
    # The API only keeps this much history (Binance snapshots: one month).
    max_lookback_ms: Optional[int] = None
    # A response this long may be truncated, so the window is split. None: fetch pages itself.
    page_size: Optional[int] = None
    overlap_ms: int = DEFAULT_OVERLAP_MS

    @property
    def key(self) -> str:
        return f"{self.source}.{self.name}"


@dataclass(frozen=True)
class IdPagedDataset:
    source: str
    name: str
    cursor_key: str
    # Rows with id >= from_id, oldest first, at most `page_size` of them.
    fetch: Callable[[int], list[dict]]
    row_id: Callable[[dict], int]
    record_id: Callable[[dict], str]
    occurred_at: Callable[[dict], object]
    page_size: int

    @property
    def key(self) -> str:
        return self.cursor_key


Dataset = Union[WindowedDataset, IdPagedDataset]


@dataclass
class DatasetResult:
    key: str
    batches: int = 0
    fetched: int = 0
    new: int = 0
    status: str = "ok"
    note: Optional[str] = None
    extra: dict = field(default_factory=dict)

    def line(self) -> str:
        text = f"{self.key}: {self.status}, {self.fetched} fetched, {self.new} new, {self.batches} batches"
        return f"{text} ({self.note})" if self.note else text


def _records(ds: Dataset, rows: list[dict]) -> list[dict]:
    return [
        {
            "record_id": str(ds.record_id(row)),
            "occurred_at": normalise_time(ds.occurred_at(row)),
            "payload": json.dumps(row, sort_keys=True, separators=(",", ":")),
        }
        for row in rows
    ]


def _fetch_complete(ds: WindowedDataset, start_ms: int, end_ms: int) -> list[dict]:
    rows = ds.fetch(start_ms, end_ms)
    if ds.page_size is None or len(rows) < ds.page_size:
        return rows
    if end_ms - start_ms < MIN_SPLIT_MS:
        raise WindowTooDense(f"{ds.key}: {len(rows)} rows between {ms_to_iso(start_ms)} and {ms_to_iso(end_ms)}")
    mid = (start_ms + end_ms) // 2
    return _fetch_complete(ds, start_ms, mid) + _fetch_complete(ds, mid + 1, end_ms)


def _run_windowed(repo: SQLiteRepository, ds: WindowedDataset, result: DatasetResult, now_ms: int,
                  since_ms: Optional[int], restart: bool) -> None:
    floor = since_ms if since_ms is not None else ds.earliest_ms
    if ds.max_lookback_ms is not None:
        floor = max(floor, now_ms - ds.max_lookback_ms)
    start = floor
    cursor = None if restart else repo.get_history_cursor(ds.key)
    if cursor and cursor.get("position"):
        start = max(floor, int(cursor["position"]) - ds.overlap_ms)

    while start <= now_ms:
        end = min(start + ds.window_ms - 1, now_ms)
        rows = _fetch_complete(ds, start, end)
        result.new += repo.save_history_batch(ds.source, ds.name, _records(ds, rows), ds.key, str(end + 1))
        result.batches += 1
        result.fetched += len(rows)
        logger.info("%s %s..%s: %d rows", ds.key, ms_to_iso(start)[:10], ms_to_iso(end)[:10], len(rows))
        start = end + 1


def _run_id_paged(repo: SQLiteRepository, ds: IdPagedDataset, result: DatasetResult, restart: bool) -> None:
    cursor = None if restart else repo.get_history_cursor(ds.cursor_key)
    from_id = int(cursor["position"]) + 1 if cursor and cursor.get("position") else 0
    while True:
        rows = ds.fetch(from_id)
        if not rows:
            break
        last_id = max(ds.row_id(r) for r in rows)
        result.new += repo.save_history_batch(ds.source, ds.name, _records(ds, rows), ds.cursor_key, str(last_id))
        result.batches += 1
        result.fetched += len(rows)
        logger.info("%s from id %d: %d rows", ds.cursor_key, from_id, len(rows))
        if len(rows) < ds.page_size:
            break
        from_id = last_id + 1


def run_dataset(repo: SQLiteRepository, ds: Dataset, now_ms: Optional[int] = None,
                since_ms: Optional[int] = None, restart: bool = False) -> DatasetResult:
    """Backfill one dataset. A failure stops this dataset only; its saved position is kept."""
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    result = DatasetResult(ds.key)
    try:
        if isinstance(ds, WindowedDataset):
            _run_windowed(repo, ds, result, now_ms, since_ms, restart)
        else:
            _run_id_paged(repo, ds, result, restart)
    except ProviderRefused as exc:
        result.status, result.note = "refused", str(exc)
        repo.set_history_cursor_status(ds.key, "refused", str(exc))
    except Exception as exc:  # keep going with the other datasets; a re-run resumes this one
        logger.exception("backfill failed for %s", ds.key)
        result.status, result.note = "error", str(exc)
        repo.set_history_cursor_status(ds.key, "error", str(exc))
    return result
