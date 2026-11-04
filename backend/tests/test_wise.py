from __future__ import annotations

import base64
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from backend.database import SQLiteRepository
from backend.sources import wise

NOW = datetime(2026, 11, 4, 6, 0, tzinfo=timezone.utc)


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


def statement(currency, *txs):
    return {"transactions": list(txs), "query": {"currency": currency}}


def tx(ref, type_, value, currency, date, detail_type="CARD", description="Coop"):
    return {
        "type": type_,
        "date": date,
        "amount": {"value": value, "currency": currency},
        "details": {"type": detail_type, "description": description},
        "referenceNumber": ref,
    }


STATEMENTS = {
    1: statement("CHF",
                 tx("CARD-1", "DEBIT", -42.5, "CHF", "2026-10-30T12:00:00.000Z"),
                 tx("TRANSFER-2", "CREDIT", 2500, "CHF", "2026-10-25T08:00:00.000Z", "DEPOSIT", "Salary"),
                 tx("BALANCE-3", "DEBIT", -100, "CHF", "2026-10-26T08:00:00.000Z", "CONVERSION", "To EUR")),
    2: statement("EUR", tx("CARD-4", "DEBIT", -20, "EUR", "2026-11-02T10:00:00.000Z")),
    3: statement("USD"),
}


def fake_get(calls):
    def _get(url, params=None, headers=None, timeout=None):
        calls.append((url, params, headers))
        path = url.removeprefix("https://api.wise.com")
        if path == "/v2/profiles":
            return Resp(PROFILES)
        if path == "/v4/profiles/123/balances":
            assert params == {"types": "STANDARD"}
            return Resp(BALANCES)
        if path.startswith("/v1/profiles/123/balance-statements/"):
            balance_id = int(path.split("/")[5])
            assert params["type"] == "COMPACT"
            return Resp(STATEMENTS[balance_id])
        raise AssertionError(f"unexpected {url}")
    return _get


class TestWiseSync:

    def test_balances_become_cash_holdings_in_chf(self, repo, wise_token):
        calls = []
        with patch("backend.sources.wise.requests.get", side_effect=fake_get(calls)):
            assert wise.sync_wise(repo, fx_client=MockFXClient(), now=NOW) == 2

        by_label = {h["label"]: h for h in repo.list_holdings()}
        assert set(by_label) == {"Wise CHF", "Wise EUR"}  # empty USD balance skipped
        assert by_label["Wise CHF"]["value_chf"] == 1200.5
        assert by_label["Wise EUR"]["value_chf"] == 95.0
        assert by_label["Wise EUR"]["native_amount"] == 100.0
        assert all(h["asset_class"] == "cash" and h["source"] == "wise" for h in by_label.values())
        assert all(h[2] == {"Authorization": "Bearer test-token"} for h in calls)

    def test_statement_lines_are_stored_signed_and_deduplicated(self, repo, wise_token):
        with patch("backend.sources.wise.requests.get", side_effect=fake_get([])):
            wise.sync_wise(repo, fx_client=MockFXClient(), now=NOW)
            wise.sync_wise(repo, fx_client=MockFXClient(), now=NOW)

        rows = repo._connection.execute(
            "SELECT reference_number, date, amount, amount_chf, detail_type FROM wise_transactions ORDER BY reference_number"
        ).fetchall()
        assert [tuple(r) for r in rows] == [
            ("BALANCE-3", "2026-10-26", -100.0, -100.0, "CONVERSION"),
            ("CARD-1", "2026-10-30", -42.5, -42.5, "CARD"),
            ("CARD-4", "2026-11-02", -20.0, -19.0, "CARD"),
            ("TRANSFER-2", "2026-10-25", 2500.0, 2500.0, "DEPOSIT"),
        ]

    def test_next_sync_starts_from_the_last_one_with_overlap(self, repo, wise_token):
        calls = []
        repo.set_setting(wise.STATEMENT_CURSOR_KEY, "2026-11-01T06:00:00+00:00")
        with patch("backend.sources.wise.requests.get", side_effect=fake_get(calls)):
            wise.sync_wise(repo, fx_client=MockFXClient(), now=NOW)
        statement_params = [p for url, p, _ in calls if "balance-statements" in url]
        assert {p["intervalStart"] for p in statement_params} == {"2026-10-29T06:00:00.000Z"}
        assert {p["intervalEnd"] for p in statement_params} == {"2026-11-04T06:00:00.000Z"}
        assert repo.get_setting(wise.STATEMENT_CURSOR_KEY) == "2026-11-04T06:00:00+00:00"

    def test_profile_id_override_skips_profile_lookup(self, repo, wise_token, monkeypatch):
        monkeypatch.setenv("WISE_PROFILE_ID", "123")
        calls = []
        with patch("backend.sources.wise.requests.get", side_effect=fake_get(calls)):
            wise.sync_wise(repo, fx_client=MockFXClient(), now=NOW)
        assert not any(url.endswith("/v2/profiles") for url, _, _ in calls)


class TestWiseStrongCustomerAuthentication:

    def _sca_get(self, calls):
        inner = fake_get(calls)

        def _get(url, params=None, headers=None, timeout=None):
            if "balance-statements" in url and "X-2FA-Approval" not in headers:
                calls.append((url, params, dict(headers)))
                return Resp(status=403, headers={"x-2fa-approval-result": "REJECTED", "x-2fa-approval": "ott-123"})
            return inner(url, params, dict(headers), timeout)
        return _get

    def test_without_private_key_balances_sync_and_error_explains(self, repo, wise_token):
        with patch("backend.sources.wise.requests.get", side_effect=self._sca_get([])):
            with pytest.raises(wise.WiseStatementUnavailable, match="WISE_PRIVATE_KEY_PATH"):
                wise.sync_wise(repo, fx_client=MockFXClient(), now=NOW)
        assert {h["label"] for h in repo.list_holdings()} == {"Wise CHF", "Wise EUR"}
        assert repo.get_setting(wise.STATEMENT_CURSOR_KEY) is None

    def test_signs_the_one_time_token_and_retries(self, repo, wise_token, monkeypatch, tmp_path):
        key = tmp_path / "wise.pem"
        subprocess.run(["openssl", "genrsa", "-out", str(key), "2048"], check=True, capture_output=True)
        pub = tmp_path / "wise.pub.pem"
        subprocess.run(["openssl", "rsa", "-in", str(key), "-pubout", "-out", str(pub)], check=True, capture_output=True)
        monkeypatch.setenv("WISE_PRIVATE_KEY_PATH", str(key))

        calls = []
        with patch("backend.sources.wise.requests.get", side_effect=self._sca_get(calls)):
            wise.sync_wise(repo, fx_client=MockFXClient(), now=NOW)

        retried = [h for url, _, h in calls if "balance-statements" in url and "X-2FA-Approval" in h]
        assert len(retried) == 3
        assert retried[0]["X-2FA-Approval"] == "ott-123"
        signature = tmp_path / "sig.bin"
        signature.write_bytes(base64.b64decode(retried[0]["X-Signature"]))
        verify = subprocess.run(
            ["openssl", "dgst", "-sha256", "-verify", str(pub), "-signature", str(signature)],
            input=b"ott-123", capture_output=True,
        )
        assert verify.returncode == 0, verify.stdout
        assert repo._connection.execute("SELECT COUNT(*) FROM wise_transactions").fetchone()[0] == 4


def test_not_configured_without_token():
    assert wise.is_configured() is False
