from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from freezegun import freeze_time

from backend.api import app
from backend.database import SQLiteRepository
from backend.fx import FrankfurterClient, convert, get_fx_rate


@pytest.fixture
def repo():
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
    repo = SQLiteRepository(db_path)
    repo.initialise_schema()
    return repo


def seed_holding(repo, source, source_type, asset_class, value_chf, label=None):
    repo.upsert_holding(source, source_type, asset_class, value_chf, label)


class MockFrankfurterClient:
    def __init__(self, return_rate=0.92):
        self.return_rate = return_rate
        self.call_count = 0

    def fetch_rate(self, base, quote, valuation_date):
        self.call_count += 1
        return self.return_rate


class TestFxRate:

    def test_cache_hit_returns_without_fetching(self, repo):
        repo.put_fx_rate("CHF", "USD", "2026-06-16", 0.92)
        mock = MockFrankfurterClient(return_rate=0.99)

        with freeze_time("2026-06-16 12:00:00"):
            result = get_fx_rate(repo, "CHF", "USD", client=mock)

        assert result["rate"] == 0.92
        assert result["stale"] is False
        assert result["source"] == "cache"
        assert mock.call_count == 0

    def test_cache_miss_fetches_and_caches(self, repo):
        mock = MockFrankfurterClient(return_rate=0.85)

        with freeze_time("2026-06-16 12:00:00"):
            result = get_fx_rate(repo, "CHF", "USD", client=mock)

        assert result["rate"] == 0.85
        assert result["stale"] is False
        assert result["source"] == "frankfurter"
        assert mock.call_count == 1

        cached = repo.get_cached_fx_rate("CHF", "USD", "2026-06-16")
        assert cached == 0.85

    def test_stale_fallback_when_frankfurter_fails(self, repo):
        repo.put_fx_rate("CHF", "USD", "2026-06-15", 0.91)

        class FailingClient:
            def fetch_rate(self, base, quote, valuation_date):
                return None

        with freeze_time("2026-06-16 12:00:00"):
            result = get_fx_rate(repo, "CHF", "USD", client=FailingClient())

        assert result["rate"] == 0.91
        assert result["stale"] is True
        assert result["source"] == "stale"

    def test_fallback_to_1_when_no_cache_and_frankfurter_fails(self, repo):
        class FailingClient:
            def fetch_rate(self, base, quote, valuation_date):
                return None

        with freeze_time("2026-06-16 12:00:00"):
            result = get_fx_rate(repo, "CHF", "USD", client=FailingClient())

        assert result["rate"] == 1.0
        assert result["stale"] is True
        assert result["source"] == "fallback"

    def test_convert_chf_passthrough(self, repo):
        result = convert(repo, 1000.0, "CHF")
        assert result["amount"] == 1000.0
        assert result["rate"] == 1.0
        assert result["stale"] is False
        assert result["currency"] == "CHF"

    def test_convert_usd_uses_rate(self, repo):
        repo.put_fx_rate("CHF", "USD", "2026-06-16", 1.10)

        with freeze_time("2026-06-16 12:00:00"):
            result = convert(repo, 100_000.0, "USD")

        assert result["amount"] == 110_000.0
        assert result["rate"] == 1.10
        assert result["stale"] is False
        assert result["currency"] == "USD"


class TestDashboardCurrency:

    def test_dashboard_defaults_to_chf(self, client):
        repo = app.state.repository
        seed_holding(repo, "finpension", "api", "pension", 100_000)

        resp = client.get("/dashboard")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_chf"] == 100_000.0
        assert "_fx" not in data

    def test_dashboard_with_usd_converts(self, client):
        repo = app.state.repository
        seed_holding(repo, "finpension", "api", "pension", 100_000)
        repo.put_fx_rate("CHF", "USD", "2026-06-16", 1.10)

        with freeze_time("2026-06-16 12:00:00"):
            resp = client.get("/dashboard?currency=USD")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_chf"] == 110_000.0
        assert data["_fx"]["rate"] == 1.10
        assert data["_fx"]["stale"] is False
        assert data["_fx"]["currency"] == "USD"

    def test_dashboard_converts_buckets_and_sources(self, client):
        repo = app.state.repository
        seed_holding(repo, "finpension", "api", "pension", 80_000)
        seed_holding(repo, "postfinance", "api", "cash", 20_000)
        repo.put_fx_rate("CHF", "USD", "2026-06-16", 2.0)

        with freeze_time("2026-06-16 12:00:00"):
            resp = client.get("/dashboard?currency=USD")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_chf"] == 200_000.0
        assert data["buckets"]["locked"] == 160_000.0
        assert data["buckets"]["available"] == 40_000.0
        assert data["sources"]["finpension"]["total_chf"] == 160_000.0
        assert data["sources"]["postfinance"]["total_chf"] == 40_000.0


class TestSettings:

    def test_get_setting_returns_default_when_missing(self, client):
        resp = client.get("/settings/display_currency")
        assert resp.status_code == 200
        data = resp.json()
        assert data["key"] == "display_currency"
        assert data["value"] is None

    def test_put_and_get_setting(self, client):
        resp = client.put("/settings/display_currency", json={"value": "USD"})
        assert resp.status_code == 200
        assert resp.json()["value"] == "USD"

        resp = client.get("/settings/display_currency")
        assert resp.status_code == 200
        assert resp.json()["value"] == "USD"
