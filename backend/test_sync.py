from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient
from freezegun import freeze_time

from backend.api import app


@pytest.fixture
def client(monkeypatch):
    with TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        monkeypatch.setenv("FINANCE_DASH_DB_FILE", str(db_path))
        app.state.repository = _make_repo(db_path)
        with TestClient(app) as c:
            yield c


def _make_repo(db_path: Path):
    from backend.database import SQLiteRepository
    repo = SQLiteRepository(db_path)
    repo.initialise_schema()
    return repo


def seed_holding(repo, source: str, source_type: str, asset_class: str, value_chf: float, label: str | None = None):
    repo.upsert_holding(source, source_type, asset_class, value_chf, label)


class TestSyncAll:

    def test_sync_writes_snapshot_per_source(self, client):
        repo = app.state.repository
        seed_holding(repo, "finpension", "api", "pension", 100_000)
        seed_holding(repo, "postfinance", "api", "cash", 10_000)

        with freeze_time("2026-06-16 08:00:00"):
            resp = client.post("/sync/all")

        assert resp.status_code == 200
        data = resp.json()
        assert set(data["ok"]) == {"finpension", "postfinance"}
        assert data["error"] == []

        rows = repo._connection.execute(
            "SELECT snapshot_date, source, total_chf FROM nw_snapshots ORDER BY source"
        ).fetchall()
        snapshots = {r["source"]: r for r in rows}
        assert "finpension" in snapshots
        assert snapshots["finpension"]["total_chf"] == 100_000.0
        assert "postfinance" in snapshots
        assert snapshots["postfinance"]["total_chf"] == 10_000.0
        assert "total" in snapshots
        assert snapshots["total"]["total_chf"] == 110_000.0

    def test_second_call_same_day_is_idempotent(self, client):
        repo = app.state.repository
        seed_holding(repo, "finpension", "api", "pension", 100_000)
        with freeze_time("2026-06-16 08:00:00"):
            client.post("/sync/all")
            client.post("/sync/all")

        rows = repo._connection.execute(
            "SELECT COUNT(*) as cnt FROM nw_snapshots WHERE snapshot_date = '2026-06-16'"
        ).fetchall()
        assert rows[0]["cnt"] == 2

    def test_error_source_logged_without_blocking_others(self, client):
        repo = app.state.repository
        seed_holding(repo, "finpension", "api", "pension", 100_000)
        seed_holding(repo, "swissquote", "api", "etf", 50_000)

        with freeze_time("2026-06-16 08:00:00"):
            resp = client.post("/sync/all")

        assert resp.status_code == 200
        data = resp.json()
        assert "finpension" in data["ok"]
        assert "swissquote" in data["ok"]

        log = repo._connection.execute(
            "SELECT source, status FROM sync_log ORDER BY source"
        ).fetchall()
        statuses = {r["source"]: r["status"] for r in log}
        assert statuses.get("finpension") == "ok"
        assert statuses.get("swissquote") == "ok"

    def test_sync_writes_snapshot_for_manual_sources(self, client):
        repo = app.state.repository
        seed_holding(repo, "finpension", "manual", "pension", 80_000)
        seed_holding(repo, "csv_upload", "manual", "cash", 20_000)

        with freeze_time("2026-06-16 08:00:00"):
            client.post("/sync/all")

        snapshots = repo._connection.execute(
            "SELECT source, total_chf FROM nw_snapshots WHERE source != 'total'"
        ).fetchall()
        sources = {r["source"]: r["total_chf"] for r in snapshots}
        assert sources["finpension"] == 80_000.0
        assert sources["csv_upload"] == 20_000.0

    def test_dashboard_delta_j1_works_across_days(self, client):
        repo = app.state.repository
        seed_holding(repo, "finpension", "api", "pension", 100_000)

        with freeze_time("2026-06-15 08:00:00"):
            resp1 = client.post("/sync/all")
        assert resp1.status_code == 200

        with freeze_time("2026-06-16 08:00:00"):
            seed_holding(repo, "finpension", "api", "pension", 120_000)
            resp2 = client.post("/sync/all")
        assert resp2.status_code == 200

        with freeze_time("2026-06-16 08:05:00"):
            dash = client.get("/dashboard")
        assert dash.status_code == 200
        d = dash.json()
        assert d["delta_chf"] == 20_000.0
        assert d["total_chf"] == 120_000.0


class TestDashboard:

    def test_dashboard_includes_sync_error_flag(self, client):
        repo = app.state.repository
        seed_holding(repo, "finpension", "api", "pension", 100_000)

        repo.log_sync_start("finpension", "2026-06-16T07:00:00")
        repo.log_sync_end("finpension", "error", "API unreachable", "2026-06-16T07:00:00")

        dash = client.get("/dashboard")
        assert dash.status_code == 200
        d = dash.json()
        assert d["sources"]["finpension"]["sync_error"] is True
        assert d["sources"]["finpension"]["last_sync"] is not None

    def test_dashboard_delta_null_when_no_prior_snapshot(self, client):
        seed_holding(app.state.repository, "finpension", "api", "pension", 100_000)
        dash = client.get("/dashboard")
        assert dash.status_code == 200
        d = dash.json()
        assert d["delta_chf"] is None
        assert d["delta_pct"] is None
