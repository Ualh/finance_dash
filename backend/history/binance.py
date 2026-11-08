"""Binance history: everything the read-only key can reach, as far back as the API keeps it.

Each dataset follows the official docs' limits (developers.binance.com):

| dataset          | endpoint                           | window      | weight / pace          |
|------------------|------------------------------------|-------------|------------------------|
| spot_snapshots   | GET /sapi/v1/accountSnapshot SPOT  | < 30 days   | IP 2400 -> 1 call/12 s |
|                  | (Binance keeps only the last month)|             |                        |
| deposits         | GET /sapi/v1/capital/deposit/hisrec| < 90 days   | IP 1                   |
| withdrawals      | GET /sapi/v1/capital/withdraw/history | < 90 days | UID 18000 -> 1 call/6 s|
| fiat_deposits /  | GET /sapi/v1/fiat/orders           | 89 days     | UID 45000 -> 1 call/15 s|
| fiat_withdrawals |                                    |             |                        |
| fiat_buys /      | GET /sapi/v1/fiat/payments         | 89 days     | IP 1                   |
| fiat_sells       |                                    |             |                        |
| converts         | GET /sapi/v1/convert/tradeFlow     | 30 days     | UID 3000 -> 1 call/s   |
| trades           | GET /api/v3/myTrades, per symbol   | fromId pages| IP 20                  |

/sapi limits are 12000 IP weight or 180000 UID weight per endpoint per minute; /api is
6000 IP weight per minute. Trades need a symbol, so they are read for every listed
pair whose two assets appear anywhere in the account's history or balances.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Callable, Iterable, Optional

from backend.database import SQLiteRepository
from backend.history.engine import (
    MS_PER_DAY,
    DatasetResult,
    IdPagedDataset,
    Pacer,
    WindowedDataset,
    date_to_ms,
    run_dataset,
    with_rate_limit_retry,
)
from backend.sources import binance as api

logger = logging.getLogger(__name__)

SOURCE = "binance"
# Binance opened in July 2017: nothing older exists.
EARLIEST_MS = date_to_ms("2017-07-01")
WINDOW_89_DAYS = 89 * MS_PER_DAY
TRADES_PAGE = 1000
# Quote assets almost every trade goes through, read even if they never show up in the history.
COMMON_ASSETS = frozenset({"BTC", "ETH", "BNB", "USDT", "USDC", "BUSD", "FDUSD", "EUR", "CHF", "USD"})


def _caller(min_interval: float, sleep: Callable[[float], None]) -> Callable[[str, dict], object]:
    pacer = Pacer(min_interval, sleep=sleep)

    def call(endpoint: str, params: dict):
        pacer.wait()
        return with_rate_limit_retry(lambda: api._signed_request(endpoint, params), sleep=sleep)

    return call


def _windowed(name: str, fetch, record_id, occurred_at, window_ms: int, page_size: Optional[int],
              max_lookback_ms: Optional[int] = None) -> WindowedDataset:
    return WindowedDataset(SOURCE, name, fetch, record_id, occurred_at, window_ms, EARLIEST_MS,
                           max_lookback_ms=max_lookback_ms, page_size=page_size)


def windowed_datasets(sleep: Callable[[float], None] = time.sleep) -> list[WindowedDataset]:
    snapshot_call = _caller(12.0, sleep)
    deposit_call = _caller(0.5, sleep)
    withdraw_call = _caller(6.0, sleep)
    fiat_order_call = _caller(15.0, sleep)
    fiat_payment_call = _caller(0.5, sleep)
    convert_call = _caller(1.0, sleep)

    def snapshots(start: int, end: int) -> list[dict]:
        data = snapshot_call("/sapi/v1/accountSnapshot",
                             {"type": "SPOT", "startTime": start, "endTime": end, "limit": 30})
        if data.get("code") not in (None, 200):
            raise RuntimeError(f"accountSnapshot: {data.get('code')} {data.get('msg')}")
        return data.get("snapshotVos") or []

    def deposits(start: int, end: int) -> list[dict]:
        return deposit_call("/sapi/v1/capital/deposit/hisrec", {"startTime": start, "endTime": end, "limit": 1000})

    def withdrawals(start: int, end: int) -> list[dict]:
        return withdraw_call("/sapi/v1/capital/withdraw/history", {"startTime": start, "endTime": end, "limit": 1000})

    def fiat_orders(kind: int):
        def fetch(start: int, end: int) -> list[dict]:
            data = fiat_order_call("/sapi/v1/fiat/orders",
                                   {"transactionType": kind, "beginTime": start, "endTime": end, "page": 1, "rows": 500})
            return data.get("data") or []
        return fetch

    def fiat_payments(kind: int):
        def fetch(start: int, end: int) -> list[dict]:
            data = fiat_payment_call("/sapi/v1/fiat/payments",
                                     {"transactionType": kind, "beginTime": start, "endTime": end, "page": 1, "rows": 500})
            return data.get("data") or []
        return fetch

    def converts(start: int, end: int) -> list[dict]:
        data = convert_call("/sapi/v1/convert/tradeFlow", {"startTime": start, "endTime": end, "limit": 1000})
        return data.get("list") or []

    order_no = lambda r: r["orderNo"]  # noqa: E731
    create_time = lambda r: r.get("createTime")  # noqa: E731
    return [
        # Binance keeps one month of daily snapshots: 29-day windows over the last 30 days.
        _windowed("spot_snapshots", snapshots, lambda r: f"{r.get('type', 'spot')}:{r['updateTime']}",
                  lambda r: r["updateTime"], 29 * MS_PER_DAY, None, max_lookback_ms=30 * MS_PER_DAY),
        _windowed("deposits", deposits, lambda r: r.get("id") or f"{r.get('txId')}:{r.get('coin')}",
                  lambda r: r.get("insertTime"), WINDOW_89_DAYS, 1000),
        _windowed("withdrawals", withdrawals, lambda r: r["id"], lambda r: r.get("applyTime"),
                  WINDOW_89_DAYS, 1000),
        _windowed("fiat_deposits", fiat_orders(0), order_no, create_time, WINDOW_89_DAYS, 500),
        _windowed("fiat_withdrawals", fiat_orders(1), order_no, create_time, WINDOW_89_DAYS, 500),
        _windowed("fiat_buys", fiat_payments(0), order_no, create_time, WINDOW_89_DAYS, 500),
        _windowed("fiat_sells", fiat_payments(1), order_no, create_time, WINDOW_89_DAYS, 500),
        _windowed("converts", converts, lambda r: r["orderId"], create_time, 30 * MS_PER_DAY, 1000),
    ]


def assets_in_history(repo: SQLiteRepository) -> set[str]:
    """Every asset the stored Binance history mentions."""
    fields = {
        "deposits": ("coin",), "withdrawals": ("coin",),
        "fiat_deposits": ("fiatCurrency",), "fiat_withdrawals": ("fiatCurrency",),
        "fiat_buys": ("cryptoCurrency", "fiatCurrency"), "fiat_sells": ("cryptoCurrency", "fiatCurrency"),
        "converts": ("fromAsset", "toAsset"),
    }
    assets: set[str] = set()
    for dataset, keys in fields.items():
        for rec in repo.list_history_records(SOURCE, dataset):
            row = json.loads(rec["payload"])
            assets.update(str(row[k]).upper() for k in keys if row.get(k))
    for rec in repo.list_history_records(SOURCE, "spot_snapshots"):
        for bal in (json.loads(rec["payload"]).get("data") or {}).get("balances") or []:
            if bal.get("asset"):
                assets.add(str(bal["asset"]).upper())
    return assets


def candidate_symbols(exchange_symbols: Iterable[dict], assets: set[str]) -> list[str]:
    """Listed pairs whose base and quote the account has held: the only ones it can have traded."""
    known = assets | COMMON_ASSETS
    return sorted(
        s["symbol"] for s in exchange_symbols
        if s.get("baseAsset") in known and s.get("quoteAsset") in known
    )


def trade_dataset(symbol: str, call: Callable[[str, dict], object]) -> IdPagedDataset:
    def fetch(from_id: int) -> list[dict]:
        return call("/api/v3/myTrades", {"symbol": symbol, "fromId": from_id, "limit": TRADES_PAGE})

    return IdPagedDataset(
        SOURCE, "trades", f"{SOURCE}.trades:{symbol}", fetch,
        row_id=lambda r: int(r["id"]),
        record_id=lambda r: f"{r['symbol']}:{r['id']}",
        occurred_at=lambda r: r.get("time"),
        page_size=TRADES_PAGE,
    )


def _held_assets(call) -> set[str]:
    account = call("/api/v3/account", {"omitZeroBalances": "true"})
    return {
        b["asset"].upper() for b in account.get("balances", [])
        if float(b.get("free") or 0) + float(b.get("locked") or 0) > 0
    }


def backfill_binance(repo: SQLiteRepository, now_ms: Optional[int] = None, since_ms: Optional[int] = None,
                     restart: bool = False, sleep: Callable[[float], None] = time.sleep) -> list[DatasetResult]:
    results = [run_dataset(repo, ds, now_ms, since_ms, restart) for ds in windowed_datasets(sleep)]

    # Trades need a symbol: read every pair whose two assets the history above shows.
    trade_call = _caller(0.5, sleep)
    summary = DatasetResult(f"{SOURCE}.trades")
    try:
        assets = assets_in_history(repo) | _held_assets(trade_call)
        exchange = with_rate_limit_retry(lambda: api._public_request("/api/v3/exchangeInfo"), sleep=sleep)
        symbols = candidate_symbols(exchange.get("symbols", []), assets)
    except Exception as exc:
        logger.exception("could not list Binance trading pairs")
        summary.status, summary.note = "error", f"listing pairs: {exc}"
        return results + [summary]

    for symbol in symbols:
        res = run_dataset(repo, trade_dataset(symbol, trade_call), now_ms, since_ms, restart)
        summary.batches += res.batches
        summary.fetched += res.fetched
        summary.new += res.new
        if res.status != "ok":
            summary.status = "error"
            summary.extra.setdefault("failed", []).append(f"{symbol}: {res.note}")
    summary.note = f"{len(symbols)} pairs"
    if summary.extra.get("failed"):
        summary.note += "; failed " + "; ".join(summary.extra["failed"][:5])
    return results + [summary]
