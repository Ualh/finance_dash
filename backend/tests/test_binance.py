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


@pytest.fixture
def binance_keys(monkeypatch):
    monkeypatch.setenv("BINANCE_API_KEY", "test_key")
    monkeypatch.setenv("BINANCE_API_SECRET", "test_secret")


def _make_repo(db_path):
    from backend.database import SQLiteRepository

    repo = SQLiteRepository(db_path)
    repo.initialise_schema()
    return repo


def seed_holding(repo, source, source_type, asset_class, value_chf, label=None):
    repo.upsert_holding(source, source_type, asset_class, value_chf, label)


BTC_USDT = 60_000.0
USD_CHF = 0.90

# Shape of GET /sapi/v1/asset/wallet/balance (quoteAsset=BTC), per the official docs.
WALLETS = [
    {"activate": True, "balance": "0.01", "walletName": "Spot"},
    {"activate": True, "balance": "0.02", "walletName": "Funding"},
    {"activate": True, "balance": "0.05", "walletName": "Earn"},
    {"activate": True, "balance": "0", "walletName": "Cross Margin"},
]


def fake_signed(wallets):
    def _fake(endpoint, params=None, base_url="https://api.binance.com"):
        if endpoint == "/sapi/v1/asset/wallet/balance":
            assert params == {"quoteAsset": "BTC"}
            return wallets
        raise AssertionError(f"Unexpected signed endpoint: {endpoint}")
    return _fake


def fake_public(endpoint, params=None, base_url="https://api.binance.com"):
    assert endpoint == "/api/v3/ticker/price" and params == {"symbol": "BTCUSDT"}
    return {"symbol": "BTCUSDT", "price": str(BTC_USDT)}


class MockFXClient:
    def fetch_rate(self, base, quote, valuation_date):
        return USD_CHF


def chf(btc: float) -> float:
    return round(btc * BTC_USDT * USD_CHF, 2)


class TestBinanceAdapter:

    def test_reads_spot_funding_and_earn_wallets(self, repo, binance_keys):
        with (
            patch("backend.sources.binance._signed_request", side_effect=fake_signed(WALLETS)),
            patch("backend.sources.binance._public_request", side_effect=fake_public),
            freeze_time("2026-06-16 12:00:00"),
        ):
            from backend.sources.binance import sync_binance

            assert sync_binance(repo, fx_client=MockFXClient()) == 3

        by_label = {h["label"]: h for h in repo.list_holdings()}
        assert set(by_label) == {"Binance Spot", "Binance Funding", "Binance Earn"}
        assert by_label["Binance Spot"]["value_chf"] == chf(0.01)
        assert by_label["Binance Funding"]["value_chf"] == chf(0.02)
        assert by_label["Binance Earn"]["value_chf"] == chf(0.05)
        assert by_label["Binance Earn"]["native_currency"] == "BTC"
        assert all(h["source"] == "binance" and h["source_type"] == "api" and h["asset_class"] == "crypto"
                   for h in by_label.values())

    def test_replaces_previous_lines_instead_of_keeping_stale_ones(self, repo, binance_keys):
        # Legacy per-asset line from the old Spot-only adapter, and a wallet since emptied.
        seed_holding(repo, "binance", "api", "crypto", 1000.0, "Binance BTC")
        seed_holding(repo, "binance", "api", "crypto", 500.0, "Binance Funding")
        seed_holding(repo, "finpension", "manual", "pension", 50_000.0)

        with (
            patch("backend.sources.binance._signed_request", side_effect=fake_signed(WALLETS[:1])),
            patch("backend.sources.binance._public_request", side_effect=fake_public),
            freeze_time("2026-06-16 12:00:00"),
        ):
            from backend.sources.binance import sync_binance

            sync_binance(repo, fx_client=MockFXClient())

        labels = sorted(h["label"] for h in repo.list_holdings())
        assert labels == ["", "Binance Spot"]  # finpension untouched, Binance replaced

    def test_no_balances_clears_binance(self, repo, binance_keys):
        seed_holding(repo, "binance", "api", "crypto", 1000.0, "Binance Spot")
        with patch("backend.sources.binance._signed_request", side_effect=fake_signed([])):
            from backend.sources.binance import sync_binance

            assert sync_binance(repo) == 0
        assert repo.list_holdings() == []

    def test_signature_covers_the_exact_query_sent(self, binance_keys):
        import hashlib
        import hmac

        captured = {}

        class Resp:
            def raise_for_status(self):
                pass

            def json(self):
                return []

        def fake_get(url, headers=None, timeout=None, **kwargs):
            captured["url"], captured["headers"] = url, headers
            return Resp()

        with patch("backend.sources.binance.requests.get", side_effect=fake_get), freeze_time("2026-06-16 12:00:00"):
            from backend.sources.binance import _signed_request

            _signed_request("/sapi/v1/asset/wallet/balance", {"quoteAsset": "BTC"})

        query, signature = captured["url"].split("?", 1)[1].rsplit("&signature=", 1)
        assert query == "quoteAsset=BTC&timestamp=1781611200000"
        assert signature == hmac.new(b"test_secret", query.encode(), hashlib.sha256).hexdigest()
        assert captured["headers"] == {"X-MBX-APIKEY": "test_key"}


class TestBinanceSyncAll:

    def test_first_sync_on_empty_database_calls_binance(self, client, binance_keys):
        """Regression: sync only ran sources that already had a holdings row, so Binance never started."""
        repo = app.state.repository
        assert repo.list_holdings() == []

        with (
            patch("backend.sources.binance._signed_request", side_effect=fake_signed(WALLETS)),
            patch("backend.sources.binance._public_request", side_effect=fake_public),
            patch("backend.fx.service.FrankfurterClient", return_value=MockFXClient()),
            freeze_time("2026-06-16 12:00:00"),
        ):
            resp = client.post("/sync/all")

        assert resp.status_code == 200
        assert resp.json() == {"ok": ["binance"], "error": []}
        total = sum(h["value_chf"] for h in repo.list_holdings())
        assert total == pytest.approx(chf(0.01) + chf(0.02) + chf(0.05))
        assert repo.get_last_sync_log("binance")["status"] == "ok"

    def test_without_keys_binance_is_not_synced(self, client):
        repo = app.state.repository
        seed_holding(repo, "binance", "api", "crypto", 1000.0, "Binance Spot")
        with patch("backend.sources.binance._signed_request") as signed:
            resp = client.post("/sync/all")
        assert resp.json() == {"ok": [], "error": []}
        signed.assert_not_called()

    def test_binance_error_is_logged(self, client, binance_keys):
        repo = app.state.repository

        def unreachable(endpoint, params=None, base_url="https://api.binance.com"):
            raise Exception("Binance API unreachable")

        with patch("backend.sources.binance._signed_request", side_effect=unreachable), freeze_time("2026-06-16 12:00:00"):
            resp = client.post("/sync/all")

        assert resp.json() == {"ok": [], "error": ["binance"]}
        log = repo.get_last_sync_log("binance")
        assert log["status"] == "error"
        assert "Binance API unreachable" in log["message"]
