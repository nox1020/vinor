"""Rich portfolio snapshot repository (daily marks)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.utils.dates import now_iso, today_iso


@dataclass
class PortfolioSnapshot:
    id: int | None
    snapshot_date: str
    total_value: float
    cash_invested: float
    realized_pnl_cumulative: float
    unrealized_pnl: float
    total_fees_cumulative: float
    created_at: str = ""


@dataclass
class PortfolioSnapshotAsset:
    asset_id: int
    quantity: float
    price: float
    value: float
    weight_pct: float


class PortfolioSnapshotRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert(
        self,
        *,
        total_value: float,
        cash_invested: float,
        realized_pnl_cumulative: float,
        unrealized_pnl: float,
        total_fees_cumulative: float = 0.0,
        assets: list[PortfolioSnapshotAsset] | None = None,
        date_str: str | None = None,
    ) -> int:
        d = date_str or today_iso()
        now = now_iso()
        self._conn.execute(
            """
            INSERT INTO portfolio_snapshots (
                snapshot_date, total_value, cash_invested,
                realized_pnl_cumulative, unrealized_pnl,
                total_fees_cumulative, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(snapshot_date) DO UPDATE SET
                total_value = excluded.total_value,
                cash_invested = excluded.cash_invested,
                realized_pnl_cumulative = excluded.realized_pnl_cumulative,
                unrealized_pnl = excluded.unrealized_pnl,
                total_fees_cumulative = excluded.total_fees_cumulative,
                created_at = excluded.created_at
            """,
            (
                d,
                total_value,
                cash_invested,
                realized_pnl_cumulative,
                unrealized_pnl,
                total_fees_cumulative,
                now,
            ),
        )
        row = self._conn.execute(
            "SELECT id FROM portfolio_snapshots WHERE snapshot_date = ?",
            (d,),
        ).fetchone()
        snapshot_id = int(row["id"])
        self._conn.execute(
            "DELETE FROM portfolio_snapshot_assets WHERE snapshot_id = ?",
            (snapshot_id,),
        )
        for a in assets or []:
            self._conn.execute(
                """
                INSERT INTO portfolio_snapshot_assets (
                    snapshot_id, asset_id, quantity, price, value, weight_pct
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    a.asset_id,
                    a.quantity,
                    a.price,
                    a.value,
                    a.weight_pct,
                ),
            )
        self._conn.commit()
        return snapshot_id

    def list_values(self) -> list[tuple[str, float]]:
        rows = self._conn.execute(
            "SELECT snapshot_date, total_value FROM portfolio_snapshots "
            "ORDER BY snapshot_date ASC"
        ).fetchall()
        return [(r["snapshot_date"], float(r["total_value"])) for r in rows]

    def get(self, date_str: str) -> PortfolioSnapshot | None:
        row = self._conn.execute(
            "SELECT * FROM portfolio_snapshots WHERE snapshot_date = ?",
            (date_str,),
        ).fetchone()
        if not row:
            return None
        return PortfolioSnapshot(
            id=row["id"],
            snapshot_date=row["snapshot_date"],
            total_value=float(row["total_value"]),
            cash_invested=float(row["cash_invested"]),
            realized_pnl_cumulative=float(row["realized_pnl_cumulative"]),
            unrealized_pnl=float(row["unrealized_pnl"]),
            total_fees_cumulative=float(row["total_fees_cumulative"]),
            created_at=row["created_at"],
        )
