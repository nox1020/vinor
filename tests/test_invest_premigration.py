# -*- coding: utf-8 -*-
"""Pre-migration dated copy of each per-account DB."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "invest"))

from invest_app.database import migrations as m  # noqa: E402
from invest_app.database.connection import get_connection, init_database  # noqa: E402


def _db(path):
    if not path.exists() and m.PREMIGRATION_DIR not in str(path):
        init_database(path)
        return get_connection(path)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _older(path):
    conn = _db(path)
    m.run_migrations(conn)
    conn.execute("INSERT INTO settings VALUES ('marker', 'keep-me')")
    conn.execute("DELETE FROM schema_migrations WHERE version = ?", (m.CURRENT_SCHEMA_VERSION,))
    conn.commit()
    return conn


def test_copy_written_before_pending_migration(tmp_path):
    db = tmp_path / "acc.db"
    conn = _older(db)
    m.run_migrations(conn)
    copies = list((tmp_path / m.PREMIGRATION_DIR).glob("acc.v*-to-v*.db"))
    assert len(copies) == 1
    name = copies[0].name
    assert f".v{m.CURRENT_SCHEMA_VERSION - 1}-to-v{m.CURRENT_SCHEMA_VERSION}." in name
    c = _db(copies[0])
    assert c.execute("SELECT value FROM settings WHERE key='marker'").fetchone()[0] == "keep-me"
    assert c.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == m.CURRENT_SCHEMA_VERSION - 1
    # up to date: no new copy
    m.run_migrations(conn)
    c.close()
    assert len(list((tmp_path / m.PREMIGRATION_DIR).glob("*.db"))) == 1


def test_fresh_db_gets_no_copy(tmp_path):
    conn = _db(tmp_path / "new.db")
    m.run_migrations(conn)
    assert not (tmp_path / m.PREMIGRATION_DIR).exists()


def test_retention_only_touches_own_copies(tmp_path):
    db = tmp_path / "acc.db"
    folder = tmp_path / m.PREMIGRATION_DIR
    folder.mkdir()
    foreign = folder / "acc.manual-backup.db"
    foreign.write_text("x")
    other = tmp_path / "acc.20260101.bak"
    other.write_text("y")
    conn = _older(db)
    for i in range(m.PREMIGRATION_KEEP + 3):
        m.backup_before_migration(conn, 6, 7)
    mine = list(folder.glob("acc.v*-to-v*.db"))
    assert len(mine) == m.PREMIGRATION_KEEP
    assert foreign.exists() and other.exists()


def test_copy_failure_never_blocks_migration(tmp_path, monkeypatch):
    conn = _older(tmp_path / "acc.db")

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(m, "backup_before_migration", boom)
    m.run_migrations(conn)
    assert conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == m.CURRENT_SCHEMA_VERSION
