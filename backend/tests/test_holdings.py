from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient
from freezegun import freeze_time

from backend.api import app
from backend.config import AppConfig
from backend.database import SQLiteRepository
from backend.fx import convert_to_chf


@pytest.fixture
def tmp_home(monkeypatch):
    with TemporaryDirectory() as tmp:
        monkeypatch.setattr(
            "backend.api.load_config",
            lambda: AppConfig(project_root=Path(tmp), database_file=Path(tmp) / "test.db"),
        )
        repo = SQLiteRepository(Path(tmp) / "test.db")
        repo.initialise_schema()
        app.state.repository = repo
        yield Path(tmp)


@pytest.fixture
def client(tmp_home):
    with TestClient(app) as c:
        yield c


class TestConvertToChf:

    def test_chf_passthrough(self):
        with TemporaryDirectory() as tmp:
            repo = SQLiteRepository(Path(tmp) / "t.db")
            repo.initialise_schema()
            result = convert_to_chf(repo, 1000.0, "CHF")
            assert result["amount_chf"] == 1000.0
            assert result["rate"] == 1.0
            assert result["stale"] is False

    def test_usd_uses_rate(self):
        with TemporaryDirectory() as tmp:
            repo = SQLiteRepository(Path(tmp) / "t.db")
            repo.initialise_schema()
            repo.put_fx_rate("USD", "CHF", "2026-06-16", 0.90)
            with freeze_time("2026-06-16 12:00:00"):
                result = convert_to_chf(repo, 1000.0, "USD")
            assert result["amount_chf"] == 900.0
            assert result["rate"] == 0.90
            assert result["stale"] is False


class TestAddHoldingEndpoint:

    def test_add_chf_holding(self, client):
        resp = client.post(
            "/holdings",
            json={"label": "UBS Equity Fund", "asset_class": "etf", "amount": 12000, "currency": "CHF"},
        )
        assert resp.status_code == 200
        h = resp.json()["holding"]
        assert h["label"] == "UBS Equity Fund"
        assert h["asset_class"] == "etf"
        assert h["source_type"] == "manual"
        assert h["value_chf"] == 12000.0
        assert h["native_amount"] == 12000.0
        assert h["native_currency"] == "CHF"

    def test_add_usd_holding_converts(self, client):
        app.state.repository.put_fx_rate("USD", "CHF", "2026-06-16", 0.90)
        with freeze_time("2026-06-16 12:00:00"):
            resp = client.post(
                "/holdings",
                json={"label": "IBKR", "asset_class": "stock", "amount": 1000, "currency": "USD"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["holding"]["value_chf"] == 900.0
        assert body["holding"]["native_amount"] == 1000.0
        assert body["holding"]["native_currency"] == "USD"
        assert body["fx"]["rate"] == 0.90

    def test_default_currency_is_chf(self, client):
        resp = client.post("/holdings", json={"label": "Hard wallet", "asset_class": "crypto", "amount": 500})
        assert resp.status_code == 200
        assert resp.json()["holding"]["native_currency"] == "CHF"

    def test_invalid_asset_class_rejected(self, client):
        resp = client.post(
            "/holdings",
            json={"label": "Whatever", "asset_class": "banana", "amount": 100, "currency": "CHF"},
        )
        assert resp.status_code == 400

    def test_blank_label_rejected(self, client):
        resp = client.post(
            "/holdings",
            json={"label": "   ", "asset_class": "cash", "amount": 100, "currency": "CHF"},
        )
        assert resp.status_code == 400

    def test_re_adding_same_label_updates_in_place(self, client):
        client.post("/holdings", json={"label": "Pillar 3a", "asset_class": "pension", "amount": 1000, "currency": "CHF"})
        client.post("/holdings", json={"label": "Pillar 3a", "asset_class": "pension", "amount": 2500, "currency": "CHF"})
        holdings = [h for h in app.state.repository.list_holdings() if h["label"] == "Pillar 3a"]
        assert len(holdings) == 1
        assert holdings[0]["value_chf"] == 2500.0

    def test_added_holding_appears_in_dashboard_bucket(self, client):
        client.post("/holdings", json={"label": "UBS Fund", "asset_class": "etf", "amount": 5000, "currency": "CHF"})
        client.post("/holdings", json={"label": "Frankly 3a", "asset_class": "pension", "amount": 3000, "currency": "CHF"})
        data = client.get("/dashboard").json()
        assert data["total_chf"] == 8000.0
        assert data["buckets"]["invested"] == 5000.0
        assert data["buckets"]["locked"] == 3000.0


class TestAnchorSettingRegression:
    """Setting the Neon anchor via PUT /settings must not 500 (was AttributeError)."""

    def test_set_anchor_amount_does_not_500(self, client):
        resp = client.put("/settings/neon_anchor_amount", json={"value": "5000"})
        assert resp.status_code == 200

    def test_set_anchor_recomputes_neon_holding(self, client):
        client.put("/settings/neon_anchor_date", json={"value": "2026-05-01"})
        client.put("/settings/neon_anchor_amount", json={"value": "5000"})
        neon = [h for h in app.state.repository.list_holdings() if h["source"] == "neon"]
        assert len(neon) == 1
        # No transactions yet, so balance == anchor amount.
        assert neon[0]["value_chf"] == 5000.0
