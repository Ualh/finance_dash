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

class TestSettings:

    def test_get_setting_returns_default_when_missing(self, client):
        resp = client.get("/settings/display_currency")
        assert resp.status_code == 200
        data = resp.json()
        assert data["key"] == "display_currency"
        assert data["value"] is None

    def test_theme_setting_persists(self, client):
        resp = client.put("/settings/theme", json={"value": "dark"})
        assert resp.status_code == 200
        assert resp.json()["value"] == "dark"

        resp = client.get("/settings/theme")
        assert resp.status_code == 200
        assert resp.json()["value"] == "dark"

    def test_theme_setting_idempotent(self, client):
        client.put("/settings/theme", json={"value": "dark"})
        client.put("/settings/theme", json={"value": "dark"})
        resp = client.get("/settings/theme")
        assert resp.json()["value"] == "dark"


class TestManualHoldings:

    def test_list_holdings_empty(self, client):
        resp = client.get("/holdings")
        assert resp.status_code == 200
        assert resp.json()["holdings"] == []

    def test_list_holdings_returns_seeded(self, client):
        repo = app.state.repository
        seed_holding(repo, "finpension", "manual", "pension", 100_000, label="Pillar 3a")

        resp = client.get("/holdings")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["holdings"]) == 1
        assert data["holdings"][0]["value_chf"] == 100_000.0
        assert data["holdings"][0]["label"] == "Pillar 3a"

    def test_update_holding_value_returns_updated(self, client):
        repo = app.state.repository
        seed_holding(repo, "finpension", "manual", "pension", 100_000, label="Pillar 3a")
        h = repo.list_holdings()[0]

        resp = client.put(f"/holdings/{h['id']}", json={"value_chf": 120_000.0})
        assert resp.status_code == 200
        data = resp.json()
        assert data["holding"]["value_chf"] == 120_000.0

        row = repo.get_holding(h["id"])
        assert row["value_chf"] == 120_000.0

    def test_update_holds_no_duplicate(self, client):
        repo = app.state.repository
        seed_holding(repo, "finpension", "manual", "pension", 100_000, label="Pillar 3a")
        h = repo.list_holdings()[0]

        client.put(f"/holdings/{h['id']}", json={"value_chf": 120_000.0})
        rows = repo._connection.execute(
            "SELECT COUNT(*) as cnt FROM holdings WHERE source = 'finpension'"
        ).fetchone()
        assert rows["cnt"] == 1

    def test_update_nonexistent_holding_404(self, client):
        resp = client.put("/holdings/99999", json={"value_chf": 100.0})
        assert resp.status_code == 404

    def test_dashboard_reflects_updated_value(self, client):
        repo = app.state.repository
        seed_holding(repo, "finpension", "manual", "pension", 100_000, label="Pillar 3a")
        h = repo.list_holdings()[0]

        client.put(f"/holdings/{h['id']}", json={"value_chf": 150_000.0})

        dash = client.get("/dashboard")
        assert dash.status_code == 200
        assert dash.json()["total_chf"] == 150_000.0
