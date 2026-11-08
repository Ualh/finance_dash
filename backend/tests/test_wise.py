from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from backend.database import SQLiteRepository
from backend.sources import wise

@pytest.fixture
def repo():
    with TemporaryDirectory() as tmp:
        repo = SQLiteRepository(Path(tmp) / "test.db")
        repo.initialise_schema()
        yield repo


@pytest.fixture
def wise_token(monkeypatch):
    monkeypatch.setenv("WISE_API_TOKEN", "test-token")


class MockFXClient:
    rates = {("EUR", "CHF"): 0.95}

    def fetch_rate(self, base, quote, valuation_date):
        return self.rates[(base, quote)]


class Resp:
    def __init__(self, payload=None, status=200, headers=None):
        self._payload, self.status_code, self.headers = payload, status, headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


PROFILES = [{"id": 900, "type": "BUSINESS"}, {"id": 123, "type": "PERSONAL"}]
BALANCES = [
    {"id": 1, "currency": "CHF", "amount": {"value": 1200.5, "currency": "CHF"}, "type": "STANDARD"},
    {"id": 2, "currency": "EUR", "amount": {"value": 100.0, "currency": "EUR"}, "type": "STANDARD"},
    {"id": 3, "currency": "USD", "amount": {"value": 0, "currency": "USD"}, "type": "STANDARD"},
]


def fake_get(calls):
    def _get(url, params=None, headers=None, timeout=None):
        calls.append((url, params, headers))
        path = url.removeprefix("https://api.wise.com")
        if path == "/v2/profiles":
            return Resp(PROFILES)
        if path == "/v4/profiles/123/balances":
            assert params == {"types": "STANDARD"}
            return Resp(BALANCES)
        if "balance-statements" in path:
            # Wise no longer signs statement requests for personal accounts (PSD2): never ask.
            raise AssertionError(f"statement endpoint must not be called: {url}")
        raise AssertionError(f"unexpected {url}")
    return _get


class TestWiseSync:

    def test_balances_become_cash_holdings_in_chf(self, repo, wise_token):
        calls = []
        with patch("backend.sources.wise.requests.get", side_effect=fake_get(calls)):
            assert wise.sync_wise(repo, fx_client=MockFXClient()) == 2

        by_label = {h["label"]: h for h in repo.list_holdings()}
        assert set(by_label) == {"Wise CHF", "Wise EUR"}  # empty USD balance skipped
        assert by_label["Wise CHF"]["value_chf"] == 1200.5
        assert by_label["Wise EUR"]["value_chf"] == 95.0
        assert by_label["Wise EUR"]["native_amount"] == 100.0
        assert all(h["asset_class"] == "cash" and h["source"] == "wise" for h in by_label.values())
        assert all(h[2] == {"Authorization": "Bearer test-token"} for h in calls)

    def test_statement_is_never_requested_and_no_transactions_are_stored(self, repo, wise_token):
        calls = []
        with patch("backend.sources.wise.requests.get", side_effect=fake_get(calls)):
            wise.sync_wise(repo, fx_client=MockFXClient())
        assert not any("balance-statements" in url for url, _, _ in calls)
        assert repo._connection.execute("SELECT COUNT(*) FROM wise_transactions").fetchone()[0] == 0

    def test_private_key_setting_is_inert(self, repo, wise_token, monkeypatch):
        monkeypatch.setenv("WISE_PRIVATE_KEY_PATH", "/nonexistent/wise.pem")
        with patch("backend.sources.wise.requests.get", side_effect=fake_get([])):
            assert wise.sync_wise(repo, fx_client=MockFXClient()) == 2

    def test_profile_id_override_skips_profile_lookup(self, repo, wise_token, monkeypatch):
        monkeypatch.setenv("WISE_PROFILE_ID", "123")
        calls = []
        with patch("backend.sources.wise.requests.get", side_effect=fake_get(calls)):
            wise.sync_wise(repo, fx_client=MockFXClient())
        assert not any(url.endswith("/v2/profiles") for url, _, _ in calls)


class TestWiseInSyncAll:

    def test_wise_syncs_without_error_and_logs_ok(self, repo, wise_token):
        from backend.sync.engine import run_sync_all
        with patch("backend.sources.wise.requests.get", side_effect=fake_get([])), \
             patch("backend.sources.wise.convert_to_chf", side_effect=lambda r, v, c, f=None: {"amount_chf": v}):
            result = run_sync_all(repo)
        assert result == {"ok": ["wise"], "error": []}
        assert repo.get_last_sync_log("wise")["status"] == "ok"


def test_not_configured_without_token():
    assert wise.is_configured() is False
