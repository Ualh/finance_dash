"""Reconstructed past: each account's month-end value from before the app recorded it.

The app records a snapshot only from the day a source is connected; before that, only raw
activity exists (the history backfill, Neon CSVs). `rebuild` turns that activity into one value
per account and month-end, stored in `nw_snapshots` flagged `reconstructed`, next to and never
over the recorded snapshots. A stretch an account cannot be rebuilt for is stored as a gap.

How each account is rebuilt:

- Neon: the anchor plus the transactions up to the month-end, the rule of the live balance.
  Before the anchor date nothing is known: a gap.
- Binance: walked backward from the earliest stored daily balance snapshot (per asset), undoing
  deposits, withdrawals, card buys and sells, Convert and Spot trades, for as long as that holds
  up; before that, replayed forward from the empty account at its first activity, for as long as
  that holds up. A walk stops holding up when an asset would be short by more than a dollar:
  activity the API no longer serves (trades on delisted pairs, some transfers) is missing there.
  Between the two is a gap. A month-end after the snapshot starts from the latest snapshot
  before it. Valued at each asset's monthly close on Binance (its USDT pair) and the ECB USD/CHF
  rate (Frankfurter). Airdrops and Earn interest are not in the activity, so walking backward
  counts them a little early.
- Wise: the activity feed is replayed forward from zero, per currency, while it stays possible.
  The feed does not say whether a sent transfer was paid from the balance or straight from a
  bank, so the first activity that would take a balance below zero, or that the feed does not
  describe fully, ends what can be known: from there to the first recorded snapshot is a gap.
"""
from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import groupby
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Iterable, Optional, Protocol

import requests

from backend.database import LIQUIDITY_BUCKET, SQLiteRepository
from backend.fx.service import FrankfurterClient
from backend.history.engine import date_to_ms, ms_to_iso
from backend.sources import binance as binance_api

logger = logging.getLogger(__name__)

ASSET_CLASS = {"neon": "cash", "wise": "cash", "binance": "crypto"}
# Quantities this small are rounding left over by the provider, not holdings.
DUST = 1e-9
# A balance this far below zero cannot have happened: the activity is incomplete.
OVERDRAWN = -0.005
# Binance: an asset short by more than this (in USD) means activity is missing; less is rounding and fees.
UNEXPLAINED_USD = 1.0

USD_STABLECOINS = frozenset({"USD", "USDT", "BUSD", "USDC", "FDUSD", "TUSD", "USDP", "DAI"})
# The same coin under a new ticker, swapped 1:1.
RENAMED = {"RNDR": "RENDER", "FTM": "S"}
# Simple Earn flexible positions show up as "LD" + asset (LDBTC is BTC lent out); LDO is a coin.
EARN_PREFIX = "LD"
NOT_EARN = frozenset({"LDO"})
# Quote assets of Binance spot pairs, longest first so "FDUSD" wins over "USD".
TRADE_QUOTES = tuple(sorted({
    "USDT", "BUSD", "FDUSD", "USDC", "TUSD", "DAI", "USD", "BTC", "ETH", "BNB", "TRX", "XRP", "DOGE", "DOT",
    "EUR", "GBP", "TRY", "BRL", "AUD", "JPY", "RUB", "UAH", "ZAR", "NGN", "PLN", "RON", "ARS", "MXN", "COP",
    "CZK", "BIDR", "IDRT",
}, key=len, reverse=True))

WISE_SPENDING = frozenset({"CARD_PAYMENT", "CARD_ORDER", "CASH_WITHDRAWAL", "CARD_CHECK"})
WISE_TRANSFERS = frozenset({"TRANSFER", "BALANCE_DEPOSIT"})
WISE_AMOUNT = re.compile(r"^([+-]?)\s*(\d[\d,]*(?:\.\d+)?)\s+([A-Z]{3})$")

NEON_GAP = "No Neon statement before the anchor date, so its balance is unknown."
WISE_GAP = ("Wise's activity feed does not say which transfers were paid from the balance, so the "
            "balance cannot be followed from here until the first sync.")
BINANCE_GAP = ("The stored Binance activity cannot account for the balance here: some trades or transfers "
               "are missing (the API serves trades only for pairs still listed).")


class PriceBook(Protocol):
    def usd_price(self, asset: str, day: date) -> Optional[float]:
        """The asset's USD price at the close of `day`'s month, or None when no market quotes it."""

    def chf_rate(self, currency: str, day: date) -> Optional[float]:
        """CHF per unit of `currency` on `day` (the last rate published by then), or None if unknown."""


class PriceUnavailable(Exception):
    """A rate the reconstruction cannot do without could not be found; nothing is replaced."""


@dataclass(frozen=True)
class Gap:
    source: str
    start: Optional[str]  # first unknown day; None: since the beginning
    end: Optional[str]    # last unknown day; None: still unknown
    reason: str


@dataclass
class Reconstruction:
    source: str
    values: dict[str, float] = field(default_factory=dict)  # month-end day -> CHF
    gaps: list[Gap] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def line(self) -> str:
        if self.values:
            days = sorted(self.values)
            text = f"{self.source}: {len(days)} months reconstructed, {days[0]} to {days[-1]}"
        else:
            text = f"{self.source}: nothing reconstructed"
        for gap in self.gaps:
            text += f"; gap {gap.start or 'start'} to {gap.end or 'now'}"
        return "; ".join([text, *self.notes])


def _day(value: str) -> date:
    return date.fromisoformat(value[:10])


def month_ends(first: date, stop: date) -> list[date]:
    """The last day of every month from `first`'s month on, keeping only days before `stop`."""
    days: list[date] = []
    end = last_day_of_month(first)
    while end < stop:
        days.append(end)
        end = last_day_of_month(end + timedelta(days=1))
    return days


def last_day_of_month(day: date) -> date:
    nxt = date(day.year + day.month // 12, day.month % 12 + 1, 1)
    return nxt - timedelta(days=1)


def _stop(first_recorded: Optional[str], today: date) -> date:
    """Rebuild only before the first recorded snapshot, and only months that have ended."""
    month_start = today.replace(day=1)
    return min(_day(first_recorded), month_start) if first_recorded else month_start


def _gap_end(first_recorded: Optional[str]) -> Optional[str]:
    return (_day(first_recorded) - timedelta(days=1)).isoformat() if first_recorded else None


# --- Neon -----------------------------------------------------------------------------------

def neon_reconstruction(transactions: list[dict], anchor_date: Optional[str], anchor_amount: Optional[float],
                        first_recorded: Optional[str], today: date) -> Reconstruction:
    result = Reconstruction("neon")
    if anchor_date is not None and anchor_amount is not None:
        start, base = _day(anchor_date), anchor_amount
        counted = [t for t in transactions if t["date"] >= anchor_date]
        result.gaps.append(Gap("neon", None, (start - timedelta(days=1)).isoformat(), NEON_GAP))
    elif transactions:
        start, base, counted = _day(transactions[0]["date"]), 0.0, transactions
    else:
        return result
    for day in month_ends(start, _stop(first_recorded, today)):
        key = day.isoformat()
        result.values[key] = round(base + sum(t["amount"] for t in counted if t["date"] <= key), 2)
    return result


# --- Binance --------------------------------------------------------------------------------

def binance_asset(raw: str) -> str:
    asset = raw.upper()
    if asset.startswith(EARN_PREFIX) and len(asset) > len(EARN_PREFIX) and asset not in NOT_EARN:
        asset = asset[len(EARN_PREFIX):]
    return RENAMED.get(asset, asset)


def split_symbol(symbol: str) -> Optional[tuple[str, str]]:
    for quote in TRADE_QUOTES:
        if symbol.endswith(quote) and len(symbol) > len(quote):
            return symbol[: -len(quote)], quote
    return None


def _num(row: dict, key: str) -> float:
    return float(row.get(key) or 0)


def _binance_deltas(dataset: str, row: dict) -> Optional[dict[str, float]]:
    """How one stored record moved the account's holdings, or None when it did not happen."""
    if dataset == "deposits":
        return {row["coin"]: _num(row, "amount")} if row.get("status") in (1, 6) else None
    if dataset == "withdrawals":
        # 1 cancelled, 3 rejected, 5 failed; anything else has left the balance.
        if row.get("status") in (1, 3, 5):
            return None
        return {row["coin"]: -(_num(row, "amount") + _num(row, "transactionFee"))}
    if dataset == "fiat_deposits":
        ok = row.get("status") == "Successful"
        return {row["fiatCurrency"]: _num(row, "amount") - _num(row, "totalFee")} if ok else None
    if dataset == "fiat_withdrawals":
        return {row["fiatCurrency"]: -_num(row, "amount")} if row.get("status") == "Successful" else None
    if dataset == "fiat_buys":
        return {row["cryptoCurrency"]: _num(row, "obtainAmount")} if row.get("status") == "Completed" else None
    if dataset == "fiat_sells":
        return {row["cryptoCurrency"]: -_num(row, "sourceAmount")} if row.get("status") == "Completed" else None
    if dataset == "converts":
        if row.get("orderStatus") != "SUCCESS":
            return None
        return {row["fromAsset"]: -_num(row, "fromAmount"), row["toAsset"]: _num(row, "toAmount")}
    if dataset == "trades":
        pair = split_symbol(row["symbol"])
        if pair is None:
            return None
        base, quote = pair
        sign = 1 if row.get("isBuyer") else -1
        deltas = {base: sign * _num(row, "qty"), quote: -sign * _num(row, "quoteQty")}
        fee_asset = row.get("commissionAsset")
        if fee_asset:
            deltas[fee_asset] = deltas.get(fee_asset, 0.0) - _num(row, "commission")
        return deltas
    return None


Holdings = tuple[str, dict[str, float]]  # (day, asset -> quantity or quantity change)

BINANCE_FLOWS = ("deposits", "withdrawals", "fiat_deposits", "fiat_withdrawals", "fiat_buys", "fiat_sells",
                 "converts", "trades")


def _merge(into: dict[str, float], deltas: dict[str, float], sign: int = 1) -> None:
    for raw, qty in deltas.items():
        into[binance_asset(raw)] += sign * qty


def binance_events(records: dict[str, list[dict]]) -> list[Holdings]:
    """Every stored flow as (day, asset -> quantity change), oldest first."""
    events = []
    for dataset in BINANCE_FLOWS:
        for rec in records.get(dataset, []):
            deltas = _binance_deltas(dataset, json.loads(rec["payload"]))
            if deltas and rec.get("occurred_at"):
                events.append((rec["occurred_at"][:10], deltas))
    return sorted(events, key=lambda e: e[0])


def binance_snapshots(records: list[dict]) -> list[Holdings]:
    """Stored daily balance snapshots as (day, asset -> quantity), oldest first."""
    snapshots = []
    for rec in records:
        holdings: dict[str, float] = defaultdict(float)
        for bal in (json.loads(rec["payload"]).get("data") or {}).get("balances") or []:
            holdings[binance_asset(bal["asset"])] += _num(bal, "free") + _num(bal, "locked")
        snapshots.append((rec["occurred_at"][:10], dict(holdings)))
    return sorted(snapshots, key=lambda s: s[0])


def holdings_on(day: str, snapshots: list[Holdings], events: list[Holdings]) -> dict[str, float]:
    """Quantities at the end of `day`: from the latest snapshot by then, else back from the earliest one."""
    earlier = [s for s in snapshots if s[0] <= day]
    base_day, base = earlier[-1] if earlier else snapshots[0]
    holdings: dict[str, float] = defaultdict(float, base)
    for when, deltas in events:
        if base_day < when <= day:
            _merge(holdings, deltas)
        elif day < when <= base_day:
            _merge(holdings, deltas, sign=-1)
    return holdings


def replayed(day: str, events: list[Holdings]) -> dict[str, float]:
    """Quantities at the end of `day`, replaying every flow from an empty account."""
    holdings: dict[str, float] = defaultdict(float)
    for when, deltas in events:
        if when <= day:
            _merge(holdings, deltas)
    return holdings


def _by_day(events: list[Holdings]) -> list[tuple[str, list[dict[str, float]]]]:
    return [(day, [deltas for _, deltas in group]) for day, group in groupby(events, key=lambda e: e[0])]


def _short(holdings: dict[str, float], prices: PriceBook, day: str) -> bool:
    """True when the holdings cannot have been real: an asset is short by more than UNEXPLAINED_USD.

    Stablecoins and USD count as one, since Binance swapped them for each other without a record
    (a USD deposit spent as BUSD, BUSD turned into FDUSD).
    """
    pooled: dict[str, float] = defaultdict(float)
    for asset, qty in holdings.items():
        pooled["USD" if asset in USD_STABLECOINS else asset] += qty
    month_end = last_day_of_month(_day(day))
    for asset, qty in pooled.items():
        if qty < 0:
            price = prices.usd_price(asset, month_end)
            if price is not None and qty * price < -UNEXPLAINED_USD:
                return True
    return False


def forward_limit(events: list[Holdings], prices: PriceBook) -> Optional[str]:
    """The first day on which replaying from an empty account leaves an asset short, or None."""
    holdings: dict[str, float] = defaultdict(float)
    for day, changes in _by_day(events):
        for deltas in changes:
            _merge(holdings, deltas)
        if _short(holdings, prices, day):
            return day
    return None


def backward_limit(snapshot: Holdings, events: list[Holdings], prices: PriceBook) -> Optional[str]:
    """The earliest day walking back from `snapshot` holds up to; the day before it an asset would be short."""
    base_day, base = snapshot
    holdings: dict[str, float] = defaultdict(float, base)
    for day, changes in reversed(_by_day([e for e in events if e[0] <= base_day])):
        for deltas in changes:
            _merge(holdings, deltas, sign=-1)
        if _short(holdings, prices, (_day(day) - timedelta(days=1)).isoformat()):
            return day
    return None


def binance_reconstruction(records: dict[str, list[dict]], prices: PriceBook,
                           first_recorded: Optional[str], today: date) -> Reconstruction:
    """Back from the earliest snapshot while that holds up, forward from zero before it, a gap between."""
    result = Reconstruction("binance")
    events = binance_events(records)
    snapshots = binance_snapshots(records.get("spot_snapshots", []))
    starts = [e[0] for e in events[:1]] + [s[0] for s in snapshots[:1]]
    if not starts:
        return result
    forward_until = forward_limit(events, prices)
    backward_from = backward_limit(snapshots[0], events, prices) if snapshots else None

    unpriced: dict[str, int] = defaultdict(int)
    for day in month_ends(_day(min(starts)), _stop(first_recorded, today)):
        key = day.isoformat()
        if snapshots and (backward_from is None or key >= backward_from):
            holdings = holdings_on(key, snapshots, events)
        elif forward_until is None or key < forward_until:
            holdings = replayed(key, events)
        else:
            continue
        usd = 0.0
        for asset, qty in holdings.items():
            if abs(qty) < DUST:
                continue
            price = prices.usd_price(asset, day)
            if price is None:
                unpriced[asset] += 1
                continue
            usd += qty * price
        rate = prices.chf_rate("USD", day)
        if rate is None:
            raise PriceUnavailable(f"no USD/CHF rate for {day}")
        result.values[key] = round(usd * rate, 2)

    if forward_until is not None:
        if not snapshots:
            result.gaps.append(Gap("binance", forward_until, _gap_end(first_recorded), BINANCE_GAP))
        elif backward_from is not None and forward_until < backward_from:
            gap_end = (_day(backward_from) - timedelta(days=1)).isoformat()
            result.gaps.append(Gap("binance", forward_until, gap_end, BINANCE_GAP))
    if unpriced:
        listed = ", ".join(f"{a} ({n} month{'' if n == 1 else 's'})" for a, n in sorted(unpriced.items()))
        result.notes.append(f"no market price, left out: {listed}")
    return result


# --- Wise -----------------------------------------------------------------------------------

def wise_amount(text: Optional[str]) -> Optional[tuple[float, str]]:
    """A feed amount ("<positive>+ 1,000 CHF</positive>", "9,038 MXN") as a signed number and currency."""
    plain = re.sub(r"<[^>]+>", "", text or "").strip()
    match = WISE_AMOUNT.match(plain)
    if not match:
        return None
    sign, number, currency = match.groups()
    value = float(number.replace(",", ""))
    inflow = sign == "+" or "<positive>" in (text or "")
    return (value if inflow else -value), currency


def _wise_change(row: dict) -> Optional[tuple[float, str]]:
    """How a completed activity moved one balance; None when the feed does not say."""
    if row.get("type") not in WISE_SPENDING | WISE_TRANSFERS:
        return None
    primary = wise_amount(row.get("primaryAmount"))
    if primary is None or primary[0] >= 0:
        return primary
    if not row.get("secondaryAmount"):
        return primary
    # Paid in another currency: the secondary amount is what left the balance.
    secondary = wise_amount(row["secondaryAmount"])
    return (-abs(secondary[0]), secondary[1]) if secondary else None


def wise_reconstruction(records: list[dict], prices: PriceBook, first_recorded: Optional[str],
                        today: date) -> Reconstruction:
    result = Reconstruction("wise")
    activities = sorted((r for r in records if r.get("occurred_at")), key=lambda r: r["occurred_at"])
    if not activities:
        return result

    balances: dict[str, float] = defaultdict(float)
    timeline: list[tuple[str, dict[str, float]]] = []
    unknown_from: Optional[str] = None
    completed = [(r["occurred_at"][:10], json.loads(r["payload"])) for r in activities]
    # A day is settled as a whole: the feed may list a payment just before the top-up that paid for it.
    for day, group in groupby((a for a in completed if a[1].get("status") == "COMPLETED"), key=lambda a: a[0]):
        changes = [_wise_change(row) for _, row in group]
        if None in changes:
            unknown_from = day
            break
        for amount, currency in changes:
            balances[currency] += amount
        if any(v < OVERDRAWN for v in balances.values()):
            unknown_from = day
            break
        timeline.append((day, dict(balances)))

    stop = _stop(first_recorded, today)
    if unknown_from is not None:
        stop = min(stop, _day(unknown_from))
        result.gaps.append(Gap("wise", unknown_from, _gap_end(first_recorded), WISE_GAP))
    for day in month_ends(_day(activities[0]["occurred_at"]), stop):
        key = day.isoformat()
        held = next((b for when, b in reversed(timeline) if when <= key), {})
        value = 0.0
        for currency, amount in held.items():
            if abs(amount) < DUST:
                continue
            rate = prices.chf_rate(currency, day)
            if rate is None:
                raise PriceUnavailable(f"no {currency}/CHF rate for {day}")
            value += amount * rate
        result.values[key] = round(value, 2)
    return result


# --- Prices ---------------------------------------------------------------------------------

KLINES_SINCE_MS = date_to_ms("2017-07-01")
FX_SINCE = "2011-01-01"


class MarketPrices:
    """Month closes from Binance's public klines and ECB rates from Frankfurter, cached in `fx_rates`."""

    def __init__(self, repo: SQLiteRepository, klines: Optional[Callable[[str], list]] = None,
                 fx_series: Optional[Callable[[str, str, str], dict[str, float]]] = None,
                 now: Optional[datetime] = None) -> None:
        self._repo = repo
        self._klines = klines or self._fetch_klines
        self._fx_series = fx_series or (lambda base, start, end: FrankfurterClient().fetch_series(base, "CHF", start, end))
        self._now = now or datetime.now(timezone.utc)
        self._closes: dict[str, dict[str, float]] = {}
        self._fx: dict[str, dict[str, float]] = {}

    @staticmethod
    def _fetch_klines(symbol: str) -> list:
        params = {"symbol": symbol, "interval": "1M", "startTime": KLINES_SINCE_MS, "limit": 1000}
        try:
            return binance_api._public_request("/api/v3/klines", params)
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 400:  # not a Binance pair
                return []
            raise

    def _monthly_closes(self, asset: str) -> dict[str, float]:
        if asset not in self._closes:
            now_ms = self._now.timestamp() * 1000
            closes: dict[str, float] = {}
            old_names = [old for old, new in RENAMED.items() if new == asset]
            for ticker in [asset, *old_names]:
                for kline in self._klines(f"{ticker}USDT"):
                    month = ms_to_iso(int(kline[0]))[:7]
                    if int(kline[6]) < now_ms and month not in closes:
                        closes[month] = float(kline[4])
            self._closes[asset] = closes
            self._repo.put_fx_rates([(asset, "USD", last_day_of_month(date.fromisoformat(f"{m}-01")).isoformat(), rate, "binance") for m, rate in closes.items()])
        return self._closes[asset]

    def usd_price(self, asset: str, day: date) -> Optional[float]:
        if asset in USD_STABLECOINS:
            return 1.0
        cached = self._repo.get_cached_fx_rate(asset, "USD", day.isoformat())
        if cached is not None:
            return cached
        return self._monthly_closes(asset).get(day.strftime("%Y-%m"))

    def chf_rate(self, currency: str, day: date) -> Optional[float]:
        if currency == "CHF":
            return 1.0
        cached = self._repo.get_cached_fx_rate(currency, "CHF", day.isoformat())
        if cached is not None:
            return cached
        if currency not in self._fx:
            self._fx[currency] = self._fx_series(currency, FX_SINCE, self._now.date().isoformat())
        published = [d for d in self._fx[currency] if d <= day.isoformat()]
        if not published:
            return None
        rate = self._fx[currency][max(published)]
        self._repo.put_fx_rates([(currency, "CHF", day.isoformat(), rate, "frankfurter")])
        return rate


# --- Rebuild --------------------------------------------------------------------------------

def _points(rebuilt: Reconstruction) -> Iterable[dict]:
    bucket = LIQUIDITY_BUCKET[ASSET_CLASS[rebuilt.source]]
    for day, value in rebuilt.values.items():
        buckets = {"available": 0.0, "invested": 0.0, "locked": 0.0, bucket: value}
        yield {"date": day, "source": rebuilt.source, "total_chf": value, "available_chf": buckets["available"],
               "invested_chf": buckets["invested"], "locked_chf": buckets["locked"]}


def rebuild(repo: SQLiteRepository, prices: Optional[PriceBook] = None, today: Optional[date] = None) -> list[str]:
    """Replace the reconstructed past with one rebuilt from the stored activity. Returns one line per account."""
    today = today or datetime.now(timezone.utc).date()
    prices = prices or MarketPrices(repo)
    recorded = repo.first_recorded_snapshot_dates()
    anchor_date, anchor_amount = repo.get_neon_anchor()
    binance_records = {ds: repo.list_history_records("binance", ds) for ds in (*BINANCE_FLOWS, "spot_snapshots")}
    rebuilt = [
        neon_reconstruction(repo.list_neon_transactions(), anchor_date, anchor_amount, recorded.get("neon"), today),
        binance_reconstruction(binance_records, prices, recorded.get("binance"), today),
        wise_reconstruction(repo.list_history_records("wise", "activities"), prices, recorded.get("wise"), today),
    ]
    points = [p for r in rebuilt for p in _points(r)]
    gaps = [g.__dict__ for r in rebuilt for g in r.gaps]
    repo.replace_reconstruction(points, gaps)
    return [r.line() for r in rebuilt]
