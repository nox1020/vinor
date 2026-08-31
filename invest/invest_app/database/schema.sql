-- Investment Manager SQLite schema

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY NOT NULL,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assets (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    symbol         TEXT NOT NULL DEFAULT '',
    quantity       REAL NOT NULL DEFAULT 0,
    avg_buy_price  REAL NOT NULL DEFAULT 0,
    current_price  REAL NOT NULL DEFAULT 0,
    notes          TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_assets_name_symbol
    ON assets (name, symbol);

CREATE TABLE IF NOT EXISTS trades (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id      INTEGER NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('open', 'closed')),
    quantity      REAL NOT NULL,
    buy_price     REAL NOT NULL,
    buy_fee       REAL NOT NULL DEFAULT 0,
    buy_date      TEXT NOT NULL,
    buy_note      TEXT NOT NULL DEFAULT '',
    sell_price    REAL,
    sell_fee      REAL DEFAULT 0,
    sell_date     TEXT,
    sell_note     TEXT NOT NULL DEFAULT '',
    realized_pnl  REAL,
    return_pct    REAL,
    holding_days  INTEGER,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_trades_status ON trades (status);
CREATE INDEX IF NOT EXISTS idx_trades_asset ON trades (asset_id);
CREATE INDEX IF NOT EXISTS idx_trades_buy_date ON trades (buy_date);
CREATE INDEX IF NOT EXISTS idx_trades_sell_date ON trades (sell_date);

CREATE TABLE IF NOT EXISTS capital_snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        TEXT NOT NULL UNIQUE,
    total_value REAL NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_snapshots_date ON capital_snapshots (date);
