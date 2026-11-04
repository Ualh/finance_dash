from __future__ import annotations

import sqlite3
from datetime import date

import pytest

from backend.backup import backup_database


def make_db(path):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (v INTEGER)")
    conn.execute("INSERT INTO t VALUES (42)")
    conn.commit()
    conn.close()


def test_copy_is_a_readable_database(tmp_path):
    db = tmp_path / "finance_dash.db"
    make_db(db)
    target = backup_database(db, tmp_path / "backups", keep=30, today=date(2026, 11, 4))
    assert target.name == "finance_dash_20261104.db"
    assert sqlite3.connect(target).execute("SELECT v FROM t").fetchone() == (42,)
    assert not list((tmp_path / "backups").glob("*.partial"))


def test_keeps_only_the_newest_copies(tmp_path):
    db = tmp_path / "finance_dash.db"
    make_db(db)
    for day in range(1, 6):
        backup_database(db, tmp_path / "backups", keep=3, today=date(2026, 11, day))
    names = sorted(p.name for p in (tmp_path / "backups").iterdir())
    assert names == ["finance_dash_20261103.db", "finance_dash_20261104.db", "finance_dash_20261105.db"]


def test_missing_database_fails_loudly(tmp_path):
    with pytest.raises(FileNotFoundError):
        backup_database(tmp_path / "nope.db", tmp_path / "backups", keep=3)
    assert not (tmp_path / "nope.db").exists()
