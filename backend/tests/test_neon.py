from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

from backend.api import app
from backend.config import AppConfig
from backend.csv_source.neon import (
    NeonParseError,
    archive_csv,
    compute_balance_from_ledger,
    derive_balance,
    get_archive_dir,
    parse_neon_csv,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class TestNeonParser:

    def test_parse_may_csv(self):
        content = load_fixture("2026_5_account_statements_neon.csv")
        rows = parse_neon_csv(content)
        assert len(rows) == 12

        first = rows[0]
        assert first["date"] == "2026-05-31"
        assert first["amount"] == -150.0

        last = rows[-1]
        assert last["date"] == "2026-05-01"
        assert last["amount"] == 600.0

    def test_parse_june_csv(self):
        content = load_fixture("2026_6_account_statements_neon.csv")
        rows = parse_neon_csv(content)
        assert len(rows) == 10

        total = sum(r["amount"] for r in rows)
        assert total == 1550.0

    def test_empty_csv_raises_error(self):
        content = load_fixture("empty.csv")
        rows = parse_neon_csv(content)
        assert rows == []

    def test_corrupted_row_raises_error(self):
        content = load_fixture("corrupted_row.csv")
        with pytest.raises(NeonParseError, match="Row 3.*Amount"):
            parse_neon_csv(content)

    def test_bom_is_stripped(self):
        content = load_fixture("with_bom.csv")
        bommed = b"\xef\xbb\xbf" + content
        rows = parse_neon_csv(bommed)
        assert len(rows) == 1
        assert rows[0]["amount"] == 100.0

    def test_parse_non_csv_raises_error(self):
        with pytest.raises(NeonParseError, match="Missing required columns"):
            parse_neon_csv(b"foo,bar\n1,2")

    def test_parse_empty_bytes_raises_error(self):
        with pytest.raises(NeonParseError, match="Empty CSV"):
            parse_neon_csv(b"")


class TestDeriveBalance:

    def test_without_anchor_uses_all_rows(self):
        rows = [{"date": "2026-06-01", "amount": 100.0}, {"date": "2026-05-01", "amount": -50.0}]
        assert derive_balance(rows) == 50.0

    def test_with_anchor_sums_post_anchor(self):
        rows = [
            {"date": "2026-06-10", "amount": -30.0},
            {"date": "2026-06-05", "amount": 200.0},
            {"date": "2026-06-01", "amount": -50.0},
            {"date": "2026-05-20", "amount": -100.0},
        ]
        balance = derive_balance(rows, anchor_date="2026-06-01", anchor_amount=1000.0)
        expected = 1000.0 + (-30.0) + 200.0 + (-50.0)
        assert balance == expected

    def test_anchor_filters_correctly(self):
        rows = [
            {"date": "2026-06-15", "amount": 500.0},
            {"date": "2026-06-10", "amount": -100.0},
        ]
        balance = derive_balance(rows, anchor_date="2026-06-12", anchor_amount=2000.0)
        assert balance == 2000.0 + 500.0

    def test_no_rows_with_anchor_returns_anchor(self):
        rows = []
        balance = derive_balance(rows, anchor_date="2026-06-01", anchor_amount=3000.0)
        assert balance == 3000.0

    def test_no_rows_no_anchor_returns_zero(self):
        assert derive_balance([]) == 0.0


class TestComputeBalanceFromLedger:

    def test_no_anchor_sums_all(self):
        txs = [{"date": "2026-06-01", "amount": 100.0}, {"date": "2026-05-01", "amount": -50.0}]
        assert compute_balance_from_ledger(txs) == 50.0

    def test_with_anchor_sums_post_anchor(self):
        txs = [
            {"date": "2026-06-10", "amount": -30.0},
            {"date": "2026-06-05", "amount": 200.0},
            {"date": "2026-06-01", "amount": -50.0},
            {"date": "2026-05-20", "amount": -100.0},
        ]
        balance = compute_balance_from_ledger(txs, anchor_date="2026-06-01", anchor_amount=1000.0)
        expected = 1000.0 + (-30.0) + 200.0 + (-50.0)
        assert balance == expected

    def test_no_transactions_with_anchor_returns_anchor(self):
        assert compute_balance_from_ledger([], anchor_date="2026-06-01", anchor_amount=3000.0) == 3000.0

    def test_no_transactions_no_anchor_returns_zero(self):
        assert compute_balance_from_ledger([]) == 0.0

    def test_spaces_rows_are_included(self):
        txs = [
            {"date": "2026-05-31", "amount": -150.0},
            {"date": "2026-05-01", "amount": -1000.0},
            {"date": "2026-05-01", "amount": 600.0},
        ]
        balance = compute_balance_from_ledger(txs, anchor_date="2026-05-01", anchor_amount=2585.22)
        assert balance == 2585.22 + (-150.0) + (-1000.0) + 600.0


class TestArchiveCsv:

    def test_archive_writes_file(self):
        with TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            content = b"Date;Amount\n2026-01-01;100"
            path = archive_csv(project_root, content)
            assert path.parent == get_archive_dir(project_root)
            assert path.name.endswith(".csv")
            assert path.read_bytes() == content

    def test_archive_keeps_exact_content(self):
        with TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            content = b"hello,world\n1,2"
            path = archive_csv(project_root, content)
            assert path.read_bytes() == content


@pytest.fixture
def tmp_home(monkeypatch):
    with TemporaryDirectory() as tmp:
        monkeypatch.setattr("backend.api.load_config", lambda: AppConfig(
            project_root=Path(tmp),
            database_file=Path(tmp) / "test.db",
        ))
        from backend.database import SQLiteRepository
        repo = SQLiteRepository(Path(tmp) / "test.db")
        repo.initialise_schema()
        app.state.repository = repo
        yield Path(tmp)


@pytest.fixture
def client(tmp_home):
    with TestClient(app) as c:
        yield c


class TestUploadEndpoint:

    def test_upload_may_csv_creates_holding(self, client, tmp_home):
        content = load_fixture("2026_5_account_statements_neon.csv")
        resp = client.post("/holdings/neon/upload", files={"file": ("may.csv", content, "text/csv")})
        assert resp.status_code == 200
        data = resp.json()
        assert data["transactions_parsed"] == 12
        assert data["holding"]["source"] == "neon"
        assert data["holding"]["asset_class"] == "cash"
        assert data["holding"]["label"] == "Neon"

    def test_upload_then_june_does_not_duplicate(self, client, tmp_home):
        may = load_fixture("2026_5_account_statements_neon.csv")
        june = load_fixture("2026_6_account_statements_neon.csv")

        resp1 = client.post("/holdings/neon/upload", files={"file": ("may.csv", may, "text/csv")})
        assert resp1.status_code == 200

        resp2 = client.post("/holdings/neon/upload", files={"file": ("june.csv", june, "text/csv")})
        assert resp2.status_code == 200

        holdings = client.app.state.repository.list_holdings()
        neon_holdings = [h for h in holdings if h["source"] == "neon"]
        assert len(neon_holdings) == 1

    def test_upload_empty_csv_returns_400(self, client, tmp_home):
        content = load_fixture("empty.csv")
        resp = client.post("/holdings/neon/upload", files={"file": ("empty.csv", content, "text/csv")})
        assert resp.status_code == 400

    def test_upload_corrupted_csv_returns_400(self, client, tmp_home):
        content = load_fixture("corrupted_row.csv")
        resp = client.post("/holdings/neon/upload", files={"file": ("bad.csv", content, "text/csv")})
        assert resp.status_code == 400
        assert "Row 3" in resp.json()["detail"]

    def test_upload_non_csv_returns_400(self, client, tmp_home):
        resp = client.post("/holdings/neon/upload", files={"file": ("data.txt", b"hello", "text/plain")})
        assert resp.status_code == 400
        assert ".csv" in resp.json()["detail"]

    def test_upload_archives_file(self, client, tmp_home):
        content = load_fixture("2026_5_account_statements_neon.csv")
        resp = client.post("/holdings/neon/upload", files={"file": ("may.csv", content, "text/csv")})
        assert resp.status_code == 200

        archive_dir = tmp_home / "data" / "csv_archive" / "neon"
        assert archive_dir.exists()
        archived = list(archive_dir.glob("*.csv"))
        assert len(archived) == 1
        assert archived[0].read_bytes() == content

    def test_upload_with_anchor_derives_balance(self, client, tmp_home):
        repo = client.app.state.repository
        repo.set_setting("neon_anchor_date", "2026-05-15")
        repo.set_setting("neon_anchor_amount", "5000.0")

        may = load_fixture("2026_5_account_statements_neon.csv")
        resp = client.post("/holdings/neon/upload", files={"file": ("may.csv", may, "text/csv")})
        assert resp.status_code == 200
        data = resp.json()
        assert data["balance"] == 7205.0


class TestLedgerPersistence:

    def test_replace_neon_transactions_inserts_and_replaces(self, client, tmp_home):
        repo = client.app.state.repository
        rows_a = [
            {"date": "2026-05-01", "amount": 100.0, "description": "first"},
            {"date": "2026-05-15", "amount": 200.0, "description": "second"},
        ]
        inserted = repo.replace_neon_transactions("2026-05-01", "2026-05-31", rows_a)
        assert inserted == 2

        all_txs = repo.get_all_neon_transactions()
        assert len(all_txs) == 2

        rows_b = [
            {"date": "2026-05-10", "amount": 300.0, "description": "replacement"},
            {"date": "2026-05-20", "amount": 400.0, "description": "also new"},
        ]
        inserted = repo.replace_neon_transactions("2026-05-01", "2026-05-31", rows_b)
        assert inserted == 2

        all_txs = repo.get_all_neon_transactions()
        assert len(all_txs) == 2

        dates = sorted(t["date"] for t in all_txs)
        assert dates == ["2026-05-10", "2026-05-20"]

    def test_replace_outside_range_keeps_others(self, client, tmp_home):
        repo = client.app.state.repository
        rows_a = [
            {"date": "2026-05-01", "amount": 100.0, "description": "may"},
        ]
        repo.replace_neon_transactions("2026-05-01", "2026-05-31", rows_a)

        rows_june = [
            {"date": "2026-06-01", "amount": 200.0, "description": "june"},
        ]
        repo.replace_neon_transactions("2026-06-01", "2026-06-30", rows_june)

        all_txs = repo.get_all_neon_transactions()
        assert len(all_txs) == 2

    def test_reupload_same_file_is_idempotent(self, client, tmp_home):
        repo = client.app.state.repository
        rows = [
            {"date": "2026-05-01", "amount": 100.0, "description": "dup"},
        ]
        repo.replace_neon_transactions("2026-05-01", "2026-05-31", rows)
        repo.replace_neon_transactions("2026-05-01", "2026-05-31", rows)

        all_txs = repo.get_all_neon_transactions()
        assert len(all_txs) == 1


class TestUploadAccumulation:

    def test_may_then_june_accumulates(self, client, tmp_home):
        repo = client.app.state.repository
        repo.set_setting("neon_anchor_date", "2026-05-01")
        repo.set_setting("neon_anchor_amount", "2585.22")

        may = load_fixture("2026_5_account_statements_neon.csv")
        resp1 = client.post("/holdings/neon/upload", files={"file": ("may.csv", may, "text/csv")})
        assert resp1.status_code == 200
        may_balance = resp1.json()["balance"]

        june = load_fixture("2026_6_account_statements_neon.csv")
        resp2 = client.post("/holdings/neon/upload", files={"file": ("june.csv", june, "text/csv")})
        assert resp2.status_code == 200
        june_balance = resp2.json()["balance"]

        all_txs = repo.get_all_neon_transactions()
        assert len(all_txs) == 22

        expected_may = 2585.22 + sum(r["amount"] for r in parse_neon_csv(may))
        assert may_balance == expected_may

        all_parsed = parse_neon_csv(may) + parse_neon_csv(june)
        expected_june = 2585.22 + sum(r["amount"] for r in all_parsed)
        assert june_balance == expected_june

    def test_reupload_may_after_june_stays_correct(self, client, tmp_home):
        repo = client.app.state.repository
        repo.set_setting("neon_anchor_date", "2026-05-01")
        repo.set_setting("neon_anchor_amount", "2585.22")

        may = load_fixture("2026_5_account_statements_neon.csv")
        june = load_fixture("2026_6_account_statements_neon.csv")

        client.post("/holdings/neon/upload", files={"file": ("may.csv", may, "text/csv")})
        client.post("/holdings/neon/upload", files={"file": ("june.csv", june, "text/csv")})

        all_parsed = parse_neon_csv(may) + parse_neon_csv(june)
        expected = 2585.22 + sum(r["amount"] for r in all_parsed)

        resp = client.post("/holdings/neon/upload", files={"file": ("may.csv", may, "text/csv")})
        assert resp.status_code == 200
        assert resp.json()["balance"] == expected

        all_txs = repo.get_all_neon_transactions()
        assert len(all_txs) == 22

    def test_holding_is_single_neon_line(self, client, tmp_home):
        repo = client.app.state.repository
        repo.set_setting("neon_anchor_date", "2026-05-01")
        repo.set_setting("neon_anchor_amount", "2585.22")

        may = load_fixture("2026_5_account_statements_neon.csv")
        june = load_fixture("2026_6_account_statements_neon.csv")

        client.post("/holdings/neon/upload", files={"file": ("may.csv", may, "text/csv")})
        client.post("/holdings/neon/upload", files={"file": ("june.csv", june, "text/csv")})

        holdings = repo.list_holdings()
        neon_holdings = [h for h in holdings if h["source"] == "neon"]
        assert len(neon_holdings) == 1
        h = neon_holdings[0]
        assert h["source_type"] == "csv"
        assert h["asset_class"] == "cash"

    def test_spaces_rows_count_toward_balance(self, client, tmp_home):
        may = load_fixture("2026_5_account_statements_neon.csv")
        may_rows = parse_neon_csv(may)
        space_rows = [r for r in may_rows if r.get("description") == "Space Transfer"]
        assert len(space_rows) == 1
        assert space_rows[0]["amount"] == 600.0

        repo = client.app.state.repository
        repo.set_setting("neon_anchor_date", "2026-05-01")
        repo.set_setting("neon_anchor_amount", "2585.22")

        resp = client.post("/holdings/neon/upload", files={"file": ("may.csv", may, "text/csv")})
        assert resp.status_code == 200

        total = sum(r["amount"] for r in may_rows)
        expected = 2585.22 + total
        assert resp.json()["balance"] == expected
