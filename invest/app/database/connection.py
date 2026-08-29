"""SQLite connection helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.config import DATA_DIR, DB_PATH, SCHEMA_PATH


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Open a SQLite connection with sensible defaults."""
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_database(db_path: Path | None = None) -> Path:
    """Create data directory and apply schema if needed."""
    path = db_path or DB_PATH
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    conn = get_connection(path)
    try:
        conn.executescript(schema_sql)
        conn.commit()
    finally:
        conn.close()
    return path
