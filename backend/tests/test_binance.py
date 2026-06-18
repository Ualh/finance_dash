from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from freezegun import freeze_time

from backend.api import app


@pytest.fixture
def repo():
    from backend.database import SQLiteRepository

    with TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        repo = SQLiteRepository(db_path)
        repo.initialise_schema()
        yield repo


@pytest.fixture
def client(monkeypatch):
    with TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        monkeypatch.setenv("FINANCE_DASH_DB_FILE", str(db_path))
        app.state.repository = _make_repo(db_path)
        with TestClient(app) as c:
            yield c


def _make_repo(db_path):
    from backend.database import SQLiteRepository

    repo = SQLiteRepository(db_path)
    repo.initialise_schema()
    return repo


def seed_holding(repo, source, source_type, asset_class, value_chf, label=None):
    repo.upsert_holding(source, source_type, asset_class, value_chf, label)


def mock_binance_account_response(balances: list[dict]) -> dict:
    return {"canTrade": True, "balances": balances}


def mock_binance_ticker_price(symbol: str, price: float) -> dict:
    return {"symbol": symbol, "price": str(price)}


MOCK_ACCOUNT = mock_binance_account_response([
    {"asset": "BTC", "free": "0.5", "locked": "0.0"},
    {"asset": "ETH", "free": "10.0", "locked": "0.0"},
    {"asset": "USDT", "free": "2000.0", "locked": "0.0"},
    {"asset": "ADA", "free": "5000.0", "locked": "0.0"},
    {"asset": "SOL", "free": "0.0", "locked": "0.0"},
])


class TestBinanceAdapter:

    def test_sync_binance_creates_holdings(self, repo):
        btc_price = 60_000.0
        eth_price = 3_000.0
        ada_price = 0.35
        usd_to_chf = 0.90

        def fake_signed_request(endpoint, params=None, base_url="https://api.binance.com"):
            if endpoint == "/api/v3/account":
                return MOCK_ACCOUNT
            if endpoint == "/api/v3/ticker/price":
                sym = (params or {}).get("symbol", "")
                prices = {
                    "BTCUSDT": btc_price,
                    "ETHUSDT": eth_price,
                    "ADAUSDT": ada_price,
                }
                p = prices.get(sym)
                if p is not None:
                    return {"symbol": sym, "price": str(p)}
                raise Exception(f"Unknown symbol: {sym}")
            raise Exception(f"Unexpected endpoint: {endpoint}")

        class MockFXClient:
            def fetch_rate(self, base, quote, valuation_date):
                return usd_to_chf

        with (
            patch("backend.sources.binance.BINANCE_API_KEY", "test_key"),
            patch("backend.sources.binance.BINANCE_API_SECRET", "test_secret"),
            patch("backend.sources.binance._signed_request", side_effect=fake_signed_request),
            freeze_time("2026-06-16 12:00:00"),
        ):
            from backend.sources.binance import sync_binance

            result = sync_binance(repo, fx_client=MockFXClient())

        assert result == 4

        holdings = repo.list_holdings()
        assert len(holdings) == 4

        holdings_by_label = {h["label"]: h for h in holdings}

        btc_holding = holdings_by_label["Binance BTC"]
        expected_btc_value = round(0.5 * btc_price * usd_to_chf, 2)
        assert btc_holding["value_chf"] == expected_btc_value
        assert btc_holding["source"] == "binance"
        assert btc_holding["source_type"] == "api"
        assert btc_holding["asset_class"] == "crypto"

        eth_holding = holdings_by_label["Binance ETH"]
        expected_eth_value = round(10.0 * eth_price * usd_to_chf, 2)
        assert eth_holding["value_chf"] == expected_eth_value

        usdt_holding = holdings_by_label["Binance USDT"]
        expected_usdt_value = round(2000.0 * 1.0 * usd_to_chf, 2)
        assert usdt_holding["value_chf"] == expected_usdt_value

        ada_holding = holdings_by_label["Binance ADA"]
        expected_ada_value = round(5000.0 * ada_price * usd_to_chf, 2)
        assert ada_holding["value_chf"] == expected_ada_value

    def test_sync_binance_upserts_existing_holdings(self, repo):
        seed_holding(repo, "binance", "api", "crypto", 1000.0, "Binance BTC")

        def fake_signed_request(endpoint, params=None, base_url="https://api.binance.com"):
            if endpoint == "/api/v3/account":
                return mock_binance_account_response([
                    {"asset": "BTC", "free": "0.5", "locked": "0.0"},
                ])
            if endpoint == "/api/v3/ticker/price":
                return {"symbol": "BTCUSDT", "price": "60000"}
            raise Exception(f"Unexpected endpoint: {endpoint}")

        class MockFXClient:
            def fetch_rate(self, base, quote, valuation_date):
                return 0.90

        with (
            patch("backend.sources.binance.BINANCE_API_KEY", "test_key"),
            patch("backend.sources.binance.BINANCE_API_SECRET", "test_secret"),
            patch("backend.sources.binance._signed_request", side_effect=fake_signed_request),
            freeze_time("2026-06-16 12:00:00"),
        ):
            from backend.sources.binance import sync_binance

            sync_binance(repo, fx_client=MockFXClient())

        holdings = repo.list_holdings()
        assert len(holdings) == 1
        assert holdings[0]["value_chf"] == round(0.5 * 60000 * 0.90, 2)

    def test_sync_binance_no_balances(self, repo):
        def fake_signed_request(endpoint, params=None, base_url="https://api.binance.com"):
            if endpoint == "/api/v3/account":
                return mock_binance_account_response([])
            raise Exception(f"Unexpected endpoint: {endpoint}")

        with (
            patch("backend.sources.binance.BINANCE_API_KEY", "test_key"),
            patch("backend.sources.binance.BINANCE_API_SECRET", "test_secret"),
            patch("backend.sources.binance._signed_request", side_effect=fake_signed_request),
        ):
            from backend.sources.binance import sync_binance

            result = sync_binance(repo)

        assert result == 0
        assert repo.list_holdings() == []

    def test_sync_binance_handles_price_failure_gracefully(self, repo):
        def fake_signed_request(endpoint, params=None, base_url="https://api.binance.com"):
            if endpoint == "/api/v3/account":
                return mock_binance_account_response([
                    {"asset": "BTC", "free": "0.5", "locked": "0.0"},
                    {"asset": "UNKNOWN_ASSET", "free": "100.0", "locked": "0.0"},
                ])
            if endpoint == "/api/v3/ticker/price":
                sym = (params or {}).get("symbol", "")
                if sym == "BTCUSDT":
                    return {"symbol": "BTCUSDT", "price": "60000"}
                raise Exception(f"Unknown symbol: {sym}")
            raise Exception(f"Unexpected endpoint: {endpoint}")

        class MockFXClient:
            def fetch_rate(self, base, quote, valuation_date):
                return 0.90

        with (
            patch("backend.sources.binance.BINANCE_API_KEY", "test_key"),
            patch("backend.sources.binance.BINANCE_API_SECRET", "test_secret"),
            patch("backend.sources.binance._signed_request", side_effect=fake_signed_request),
            freeze_time("2026-06-16 12:00:00"),
        ):
            from backend.sources.binance import sync_binance

            result = sync_binance(repo, fx_client=MockFXClient())

        assert result == 1
        holdings = repo.list_holdings()
        assert len(holdings) == 1
        assert holdings[0]["label"] == "Binance BTC"

    def test_sync_binance_integrated_via_sync_all(self, client):
        repo = app.state.repository
        seed_holding(repo, "binance", "api", "crypto", 1000.0, "Binance BTC")

        def fake_signed_request(endpoint, params=None, base_url="https://api.binance.com"):
            if endpoint == "/api/v3/account":
                return mock_binance_account_response([
                    {"asset": "BTC", "free": "0.5", "locked": "0.0"},
                ])
            if endpoint == "/api/v3/ticker/price":
                return {"symbol": "BTCUSDT", "price": "60000"}
            raise Exception(f"Unexpected endpoint: {endpoint}")

        class MockFXClient:
            def fetch_rate(self, base, quote, valuation_date):
                return 0.90

        with (
            patch("backend.sources.binance.BINANCE_API_KEY", "test_key"),
            patch("backend.sources.binance.BINANCE_API_SECRET", "test_secret"),
            patch("backend.sources.binance._signed_request", side_effect=fake_signed_request),
            patch("backend.fx.service.FrankfurterClient", return_value=MockFXClient()),
            freeze_time("2026-06-16 12:00:00"),
        ):
            resp = client.post("/sync/all")

        assert resp.status_code == 200
        data = resp.json()
        assert "binance" in data["ok"]
        assert data["error"] == []

        holdings = repo.list_holdings()
        assert len(holdings) == 1
        assert holdings[0]["value_chf"] == round(0.5 * 60000 * 0.90, 2)

    def test_binance_error_does_not_block_other_sources(self, client):
        repo = app.state.repository
        seed_holding(repo, "binance", "api", "crypto", 1000.0, "Binance BTC")
        seed_holding(repo, "finpension", "api", "pension", 50_000.0)

        def fake_signed_request(endpoint, params=None, base_url="https://api.binance.com"):
            raise Exception("Binance API unreachable")

        with (
            patch("backend.sources.binance.BINANCE_API_KEY", "test_key"),
            patch("backend.sources.binance.BINANCE_API_SECRET", "test_secret"),
            patch("backend.sources.binance._signed_request", side_effect=fake_signed_request),
            freeze_time("2026-06-16 12:00:00"),
        ):
            resp = client.post("/sync/all")

        assert resp.status_code == 200
        data = resp.json()
        assert "finpension" in data["ok"]
        assert "binance" in data["error"]

        binance_log = repo.get_last_sync_log("binance")
        assert binance_log["status"] == "error"
        assert "Binance API unreachable" in binance_log["message"]

        finpension_log = repo.get_last_sync_log("finpension")
        assert finpension_log["status"] == "ok"
