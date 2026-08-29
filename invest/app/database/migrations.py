"""Versioned SQLite migrations (non-destructive)."""

from __future__ import annotations

import logging
import sqlite3

from app.config import DEFAULT_SETTINGS, SETTING_THEME, THEME_DARK
from app.utils.dates import now_iso

logger = logging.getLogger(__name__)

MIGRATION_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY NOT NULL,
    applied_at  TEXT NOT NULL
);
"""

CURRENT_SCHEMA_VERSION = 3

_MIGRATION_2_SQL = """
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date           TEXT NOT NULL UNIQUE,
    total_value             REAL NOT NULL,
    cash_invested           REAL NOT NULL DEFAULT 0,
    realized_pnl_cumulative REAL NOT NULL DEFAULT 0,
    unrealized_pnl          REAL NOT NULL DEFAULT 0,
    total_fees_cumulative   REAL NOT NULL DEFAULT 0,
    created_at              TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_portfolio_snapshots_date
    ON portfolio_snapshots (snapshot_date);

CREATE TABLE IF NOT EXISTS portfolio_snapshot_assets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL,
    asset_id    INTEGER NOT NULL,
    quantity    REAL NOT NULL,
    price       REAL NOT NULL,
    value       REAL NOT NULL,
    weight_pct  REAL NOT NULL DEFAULT 0,
    FOREIGN KEY (snapshot_id) REFERENCES portfolio_snapshots(id) ON DELETE CASCADE,
    FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_psa_snapshot
    ON portfolio_snapshot_assets (snapshot_id);
"""


def ensure_default_settings(conn: sqlite3.Connection) -> None:
    """Insert default settings when keys are missing."""
    for key, value in DEFAULT_SETTINGS.items():
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )
    conn.commit()


def _applied_versions(conn: sqlite3.Connection) -> set[int]:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    if not row:
        return set()
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {int(r["version"]) for r in rows}


def _record(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
        (version, now_iso()),
    )
    conn.commit()


def _migrate_2(conn: sqlite3.Connection) -> None:
    conn.executescript(_MIGRATION_2_SQL)
    # Backfill totals from legacy capital_snapshots (no per-asset history).
    rows = conn.execute(
        "SELECT date, total_value, created_at FROM capital_snapshots ORDER BY date"
    ).fetchall()
    for row in rows:
        conn.execute(
            """
            INSERT OR IGNORE INTO portfolio_snapshots (
                snapshot_date, total_value, cash_invested,
                realized_pnl_cumulative, unrealized_pnl,
                total_fees_cumulative, created_at
            ) VALUES (?, ?, 0, 0, 0, 0, ?)
            """,
            (row["date"], row["total_value"], row["created_at"] or now_iso()),
        )
    conn.commit()
    logger.info("Applied schema migration version 2 (portfolio_snapshots)")


def _migrate_3(conn: sqlite3.Connection) -> None:
    """Ensure a theme key exists; never overwrite a user's saved preference."""
    conn.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
        (SETTING_THEME, THEME_DARK),
    )
    conn.commit()
    logger.info("Applied schema migration version 3 (theme default if missing)")


def run_migrations(conn: sqlite3.Connection) -> None:
    """Apply pending migrations without dropping user data."""
    conn.execute(MIGRATION_TABLE)
    applied = _applied_versions(conn)

    if 1 not in applied:
        _record(conn, 1)
        logger.info("Recorded schema migration version 1")
        applied = _applied_versions(conn)

    if 2 not in applied:
        _migrate_2(conn)
        _record(conn, 2)
        applied = _applied_versions(conn)

    if 3 not in applied:
        _migrate_3(conn)
        _record(conn, 3)
        applied = _applied_versions(conn)

    latest = max(applied) if applied else 0
    if CURRENT_SCHEMA_VERSION > latest:
        logger.warning(
            "App expects schema %s but DB is at %s",
            CURRENT_SCHEMA_VERSION,
            latest,
        )
