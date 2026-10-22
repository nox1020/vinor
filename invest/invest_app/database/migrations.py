"""Versioned SQLite migrations (non-destructive)."""

from __future__ import annotations

import logging
import sqlite3

from invest_app.config import DEFAULT_SETTINGS, SETTING_THEME, THEME_DARK
from invest_app.utils.dates import now_iso

logger = logging.getLogger(__name__)

MIGRATION_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY NOT NULL,
    applied_at  TEXT NOT NULL
);
"""

CURRENT_SCHEMA_VERSION = 7

_MIGRATION_4_SQL = """
CREATE TABLE IF NOT EXISTS checks (
    id            INTEGER PRIMARY KEY,
    direction     TEXT NOT NULL,
    amount        REAL NOT NULL,
    issue_date    TEXT NOT NULL,
    due_date      TEXT NOT NULL,
    check_number  TEXT NOT NULL DEFAULT '',
    sayad_id      TEXT NOT NULL DEFAULT '',
    bank_name     TEXT NOT NULL DEFAULT '',
    branch        TEXT NOT NULL DEFAULT '',
    counterparty  TEXT NOT NULL DEFAULT '',
    purpose       TEXT NOT NULL DEFAULT '',
    note          TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'pending',
    settled_date  TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_checks_due ON checks (due_date);
CREATE INDEX IF NOT EXISTS idx_checks_status ON checks (status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_checks_sayad_active
    ON checks (sayad_id)
    WHERE sayad_id != '' AND status != 'cancelled';
CREATE UNIQUE INDEX IF NOT EXISTS idx_checks_number_active
    ON checks (direction, bank_name, check_number)
    WHERE check_number != '' AND status != 'cancelled';
"""

_MIGRATION_5_SQL = """
CREATE TABLE IF NOT EXISTS pwo_withdrawers (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    archived    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pwo_entries (
    id            INTEGER PRIMARY KEY,
    withdrawer_id INTEGER NOT NULL,
    year          INTEGER NOT NULL,
    month         INTEGER NOT NULL,
    amount        REAL NOT NULL DEFAULT 0,
    note          TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    UNIQUE (withdrawer_id, year, month),
    FOREIGN KEY (withdrawer_id) REFERENCES pwo_withdrawers(id)
);

CREATE INDEX IF NOT EXISTS idx_pwo_entries_period ON pwo_entries (year, month);
"""

_MIGRATION_6_SQL = """
CREATE TABLE IF NOT EXISTS pwo_transactions (
    id            INTEGER PRIMARY KEY,
    withdrawer_id INTEGER NOT NULL,
    year          INTEGER NOT NULL,
    month         INTEGER NOT NULL,
    amount        REAL NOT NULL,
    note          TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    FOREIGN KEY (withdrawer_id) REFERENCES pwo_withdrawers(id)
);

CREATE INDEX IF NOT EXISTS idx_pwo_tx_period ON pwo_transactions (year, month);
"""

_MIGRATION_7_SQL = """
CREATE TABLE IF NOT EXISTS biz_property_trades (
    id          INTEGER PRIMARY KEY,
    buy_date    TEXT NOT NULL,
    sell_date   TEXT NOT NULL DEFAULT '',
    buy_amount  REAL NOT NULL DEFAULT 0,
    sell_amount REAL NOT NULL DEFAULT 0,
    area        REAL,
    title       TEXT NOT NULL DEFAULT '',
    extra_cost  REAL NOT NULL DEFAULT 0,
    note        TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS biz_monthly_ops (
    id         INTEGER PRIMARY KEY,
    year       INTEGER NOT NULL,
    month      INTEGER NOT NULL,
    staff      REAL NOT NULL DEFAULT 0,
    ads        REAL NOT NULL DEFAULT 0,
    income     REAL NOT NULL DEFAULT 0,
    note       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (year, month)
);
"""

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


def _migrate_4(conn: sqlite3.Connection) -> None:
    """دفتر چک. جدول خالی است؛ ردیف‌های قبلی پاک نمی‌شوند."""
    conn.executescript(_MIGRATION_4_SQL)
    conn.commit()
    logger.info("Applied schema migration version 4 (checks)")


def _migrate_5(conn: sqlite3.Connection) -> None:
    """PWO: جدول‌های تازه؛ فقط وقتی خالی‌اند M/A/N پیش‌فرض اضافه می‌شود."""
    conn.executescript(_MIGRATION_5_SQL)
    if conn.execute("SELECT COUNT(*) FROM pwo_withdrawers").fetchone()[0] == 0:
        ts = now_iso()
        for i, name in enumerate(("M", "A", "N")):
            conn.execute(
                "INSERT INTO pwo_withdrawers (name, sort_order, archived, created_at, updated_at)"
                " VALUES (?, ?, 0, ?, ?)",
                (name, i, ts, ts),
            )
    conn.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('pwo_monthly_target', '100000000')"
    )
    conn.commit()
    logger.info("Applied schema migration version 5 (pwo)")


def _migrate_6(conn: sqlite3.Connection) -> None:
    """PWO: جدول برداشت‌های تکی (افزودنی). ردیف‌های pwo_entries دست نمی‌خورند."""
    conn.executescript(_MIGRATION_6_SQL)
    conn.commit()
    logger.info("Applied schema migration version 6 (pwo transactions)")


def _migrate_7(conn: sqlite3.Connection) -> None:
    """کسب‌وکار ملک: جدول‌های افزودنی معاملات ملک و هزینه/درآمد ماهانه."""
    conn.executescript(_MIGRATION_7_SQL)
    conn.commit()
    logger.info("Applied schema migration version 7 (biz property/monthly)")


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

    if 4 not in applied:
        _migrate_4(conn)
        _record(conn, 4)
        applied = _applied_versions(conn)

    if 5 not in applied:
        _migrate_5(conn)
        _record(conn, 5)
        applied = _applied_versions(conn)

    if 6 not in applied:
        _migrate_6(conn)
        _record(conn, 6)
        applied = _applied_versions(conn)

    if 7 not in applied:
        _migrate_7(conn)
        _record(conn, 7)
        applied = _applied_versions(conn)

    latest = max(applied) if applied else 0
    if CURRENT_SCHEMA_VERSION > latest:
        logger.warning(
            "App expects schema %s but DB is at %s",
            CURRENT_SCHEMA_VERSION,
            latest,
        )
