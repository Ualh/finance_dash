from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

from backend import api
from backend.database import SQLiteRepository

BROWSER = {"accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}


@pytest.fixture
def client(monkeypatch):
    with TemporaryDirectory() as tmp:
        dist = Path(tmp) / "dist"
        (dist / "assets").mkdir(parents=True)
        (dist / "index.html").write_text("<html>spa</html>")
        (dist / "assets" / "app.js").write_text("console.log(1)")
        (Path(tmp) / "secret.txt").write_text("outside dist")
        monkeypatch.setattr(api, "FRONTEND_DIST", dist)
        monkeypatch.setenv("FINANCE_DASH_DB_FILE", str(Path(tmp) / "test.db"))
        with TestClient(api.app) as c:
            repo = SQLiteRepository(Path(tmp) / "test.db")
            repo.initialise_schema()
            api.app.state.repository = repo
            yield c


@pytest.mark.parametrize("path", ["/settings", "/update", "/", "/settings/"])
def test_browser_navigation_to_a_client_route_gets_the_app(client, path):
    """Regression: refreshing or opening /settings directly returned {"detail":"Not Found"}."""
    resp = client.get(path, headers=BROWSER)
    assert resp.status_code == 200
    assert resp.text == "<html>spa</html>"


def test_static_asset_is_served(client):
    resp = client.get("/assets/app.js")
    assert resp.status_code == 200
    assert resp.text == "console.log(1)"


def test_api_calls_still_get_json(client):
    assert client.get("/settings/theme").json() == {"key": "theme", "value": None}
    resp = client.get("/no-such-endpoint")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Not Found"}


def test_api_404_detail_is_kept(client):
    resp = client.put("/holdings/999", json={"value_chf": 1})
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Holding not found"}


def test_files_outside_dist_are_not_served(client):
    resp = client.get("/../secret.txt")
    assert "outside dist" not in resp.text
