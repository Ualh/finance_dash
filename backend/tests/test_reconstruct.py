"""Reconstructed past: each account rebuilt month by month from stored activity, gaps where it cannot be."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests
from fastapi.testclient import TestClient
from freezegun import freeze_time

from backend.api import app
from backend.config import AppConfig
from backend.database import SQLiteRepository
from backend.fx.service import FrankfurterClient
from backend.history import reconstruct
from backend.history.reconstruct import (
    MarketPrices,
    PriceUnavailable,
    binance_reconstruction,
    month_ends,
    neon_reconstruction,
    rebuild,
    split_symbol,
    wise_amount,
    wise_reconstruction,
)
from backend.snapshots import monthly_history

FIXTURES = Path(__file__).parent / "fixtures"


class FakePrices:
    """Month closes and FX rates given per month ("2022-03"); anything not listed has no price."""

    def __init__(self, usd: dict[str, dict[str, float]], chf: dict[str, dict[str, float]]):
        self.usd, self.chf = usd, chf

    def usd_price(self, asset, day):
        if asset in reconstruct.USD_STABLECOINS:
            return 1.0
        return self.usd.get(asset, {}).get(day.strftime("%Y-%m"))

    def chf_rate(self, currency, day):
        if currency == "CHF":
            return 1.0
        return self.chf.get(currency, {}).get(day.strftime("%Y-%m"))


def months(*pairs: tuple[str, float]) -> dict[str, float]:
    return dict(pairs)


BTC = months(("2021-12", 45_000), ("2022-01", 40_000), ("2022-02", 40_000), ("2022-03", 45_000),
             ("2022-04", 40_000), ("2022-05", 30_000), ("2022-06", 20_000), ("2022-07", 24_000))
EVERY_MONTH_2022 = [f"2022-{m:02d}" for m in range(1, 13)] + ["2021-12"]
BINANCE_PRICES = FakePrices(
    usd={"BTC": BTC, "RENDER": {m: 2.0 for m in EVERY_MONTH_2022}, "ETH": {m: 3_000.0 for m in EVERY_MONTH_2022}},
    chf={"USD": {m: 0.8 for m in EVERY_MONTH_2022}},
)
WISE_PRICES = FakePrices(usd={}, chf={"EUR": {"2024-07": 0.95, "2024-08": 0.9}, "MXN": {"2024-07": 0.05}})


@pytest.fixture
def repo(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.db")
    repo.initialise_schema()
    yield repo
    repo.close()


def store_fixture(repo: SQLiteRepository, source: str, dataset: str, rows: list[dict]) -> None:
    repo.save_history_batch(source, dataset, [
        {"record_id": f"{dataset}:{i}", "occurred_at": r["occurred_at"], "payload": json.dumps(r["payload"])}
        for i, r in enumerate(rows)
    ])


def binance_records(repo: SQLiteRepository) -> dict[str, list[dict]]:
    fixture = json.loads((FIXTURES / "binance_history.json").read_text())
    for dataset, rows in fixture.items():
        if not dataset.startswith("_"):
            store_fixture(repo, "binance", dataset, rows)
    return {ds: repo.list_history_records("binance", ds) for ds in fixture if not ds.startswith("_")}


def wise_records(repo: SQLiteRepository) -> list[dict]:
    store_fixture(repo, "wise", "activities", json.loads((FIXTURES / "wise_activities.json").read_text()))
    return repo.list_history_records("wise", "activities")


def test_month_ends_stop_before_the_given_day():
    assert month_ends(date(2023, 11, 15), date(2024, 3, 1)) == [
        date(2023, 11, 30), date(2023, 12, 31), date(2024, 1, 31), date(2024, 2, 29)]
    assert month_ends(date(2024, 3, 1), date(2024, 3, 31)) == []


class TestNeon:
    TX = [{"date": "2026-04-28", "amount": -50.0}, {"date": "2026-05-02", "amount": -100.0},
          {"date": "2026-05-31", "amount": 20.0}, {"date": "2026-06-03", "amount": -40.0}]

    def test_anchor_plus_transactions_at_each_month_end(self):
        r = neon_reconstruction(self.TX, "2026-05-01", 1_000.0, None, date(2026, 8, 10))
        # The April line predates the anchor, so it is not in the balance, like the live figure.
        assert r.values == {"2026-05-31": 920.0, "2026-06-30": 880.0, "2026-07-31": 880.0}

    def test_before_the_anchor_is_a_gap(self):
        r = neon_reconstruction(self.TX, "2026-05-01", 1_000.0, None, date(2026, 8, 10))
        assert [(g.start, g.end) for g in r.gaps] == [(None, "2026-04-30")]

    def test_stops_where_the_app_started_recording(self):
        r = neon_reconstruction(self.TX, "2026-05-01", 1_000.0, "2026-07-15", date(2026, 11, 20))
        assert list(r.values) == ["2026-05-31", "2026-06-30"]

    def test_without_anchor_the_balance_starts_at_zero(self):
        r = neon_reconstruction(self.TX, None, None, None, date(2026, 7, 1))
        assert r.values == {"2026-04-30": -50.0, "2026-05-31": -130.0, "2026-06-30": -170.0}
        assert r.gaps == []

    def test_nothing_stored_means_nothing_rebuilt(self):
        r = neon_reconstruction([], None, None, None, date(2026, 7, 1))
        assert (r.values, r.gaps) == ({}, [])


class TestBinance:

    def test_forward_from_empty_then_back_from_the_snapshot_with_a_gap_between(self, repo):
        r = binance_reconstruction(binance_records(repo), BINANCE_PRICES, None, date(2022, 8, 20))
        assert r.values == {
            # Forward from the empty account: USD 500 in, 400 spent as BUSD on 0.01 BTC.
            "2022-01-31": 400.0,
            # 0.0041 BTC withdrawn with its fee; the failed ETH buy and rejected withdrawal never happened.
            "2022-02-28": 268.8,
            # March: 0.02 BTC leaves that the activity never brought in, and walking back from July
            # needs BTC before April that is not there either.
            # Back from the 2022-07-15 snapshot (LDBTC counted as BTC, RNDR is RENDER).
            "2022-04-30": 268.8,
            "2022-05-31": 221.48,
            "2022-06-30": 214.28,
            "2022-07-31": 217.16,
        }
        assert [(g.start, g.end) for g in r.gaps] == [("2022-03-01", "2022-03-31")]

    def test_an_asset_without_a_market_is_left_out_and_named(self, repo):
        r = binance_reconstruction(binance_records(repo), BINANCE_PRICES, None, date(2022, 8, 20))
        assert r.notes == ["no market price, left out: XYZ (4 months)"]

    def test_stops_where_the_app_started_recording(self, repo):
        r = binance_reconstruction(binance_records(repo), BINANCE_PRICES, "2022-06-10", date(2022, 11, 1))
        assert list(r.values)[-1] == "2022-05-31"

    def test_without_a_snapshot_the_forward_walk_ends_in_a_gap_to_the_first_sync(self, repo):
        records = binance_records(repo)
        records["spot_snapshots"] = []
        r = binance_reconstruction(records, BINANCE_PRICES, "2022-07-20", date(2022, 11, 1))
        assert list(r.values) == ["2022-01-31", "2022-02-28"]
        assert [(g.start, g.end) for g in r.gaps] == [("2022-03-01", "2022-07-19")]

    def test_complete_activity_has_no_gap(self, repo):
        records = binance_records(repo)
        r = binance_reconstruction({"fiat_deposits": records["fiat_deposits"]}, BINANCE_PRICES, None,
                                   date(2022, 3, 5))
        assert r.values == {"2022-01-31": 400.0, "2022-02-28": 400.0}
        assert r.gaps == []

    def test_a_missing_usd_rate_stops_the_rebuild(self, repo):
        prices = FakePrices(usd=BINANCE_PRICES.usd, chf={})
        with pytest.raises(PriceUnavailable):
            binance_reconstruction(binance_records(repo), prices, None, date(2022, 8, 20))

    def test_nothing_stored_means_nothing_rebuilt(self):
        r = binance_reconstruction({}, BINANCE_PRICES, None, date(2022, 8, 20))
        assert (r.values, r.gaps) == ({}, [])

    @pytest.mark.parametrize("symbol, pair", [
        ("BTCUSDT", ("BTC", "USDT")), ("ETHFDUSD", ("ETH", "FDUSD")), ("SOLBTC", ("SOL", "BTC")), ("XYZ", None),
    ])
    def test_trading_pairs_split_into_base_and_quote(self, symbol, pair):
        assert split_symbol(symbol) == pair

    def test_buying_moves_quote_into_base_minus_the_fee(self):
        deltas = reconstruct._binance_deltas("trades", {
            "symbol": "ETHBTC", "qty": "2", "quoteQty": "0.1", "commission": "0.002", "commissionAsset": "ETH",
            "isBuyer": True})
        assert deltas == {"ETH": 1.998, "BTC": -0.1}

    def test_card_sells_and_fiat_withdrawals_leave_the_account(self):
        assert reconstruct._binance_deltas("fiat_sells", {
            "cryptoCurrency": "BTC", "sourceAmount": "0.1", "status": "Completed"}) == {"BTC": -0.1}
        assert reconstruct._binance_deltas("fiat_withdrawals", {
            "fiatCurrency": "EUR", "amount": "100", "status": "Successful"}) == {"EUR": -100.0}
        assert reconstruct._binance_deltas("fiat_withdrawals", {
            "fiatCurrency": "EUR", "amount": "100", "status": "Failed"}) is None

    def test_earn_positions_count_as_their_coin_but_lido_stays_lido(self):
        assert reconstruct.binance_asset("LDSOL") == "SOL"
        assert reconstruct.binance_asset("LDO") == "LDO"
        assert reconstruct.binance_asset("FTM") == "S"


class TestWise:

    def test_replayed_per_currency_until_a_payment_the_balance_could_not_cover(self, repo):
        r = wise_reconstruction(wise_records(repo), WISE_PRICES, "2024-11-15", date(2024, 12, 1))
        # June nets out (the card order and the top-up that paid it share a day); EUR at each month's rate.
        assert r.values == {"2024-06-30": 0.0, "2024-07-31": 1_137.0, "2024-08-31": 1_147.5}
        assert [(g.start, g.end) for g in r.gaps] == [("2024-09-10", "2024-11-14")]

    def test_a_payment_split_over_balances_ends_what_is_known(self, repo):
        records = wise_records(repo)[:3]
        split = {"id": "x", "type": "CARD_PAYMENT", "status": "COMPLETED", "primaryAmount": "175.50 EUR",
                 "secondaryAmount": "MXN, EUR, CHF"}
        records.append({"occurred_at": "2024-07-20T10:00:00+00:00", "payload": json.dumps(split)})
        r = wise_reconstruction(records, WISE_PRICES, None, date(2024, 10, 1))
        assert r.values == {"2024-06-30": 0.0}
        assert [(g.start, g.end) for g in r.gaps] == [("2024-07-20", None)]

    def test_an_activity_type_the_feed_does_not_explain_ends_what_is_known(self, repo):
        odd = {"id": "x", "type": "INTEREST", "status": "COMPLETED", "primaryAmount": "<positive>+ 1 CHF</positive>"}
        records = [{"occurred_at": "2024-07-20T10:00:00+00:00", "payload": json.dumps(odd)}]
        r = wise_reconstruction(records, WISE_PRICES, None, date(2024, 10, 1))
        assert r.values == {}
        assert [(g.start, g.end) for g in r.gaps] == [("2024-07-20", None)]

    def test_a_currency_without_a_rate_stops_the_rebuild(self, repo):
        records = wise_records(repo)
        with pytest.raises(PriceUnavailable):
            wise_reconstruction(records, FakePrices(usd={}, chf={}), None, date(2024, 9, 1))

    @pytest.mark.parametrize("text, amount", [
        ("<positive>+ 1,000 CHF</positive>", (1_000.0, "CHF")),
        ("9,038 MXN", (-9_038.0, "MXN")),
        ("- 3.50 EUR", (-3.5, "EUR")),
        ("MXN, EUR, CHF", None),
        ("", None),
    ])
    def test_feed_amounts_are_read_with_their_direction(self, text, amount):
        assert wise_amount(text) == amount

    def test_nothing_stored_means_nothing_rebuilt(self):
        r = wise_reconstruction([], WISE_PRICES, None, date(2024, 9, 1))
        assert (r.values, r.gaps) == ({}, [])


class TestRebuild:

    def seed(self, repo):
        binance_records(repo)
        wise_records(repo)
        repo.set_setting("neon_anchor_date", "2022-05-01")
        repo.set_setting("neon_anchor_amount", "500")
        prices = FakePrices(usd=BINANCE_PRICES.usd,
                            chf={**BINANCE_PRICES.chf, **WISE_PRICES.chf})
        return prices

    def test_points_are_stored_as_reconstructed_next_to_recorded_snapshots(self, repo):
        prices = self.seed(repo)
        repo.upsert_snapshot("2022-06-30", "binance", 999.0, 0, 999.0, 0)
        lines = rebuild(repo, prices, today=date(2022, 8, 20))

        rows = {(s["snapshot_date"], s["source"]): s for s in repo.list_snapshots()}
        # The recorded June value stays; months before it are rebuilt, months after it are not.
        assert rows[("2022-06-30", "binance")] == {"snapshot_date": "2022-06-30", "source": "binance",
                                                   "total_chf": 999.0, "reconstructed": False}
        assert rows[("2022-05-31", "binance")]["reconstructed"] is True
        assert ("2022-07-31", "binance") not in rows
        assert rows[("2022-07-31", "neon")] == {"snapshot_date": "2022-07-31", "source": "neon",
                                                "total_chf": 500.0, "reconstructed": True}
        assert lines[1].startswith("binance: 4 months reconstructed, 2022-01-31 to 2022-05-31; gap 2022-03-01")

    def test_a_rebuild_replaces_the_previous_one(self, repo):
        prices = self.seed(repo)
        rebuild(repo, prices, today=date(2022, 8, 20))
        repo.set_setting("neon_anchor_amount", "800")
        rebuild(repo, prices, today=date(2022, 8, 20))
        neon = [s for s in repo.list_snapshots() if s["source"] == "neon"]
        assert {s["total_chf"] for s in neon} == {800.0}
        assert [g["source"] for g in repo.list_history_gaps()] == ["neon", "binance", "wise"]

    def test_a_snapshot_recorded_later_replaces_a_reconstructed_point(self, repo):
        rebuild(repo, self.seed(repo), today=date(2022, 8, 20))
        repo.upsert_snapshot("2022-05-31", "neon", 510.0, 510.0, 0, 0)
        assert repo.first_recorded_snapshot_dates() == {"neon": "2022-05-31"}
        row = next(s for s in repo.list_snapshots() if (s["snapshot_date"], s["source"]) == ("2022-05-31", "neon"))
        assert (row["total_chf"], row["reconstructed"]) == (510.0, False)

    def test_reconstructed_points_never_count_as_recorded_totals(self, repo):
        rebuild(repo, self.seed(repo), today=date(2022, 8, 20))
        assert repo.list_total_snapshots() == []

    def test_reconstructed_points_fill_their_liquidity_bucket(self, repo):
        rebuild(repo, self.seed(repo), today=date(2022, 8, 20))
        row = repo._connection.execute(
            "SELECT available_chf, invested_chf, locked_chf FROM nw_snapshots WHERE source = 'binance' "
            "ORDER BY snapshot_date LIMIT 1"
        ).fetchone()
        assert tuple(row) == (0.0, 400.0, 0.0)


class TestCurve:

    def test_a_month_adds_reconstructed_sources_its_recorded_snapshot_did_not_cover(self, repo):
        repo.upsert_snapshot("2026-10-25", "neon", 1_800.0, 1_800.0, 0, 0)
        repo.upsert_snapshot("2026-10-25", "total", 1_800.0, 1_800.0, 0, 0)
        repo.replace_reconstruction([
            point("2026-09-30", "neon", 1_700.0), point("2026-09-30", "binance", 400.0),
            point("2026-10-31", "binance", 550.0),
        ], [])
        history = monthly_history(repo, 3_000.0, date(2026, 11, 20))
        assert history["months"] == [
            {"month": "2026-09", "date": "2026-09-30", "total_chf": 2_100.0, "reconstructed": True, "missing": []},
            {"month": "2026-10", "date": "2026-10-31", "total_chf": 2_350.0, "reconstructed": True, "missing": []},
            {"month": "2026-11", "date": "2026-11-20", "total_chf": 3_000.0, "reconstructed": False, "missing": []},
        ]
        assert history["change_since_last_month"] == {"amount_chf": 650.0, "since": "2026-10-31", "pct": 27.66}

    def test_a_recorded_total_with_no_source_rows_takes_every_reconstructed_source(self, repo):
        repo.upsert_snapshot("2026-06-23", "total", 0.0, 0, 0, 0)
        repo.replace_reconstruction([point("2026-06-30", "neon", 1_700.0)], [])
        first = monthly_history(repo, 3_000.0, date(2026, 11, 20))["months"][0]
        assert first == {"month": "2026-06", "date": "2026-06-30", "total_chf": 1_700.0,
                         "reconstructed": True, "missing": []}

    def test_a_month_no_source_can_tell_is_a_hole_and_partial_months_name_what_is_missing(self, repo):
        repo.replace_reconstruction(
            [point("2022-01-31", "binance", 400.0), point("2022-04-30", "binance", 300.0)],
            [gap("binance", "2022-02-10", "2022-04-02"), gap("neon", None, "2022-04-30")],
        )
        history = monthly_history(repo, 3_000.0, date(2022, 5, 20))
        assert history["months"] == [
            {"month": "2022-01", "date": "2022-01-31", "total_chf": 400.0, "reconstructed": True, "missing": ["neon"]},
            {"month": "2022-02", "date": "2022-02-28", "total_chf": None, "reconstructed": False,
             "missing": ["binance", "neon"]},
            {"month": "2022-03", "date": "2022-03-31", "total_chf": None, "reconstructed": False,
             "missing": ["binance", "neon"]},
            {"month": "2022-04", "date": "2022-04-30", "total_chf": 300.0, "reconstructed": True, "missing": ["neon"]},
            {"month": "2022-05", "date": "2022-05-20", "total_chf": 3_000.0, "reconstructed": False, "missing": []},
        ]
        assert history["change_since_last_month"]["since"] == "2022-04-30"

    def test_the_change_since_last_month_skips_a_hole(self, repo):
        repo.replace_reconstruction([point("2022-03-31", "binance", 300.0)], [gap("binance", "2022-04-01", None)])
        history = monthly_history(repo, 1_000.0, date(2022, 5, 20))
        assert [m["total_chf"] for m in history["months"]] == [300.0, None, 1_000.0]
        assert history["change_since_last_month"]["since"] == "2022-03-31"


def point(day: str, source: str, value: float) -> dict:
    return {"date": day, "source": source, "total_chf": value, "available_chf": value,
            "invested_chf": 0.0, "locked_chf": 0.0}


def gap(source: str, start, end) -> dict:
    return {"source": source, "start": start, "end": end, "reason": f"{source} unknown"}


class TestDashboard:

    @pytest.fixture
    def client(self, monkeypatch, tmp_path):
        monkeypatch.setattr("backend.api.load_config",
                            lambda: AppConfig(project_root=tmp_path, database_file=tmp_path / "api.db"))
        repo = SQLiteRepository(tmp_path / "api.db")
        repo.initialise_schema()
        app.state.repository = repo
        with TestClient(app) as c:
            yield c

    def test_the_curve_starts_at_the_earliest_reconstructed_month_and_lists_gaps(self, client):
        repo = app.state.repository
        repo.replace_reconstruction([point("2022-01-31", "binance", 400.0)], [gap("neon", None, "2026-04-30")])
        repo.put_fx_rate("CHF", "USD", "2022-03-15", 1.25)
        with freeze_time("2022-03-15 08:00:00"):
            d = client.get("/dashboard?currency=USD").json()
        assert [(p["month"], p["total_chf"]) for p in d["history"]] == [
            ("2022-01", 500.0), ("2022-02", None), ("2022-03", 0.0)]
        assert d["history"][0]["reconstructed"] is True
        assert d["history_gaps"] == [{"source": "neon", "label": "Neon", "start": None, "end": "2026-04-30",
                                      "reason": "neon unknown"}]


class TestMarketPrices:

    @staticmethod
    def kline(month: str, close: float, closed: bool = True) -> list:
        opened = int(datetime.fromisoformat(f"{month}-01T00:00:00+00:00").timestamp() * 1000)
        closes_at = opened + 27 * 86_400_000 if closed else 4_102_444_800_000
        return [opened, "0", "0", "0", str(close), "0", closes_at]

    def test_month_closes_come_from_the_usdt_pair_and_its_old_ticker(self, repo):
        calls = []

        def klines(symbol):
            calls.append(symbol)
            return {"RENDERUSDT": [self.kline("2024-08", 5.0), self.kline("2024-09", 6.0, closed=False)],
                    "RNDRUSDT": [self.kline("2024-06", 9.0), self.kline("2024-08", 7.0)]}.get(symbol, [])

        prices = MarketPrices(repo, klines=klines, fx_series=lambda *a: {},
                              now=datetime(2024, 9, 10, tzinfo=timezone.utc))
        assert prices.usd_price("RENDER", date(2024, 8, 31)) == 5.0
        assert prices.usd_price("RENDER", date(2024, 6, 30)) == 9.0
        assert prices.usd_price("RENDER", date(2024, 9, 30)) is None  # the month is still open
        assert prices.usd_price("USDC", date(2024, 9, 30)) == 1.0
        assert calls == ["RENDERUSDT", "RNDRUSDT"]

    def test_month_closes_are_cached_across_runs(self, repo):
        first = MarketPrices(repo, klines=lambda s: [self.kline("2023-02", 21_000.0)], fx_series=lambda *a: {},
                             now=datetime(2024, 1, 1, tzinfo=timezone.utc))
        assert first.usd_price("BTC", date(2023, 2, 28)) == 21_000.0
        second = MarketPrices(repo, klines=MagicMock(side_effect=AssertionError("fetched again")),
                              fx_series=lambda *a: {}, now=datetime(2024, 1, 1, tzinfo=timezone.utc))
        assert second.usd_price("BTC", date(2023, 2, 28)) == 21_000.0

    def test_fx_uses_the_last_rate_published_by_the_day_and_caches_it(self, repo):
        series = MagicMock(return_value={"2024-03-28": 0.9, "2024-04-02": 0.91})
        prices = MarketPrices(repo, klines=lambda s: [], fx_series=series, now=datetime(2024, 5, 1, tzinfo=timezone.utc))
        assert prices.chf_rate("USD", date(2024, 3, 31)) == 0.9  # Easter weekend: Thursday's rate
        assert prices.chf_rate("USD", date(2024, 2, 29)) is None
        assert prices.chf_rate("CHF", date(2024, 2, 29)) == 1.0
        assert series.call_count == 1
        assert repo.get_cached_fx_rate("USD", "CHF", "2024-03-31") == 0.9

    def test_a_coin_binance_does_not_list_has_no_price(self, repo):
        response = requests.Response()
        response.status_code = 400
        with patch.object(reconstruct.binance_api, "_public_request",
                          side_effect=requests.HTTPError(response=response)):
            assert MarketPrices._fetch_klines("XYZUSDT") == []

    def test_a_network_failure_is_not_taken_for_a_missing_coin(self, repo):
        with patch.object(reconstruct.binance_api, "_public_request", side_effect=requests.ConnectionError("down")):
            with pytest.raises(requests.ConnectionError):
                MarketPrices._fetch_klines("BTCUSDT")


class TestFrankfurterSeries:

    def test_daily_rates_between_two_days(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {"rates": {"2024-01-02": {"CHF": 0.85}, "2024-01-03": {"CHF": 0.86}}}
        with patch("backend.fx.service.requests.get", return_value=response) as get:
            rates = FrankfurterClient().fetch_series("USD", "CHF", "2024-01-01", "2024-01-03")
        assert rates == {"2024-01-02": 0.85, "2024-01-03": 0.86}
        assert get.call_args.args[0].endswith("/2024-01-01..2024-01-03")

    def test_a_currency_the_ecb_does_not_quote_has_no_rates(self):
        with patch("backend.fx.service.requests.get", return_value=MagicMock(status_code=404)):
            assert FrankfurterClient().fetch_series("MAD", "CHF", "2024-01-01", "2024-01-03") == {}


class TestCommand:

    def test_reconstruct_only_rebuilds_without_backfilling(self, monkeypatch, capsys, tmp_path):
        from backend.history.__main__ import main

        monkeypatch.setenv("FINANCE_DASH_DB_FILE", str(tmp_path / "x.db"))
        monkeypatch.setenv("BINANCE_API_KEY", "k")
        monkeypatch.setenv("BINANCE_API_SECRET", "s")
        with patch("backend.history.__main__.backfill_binance") as backfill:
            assert main(["--reconstruct-only"]) == 0
        backfill.assert_not_called()
        out = capsys.readouterr().out
        assert "reconstructed neon: nothing reconstructed" in out

    def test_a_failed_rebuild_keeps_the_previous_one_and_fails_the_run(self, monkeypatch, capsys, tmp_path):
        from backend.history.__main__ import main

        monkeypatch.setenv("FINANCE_DASH_DB_FILE", str(tmp_path / "x.db"))
        with patch("backend.history.__main__.rebuild", side_effect=PriceUnavailable("no USD/CHF rate")):
            assert main(["--reconstruct-only"]) == 1
        assert "the previous reconstruction is kept" in capsys.readouterr().out


def test_an_existing_snapshot_table_gains_the_reconstructed_flag(tmp_path):
    import sqlite3

    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE nw_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, snapshot_date TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'total', total_chf REAL NOT NULL, available_chf REAL NOT NULL,
            invested_chf REAL NOT NULL, locked_chf REAL NOT NULL, created_at TEXT NOT NULL,
            UNIQUE(snapshot_date, source));
        INSERT INTO nw_snapshots (snapshot_date, source, total_chf, available_chf, invested_chf, locked_chf, created_at)
            VALUES ('2026-06-23', 'total', 0, 0, 0, 0, '2026-06-23');
    """)
    conn.commit()
    conn.close()

    migrated = SQLiteRepository(db)
    migrated.initialise_schema()
    assert migrated.list_snapshots() == [
        {"snapshot_date": "2026-06-23", "source": "total", "total_chf": 0.0, "reconstructed": False}]
