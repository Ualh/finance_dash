"""Wise history: what a personal API token can read without SCA signing.

- activities: `GET /v1/profiles/{profileId}/activities` (since/until, cursor pages of up
  to 100). The activity feed: transfers, card payments, deposits, cash withdrawals...
  Amounts are display strings such as "150 JPY", so they are kept as received.
- transfers: `GET /v1/transfers?profile=...` (createdDateStart/End, offset pages):
  transfers you sent, with numeric source and target amounts.

Not reachable: balance statements (`/v1/profiles/{id}/balance-statements/...`) require
SCA, which Wise no longer supports for personal tokens under PSD2, so they are never
requested. If Wise ever answers 403 on an endpoint above (an SCA challenge), that dataset
is marked refused and skipped: the backfill never tries to sign or work around it.
"""
from __future__ import annotations

import logging
import time
from typing import Callable, Optional

import requests

from backend.database import SQLiteRepository
from backend.history.engine import (
    MS_PER_DAY,
    DatasetResult,
    Pacer,
    ProviderRefused,
    WindowedDataset,
    date_to_ms,
    run_dataset,
    with_rate_limit_retry,
)
from backend.sources import wise as api

logger = logging.getLogger(__name__)

SOURCE = "wise"
# Wise (then TransferWise) launched in 2011: nothing older exists.
EARLIEST_MS = date_to_ms("2011-01-01")
WINDOW_MS = 365 * MS_PER_DAY
ACTIVITIES_PAGE = 100
TRANSFERS_PAGE = 100
SCA_REFUSAL = ("Wise answered 403: this endpoint needs SCA signing, which personal tokens cannot do "
               "(PSD2); not attempted")


def _iso(ms: int) -> str:
    seconds, millis = divmod(ms, 1000)
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(seconds)) + f".{millis:03d}Z"


def _caller(min_interval: float, sleep: Callable[[float], None]) -> Callable[[str, dict], object]:
    pacer = Pacer(min_interval, sleep=sleep)

    def call(path: str, params: dict):
        pacer.wait()
        try:
            return with_rate_limit_retry(lambda: api._get(path, params), sleep=sleep).json()
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 403:
                raise ProviderRefused(SCA_REFUSAL) from exc
            raise

    return call


def datasets(profile_id: int, sleep: Callable[[float], None] = time.sleep) -> list[WindowedDataset]:
    call = _caller(0.5, sleep)

    def activities(start: int, end: int) -> list[dict]:
        rows: list[dict] = []
        params = {"since": _iso(start), "until": _iso(end), "size": ACTIVITIES_PAGE}
        while True:
            data = call(f"/v1/profiles/{profile_id}/activities", params)
            rows.extend(data.get("activities") or [])
            cursor = data.get("cursor")
            if not cursor:
                return rows
            params = {**params, "nextCursor": cursor}

    def transfers(start: int, end: int) -> list[dict]:
        rows: list[dict] = []
        offset = 0
        while True:
            page = call("/v1/transfers", {
                "profile": profile_id, "createdDateStart": _iso(start), "createdDateEnd": _iso(end),
                "limit": TRANSFERS_PAGE, "offset": offset,
            })
            rows.extend(page)
            if len(page) < TRANSFERS_PAGE:
                return rows
            offset += TRANSFERS_PAGE

    return [
        WindowedDataset(SOURCE, "activities", activities, lambda r: r["id"], lambda r: r.get("createdOn"),
                        WINDOW_MS, EARLIEST_MS),
        WindowedDataset(SOURCE, "transfers", transfers, lambda r: r["id"], lambda r: r.get("created"),
                        WINDOW_MS, EARLIEST_MS),
    ]


def backfill_wise(repo: SQLiteRepository, now_ms: Optional[int] = None, since_ms: Optional[int] = None,
                  restart: bool = False, sleep: Callable[[float], None] = time.sleep) -> list[DatasetResult]:
    profile_id = api.get_profile_id()
    return [run_dataset(repo, ds, now_ms, since_ms, restart) for ds in datasets(profile_id, sleep)]
