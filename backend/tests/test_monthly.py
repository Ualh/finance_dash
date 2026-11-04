"""The monthly ritual: per-source freshness, cash withdrawals, spending, and the curve."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient
from freezegun import freeze_time

from backend.api import app
from backend.config import AppConfig
from backend.database import SQLiteRepository

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def client(monkeypatch):
    with TemporaryDirectory() as tmp:
        monkeypatch.setattr(
            "backend.api.load_config",
            lambda: AppConfig(project_root=Path(tmp), database_file=Path(tmp) / "test.db"),
        )
        repo = SQLiteRepository(Path(tmp) / "test.db")
        repo.initialise_schema()
        app.state.repository = repo
        with TestClient(app) as c:
            yield c


def repo() -> SQLiteRepository:
    return app.state.repository


def upload_neon(client, name="2026_5_account_statements_neon.csv"):
    content = (FIXTURES / name).read_bytes()
    return client.post("/holdings/neon/upload", files={"file": (name, content, "text/csv")})


def add_wise_tx(ref, date, amount, detail_type="CARD"):
    repo().import_wise_transactions([{
        "reference_number": ref, "currency": "CHF", "date": date, "amount": amount,
        "amount_chf": amount, "detail_type": detail_type, "description": ref,
    }])


class TestFreshness:

    def test_neon_and_finpension_are_always_listed_and_stale_when_missing(self, client):
        with freeze_time("2026-11-01 06:00:00"):
            data = client.get("/freshness").json()
        assert data["stale_after_days"] == 35
        assert data["stale"] == ["neon", "finpension"]
        assert [s["kind"] for s in data["sources"]] == ["manual", "manual"]
        assert all(s["as_of"] is None and s["stale"] for s in data["sources"])
        assert data["actions"][0].startswith("Upload last month's Neon CSV")

    def test_neon_age_follows_its_latest_transaction_not_the_upload_day(self, client):
        with freeze_time("2026-06-26 09:00:00"):
            upload_neon(client)  # transactions run to 2026-05-31
            client.post("/holdings/finpension", json={"value_chf": 40_000})
        with freeze_time("2026-07-10 06:00:00"):
            by_source = {s["source"]: s for s in client.get("/freshness").json()["sources"]}
        assert by_source["neon"]["as_of"] == "2026-05-31"
        assert by_source["neon"]["age_days"] == 40
        assert by_source["neon"]["stale"] is True
        assert by_source["finpension"]["as_of"] == "2026-06-26"
        assert by_source["finpension"]["stale"] is False

    def test_stale_threshold_is_35_days(self, client):
        with freeze_time("2026-10-01 06:00:00"):
            client.post("/holdings/finpension", json={"value_chf": 40_000})
        with freeze_time("2026-11-05 06:00:00"):
            fin = client.get("/freshness").json()["sources"][1]
        assert (fin["age_days"], fin["stale"]) == (35, False)
        with freeze_time("2026-11-06 06:00:00"):
            fin = client.get("/freshness").json()["sources"][1]
        assert (fin["age_days"], fin["stale"]) == (36, True)

    def test_configured_automatic_source_is_listed_before_its_first_sync(self, client, monkeypatch):
        monkeypatch.setenv("BINANCE_API_KEY", "k")
        monkeypatch.setenv("BINANCE_API_SECRET", "s")
        with freeze_time("2026-11-01 06:00:00"):
            sources = client.get("/freshness").json()["sources"]
        binance = next(s for s in sources if s["source"] == "binance")
        assert binance["kind"] == "automatic"
        assert binance["stale"] is True

    def test_dashboard_sources_carry_freshness(self, client):
        with freeze_time("2026-10-01 06:00:00"):
            client.post("/holdings", json={"label": "UBS Fund", "asset_class": "etf", "amount": 5000})
        with freeze_time("2026-11-20 06:00:00"):
            sources = client.get("/dashboard").json()["sources"]
        assert sources["ubs_fund"]["label"] == "UBS Fund"
        assert sources["ubs_fund"]["stale"] is True
        assert sources["ubs_fund"]["total_chf"] == 5000.0
        assert sources["finpension"]["total_chf"] is None


class TestCashWithdrawals:

    def test_record_list_and_delete(self, client):
        resp = client.post("/cash-withdrawals", json={"amount_chf": 200, "date": "2026-11-02", "note": "  market "})
        assert resp.status_code == 200
        w = resp.json()["withdrawal"]
        assert (w["amount_chf"], w["date"], w["note"]) == (200.0, "2026-11-02", "market")

        assert [x["id"] for x in client.get("/cash-withdrawals").json()["withdrawals"]] == [w["id"]]
        assert client.delete(f"/cash-withdrawals/{w['id']}").status_code == 200
        assert client.get("/cash-withdrawals").json()["withdrawals"] == []
        assert client.delete(f"/cash-withdrawals/{w['id']}").status_code == 404

    @pytest.mark.parametrize("body", [
        {"amount_chf": 0, "date": "2026-11-02"},
        {"amount_chf": -5, "date": "2026-11-02"},
        {"amount_chf": 20, "date": "not-a-date"},
    ])
    def test_invalid_input_is_rejected(self, client, body):
        assert client.post("/cash-withdrawals", json=body).status_code in (400, 422)

    def test_cash_does_not_change_net_worth(self, client):
        client.post("/holdings/finpension", json={"value_chf": 10_000})
        before = client.get("/dashboard").json()["total_chf"]
        client.post("/cash-withdrawals", json={"amount_chf": 300, "date": "2026-11-02"})
        assert client.get("/dashboard").json()["total_chf"] == before


class TestSpending:

    def spending(self, client, today="2026-05-31 12:00:00"):
        with freeze_time(today):
            return {m["month"]: m for m in client.get("/dashboard").json()["spending"]}

    def test_neon_outflows_are_spending(self, client):
        upload_neon(client)
        may = self.spending(client)["2026-05"]
        # Every negative row of the May fixture; income and refunds are not spending.
        assert may["total_chf"] == 150 + 45 + 200 + 80 + 120 + 500 + 60 + 30 + 1000
        assert may["cash_chf"] == 0

    def test_this_month_and_last_month_are_returned(self, client):
        months = self.spending(client, "2026-06-03 12:00:00")
        assert list(months) == ["2026-06", "2026-05"]

    def test_wise_debits_count_but_internal_moves_do_not(self, client):
        add_wise_tx("CARD-1", "2026-05-10", -40.0)
        add_wise_tx("CONV-1", "2026-05-11", -500.0, "CONVERSION")
        add_wise_tx("XBAL-1", "2026-05-12", -100.0, "OUTGOING_CROSS_BALANCE")
        add_wise_tx("IN-1", "2026-05-13", 900.0, "DEPOSIT")
        assert self.spending(client)["2026-05"]["total_chf"] == 40.0

    def test_neon_space_moves_are_not_spending(self, client):
        csv = (
            'Date;Amount;Original amount;Original currency;Exchange rate;Description;Subject;Category;Tags;Wise;Spaces\n'
            '"2026-05-10";"-600.00";"-600.00";"CHF";"1.0";"To Space";"";"finances";"";"no";"yes"\n'
            '"2026-05-11";"-25.00";"-25.00";"CHF";"1.0";"Coop";"";"food";"";"no";"no"\n'
        ).encode()
        client.post("/holdings/neon/upload", files={"file": ("may.csv", csv, "text/csv")})
        assert self.spending(client)["2026-05"]["total_chf"] == 25.0

    def test_cash_without_bank_line_yet_counts_as_spending(self, client):
        client.post("/cash-withdrawals", json={"amount_chf": 200, "date": "2026-05-25"})
        may = self.spending(client)["2026-05"]
        assert (may["total_chf"], may["cash_chf"]) == (200.0, 200.0)

    def test_cash_matching_an_atm_debit_is_counted_once(self, client):
        # The May fixture has "ZKB ATM" -200.00 on 2026-05-25.
        client.post("/cash-withdrawals", json={"amount_chf": 200, "date": "2026-05-24", "note": "ATM"})
        upload_neon(client)
        may = self.spending(client)["2026-05"]
        assert may["total_chf"] == 2185.0  # same as without the cash record
        assert may["cash_chf"] == 200.0

    def test_two_withdrawals_cannot_share_one_debit(self, client):
        upload_neon(client)
        client.post("/cash-withdrawals", json={"amount_chf": 200, "date": "2026-05-25"})
        client.post("/cash-withdrawals", json={"amount_chf": 200, "date": "2026-05-26"})
        may = self.spending(client)["2026-05"]
        assert may["total_chf"] == 2185.0 + 200.0
        assert may["cash_chf"] == 400.0


class TestCurveFollowsEveryChange:

    def test_manual_entry_writes_todays_snapshot(self, client):
        with freeze_time("2026-10-31 20:00:00"):
            client.post("/holdings/finpension", json={"value_chf": 40_000})
        with freeze_time("2026-11-01 08:00:00"):
            client.post("/holdings/finpension", json={"value_chf": 41_500})
            d = client.get("/dashboard").json()
        assert d["history"] == [
            {"month": "2026-10", "date": "2026-10-31", "total_chf": 40_000.0},
            {"month": "2026-11", "date": "2026-11-01", "total_chf": 41_500.0},
        ]
        assert d["change_since_last_month"]["amount_chf"] == 1_500.0

    def test_neon_upload_writes_todays_snapshot(self, client):
        with freeze_time("2026-06-26 09:00:00"):
            upload_neon(client)
        snaps = repo().list_total_snapshots()
        assert snaps == [{"snapshot_date": "2026-06-26", "total_chf": 615.0}]

    def test_history_converts_to_display_currency(self, client):
        with freeze_time("2026-10-31 20:00:00"):
            client.post("/holdings/finpension", json={"value_chf": 40_000})
        repo().put_fx_rate("CHF", "USD", "2026-11-01", 1.25)
        with freeze_time("2026-11-01 08:00:00"):
            d = client.get("/dashboard?currency=USD").json()
        assert [p["total_chf"] for p in d["history"]] == [50_000.0, 50_000.0]
        assert d["change_since_last_month"]["amount_chf"] == 0.0


def test_existing_database_is_migrated(tmp_path):
    """The live database predates the Spaces flag and the Wise/cash tables."""
    import sqlite3

    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE neon_uploads (id INTEGER PRIMARY KEY, file_hash TEXT UNIQUE, filename TEXT, uploaded_at TEXT);
        CREATE TABLE neon_transactions (id INTEGER PRIMARY KEY, date TEXT, amount REAL, upload_id INTEGER);
        INSERT INTO neon_uploads VALUES (1, 'h', 'may.csv', '2026-06-25');
        INSERT INTO neon_transactions VALUES (1, '2026-05-02', -12.5, 1);
    """)
    conn.commit()
    conn.close()

    migrated = SQLiteRepository(db)
    migrated.initialise_schema()
    debits = migrated.list_bank_debits("2026-05-01", "2026-05-31", frozenset())
    assert debits == [{"source": "neon", "date": "2026-05-02", "amount_chf": -12.5}]
    assert migrated.list_cash_withdrawals() == []
