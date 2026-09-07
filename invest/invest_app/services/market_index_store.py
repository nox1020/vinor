"""Shared SQLite store for market index snapshots (not per-user)."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_LOCK = threading.RLock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS market_latest (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    payload     TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS inflation_latest (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    payload     TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS market_ticks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at   TEXT NOT NULL,
    essentials    TEXT NOT NULL,
    wallex_count  INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_market_ticks_captured
    ON market_ticks (captured_at);
"""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None = None) -> str:
    d = dt or _utcnow()
    return d.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class MarketIndexStore:
    """Persist latest full index + minute ticks for essentials."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK:
            self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    def save_latest(self, payload: dict[str, Any]) -> None:
        blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        now = _iso()
        essentials = payload.get("essentials") or []
        wallex = payload.get("wallex_markets") or []
        with _LOCK:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO market_latest (id, payload, updated_at)
                    VALUES (1, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        payload = excluded.payload,
                        updated_at = excluded.updated_at
                    """,
                    (blob, now),
                )
                conn.execute(
                    """
                    INSERT INTO market_ticks (captured_at, essentials, wallex_count)
                    VALUES (?, ?, ?)
                    """,
                    (
                        now,
                        json.dumps(essentials, ensure_ascii=False, separators=(",", ":")),
                        len(wallex),
                    ),
                )
                # Keep ~7 days of minute ticks.
                cutoff = _iso(_utcnow() - timedelta(days=7))
                conn.execute(
                    "DELETE FROM market_ticks WHERE captured_at < ?",
                    (cutoff,),
                )
                conn.commit()

    def load_latest(self) -> tuple[dict[str, Any] | None, str | None]:
        with _LOCK:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT payload, updated_at FROM market_latest WHERE id = 1"
                ).fetchone()
        if not row:
            return None, None
        try:
            return json.loads(row["payload"]), row["updated_at"]
        except json.JSONDecodeError:
            logger.exception("Corrupt market_latest payload")
            return None, None

    def age_seconds(self, updated_at: str | None) -> float | None:
        if not updated_at:
            return None
        try:
            text = updated_at.replace("Z", "+00:00")
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return max(0.0, (_utcnow() - dt.astimezone(timezone.utc)).total_seconds())
        except ValueError:
            return None

    def save_inflation(self, payload: dict[str, Any]) -> None:
        blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        now = _iso()
        with _LOCK:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO inflation_latest (id, payload, updated_at)
                    VALUES (1, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        payload = excluded.payload,
                        updated_at = excluded.updated_at
                    """,
                    (blob, now),
                )
                conn.commit()

    def load_inflation(self) -> tuple[dict[str, Any] | None, str | None]:
        with _LOCK:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT payload, updated_at FROM inflation_latest WHERE id = 1"
                ).fetchone()
        if not row:
            return None, None
        try:
            return json.loads(row["payload"]), row["updated_at"]
        except json.JSONDecodeError:
            return None, None

    def load_ticks(self, *, hours: float = 24) -> list[dict[str, Any]]:
        cutoff = _iso(_utcnow() - timedelta(hours=max(1.0, hours)))
        with _LOCK:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT captured_at, essentials, wallex_count
                    FROM market_ticks
                    WHERE captured_at >= ?
                    ORDER BY captured_at ASC
                    """,
                    (cutoff,),
                ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            try:
                essentials = json.loads(row["essentials"])
            except json.JSONDecodeError:
                continue
            out.append(
                {
                    "captured_at": row["captured_at"],
                    "essentials": essentials,
                    "wallex_count": int(row["wallex_count"] or 0),
                }
            )
        return out
