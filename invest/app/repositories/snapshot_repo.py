"""Capital snapshot repository for growth charts."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.utils.dates import now_iso, today_iso


@dataclass
class CapitalSnapshot:
    id: int | None
    date: str
    total_value: float
    created_at: str = ""


class SnapshotRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert(self, total_value: float, date_str: str | None = None) -> None:
        d = date_str or today_iso()
        now = now_iso()
        self._conn.execute(
            """
            INSERT INTO capital_snapshots (date, total_value, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET total_value = excluded.total_value
            """,
            (d, total_value, now),
        )
        self._conn.commit()

    def upsert_today(self, total_value: float, date_str: str | None = None) -> None:
        """Alias kept for callers; always writes/overwrites the given date."""
        self.upsert(total_value, date_str)

    def insert_if_missing(self, total_value: float, date_str: str) -> bool:
        """Store a historical day only when no row exists yet."""
        row = self._conn.execute(
            "SELECT 1 FROM capital_snapshots WHERE date = ?",
            (date_str,),
        ).fetchone()
        if row:
            return False
        self._conn.execute(
            """
            INSERT INTO capital_snapshots (date, total_value, created_at)
            VALUES (?, ?, ?)
            """,
            (date_str, total_value, now_iso()),
        )
        self._conn.commit()
        return True

    def get(self, date_str: str) -> CapitalSnapshot | None:
        row = self._conn.execute(
            "SELECT * FROM capital_snapshots WHERE date = ?",
            (date_str,),
        ).fetchone()
        if not row:
            return None
        return CapitalSnapshot(
            id=row["id"],
            date=row["date"],
            total_value=float(row["total_value"]),
            created_at=row["created_at"],
        )

    def list_all(self) -> list[CapitalSnapshot]:
        rows = self._conn.execute(
            "SELECT * FROM capital_snapshots ORDER BY date ASC"
        ).fetchall()
        return [
            CapitalSnapshot(
                id=r["id"],
                date=r["date"],
                total_value=float(r["total_value"]),
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def first(self) -> CapitalSnapshot | None:
        row = self._conn.execute(
            "SELECT * FROM capital_snapshots ORDER BY date ASC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        return CapitalSnapshot(
            id=row["id"],
            date=row["date"],
            total_value=float(row["total_value"]),
            created_at=row["created_at"],
        )
