from __future__ import annotations

from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
TAG = '<script src="/notes.js" data-app="Finance" data-endpoint="http://100.127.215.65:8096"></script>'


def test_index_embeds_notes_widget_before_body_end():
    html = (FRONTEND / "index.html").read_text()
    assert TAG in html
    assert html.index(TAG) < html.index("</body>")


def test_notes_widget_is_served_from_app_static_files():
    assert (FRONTEND / "public" / "notes.js").is_file()
