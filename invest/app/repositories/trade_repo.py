"""Trade repository."""

from __future__ import annotations

import sqlite3

from app.config import TRADE_STATUS_CLOSED, TRADE_STATUS_OPEN
from app.models.trade import Trade
from app.utils.dates import now_iso


_JOIN_SELECT = """
    SELECT t.*, a.name AS asset_name, a.symbol AS asset_symbol,
           a.current_price AS current_price
    FROM trades t
    JOIN assets a ON a.id = t.asset_id
"""


class TradeRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def list_by_status(self, status: str, search: str = "") -> list[Trade]:
        params: list = [status]
        where = "t.status = ?"
        if search.strip():
            like = f"%{search.strip()}%"
            where += " AND (a.name LIKE ? OR a.symbol LIKE ? OR t.buy_note LIKE ? OR t.sell_note LIKE ?)"
            params.extend([like, like, like, like])
        order = (
            "t.buy_date DESC, t.id DESC"
            if status == TRADE_STATUS_OPEN
            else "t.sell_date DESC, t.id DESC"
        )
        rows = self._conn.execute(
            f"{_JOIN_SELECT} WHERE {where} ORDER BY {order}",
            params,
        ).fetchall()
        return [Trade.from_row(r) for r in rows]

    def list_open(self, search: str = "") -> list[Trade]:
        return self.list_by_status(TRADE_STATUS_OPEN, search)

    def list_closed(self, search: str = "") -> list[Trade]:
        return self.list_by_status(TRADE_STATUS_CLOSED, search)

    def get(self, trade_id: int) -> Trade | None:
        row = self._conn.execute(
            f"{_JOIN_SELECT} WHERE t.id = ?", (trade_id,)
        ).fetchone()
        return Trade.from_row(row) if row else None

    def count_by_status(self, status: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS c FROM trades WHERE status = ?", (status,)
        ).fetchone()
        return int(row["c"])

    def create(self, trade: Trade, *, commit: bool = True) -> Trade:
        now = now_iso()
        trade.created_at = now
        trade.updated_at = now
        cur = self._conn.execute(
            """
            INSERT INTO trades (
                asset_id, status, quantity, buy_price, buy_fee, buy_date, buy_note,
                sell_price, sell_fee, sell_date, sell_note,
                realized_pnl, return_pct, holding_days, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade.asset_id,
                trade.status,
                trade.quantity,
                trade.buy_price,
                trade.buy_fee,
                trade.buy_date,
                trade.buy_note,
                trade.sell_price,
                trade.sell_fee,
                trade.sell_date,
                trade.sell_note,
                trade.realized_pnl,
                trade.return_pct,
                trade.holding_days,
                trade.created_at,
                trade.updated_at,
            ),
        )
        trade.id = int(cur.lastrowid)
        if commit:
            self._conn.commit()
        return trade

    def update(self, trade: Trade, *, commit: bool = True) -> Trade:
        trade.updated_at = now_iso()
        self._conn.execute(
            """
            UPDATE trades SET
                asset_id = ?, status = ?, quantity = ?, buy_price = ?, buy_fee = ?,
                buy_date = ?, buy_note = ?, sell_price = ?, sell_fee = ?,
                sell_date = ?, sell_note = ?, realized_pnl = ?, return_pct = ?,
                holding_days = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                trade.asset_id,
                trade.status,
                trade.quantity,
                trade.buy_price,
                trade.buy_fee,
                trade.buy_date,
                trade.buy_note,
                trade.sell_price,
                trade.sell_fee,
                trade.sell_date,
                trade.sell_note,
                trade.realized_pnl,
                trade.return_pct,
                trade.holding_days,
                trade.updated_at,
                trade.id,
            ),
        )
        if commit:
            self._conn.commit()
        return trade

    def delete(self, trade_id: int) -> None:
        self._conn.execute("DELETE FROM trades WHERE id = ?", (trade_id,))
        self._conn.commit()

    def closed_stats(self) -> dict:
        row = self._conn.execute(
            """
            SELECT
                COUNT(*) AS count,
                COALESCE(SUM(realized_pnl), 0) AS total_pnl,
                COALESCE(MAX(CASE WHEN realized_pnl > 0 THEN realized_pnl END), 0)
                    AS max_profit,
                COALESCE(MIN(CASE WHEN realized_pnl < 0 THEN realized_pnl END), 0)
                    AS max_loss
            FROM trades
            WHERE status = ?
            """,
            (TRADE_STATUS_CLOSED,),
        ).fetchone()
        return {
            "count": int(row["count"]),
            "total_pnl": float(row["total_pnl"]),
            "max_profit": float(row["max_profit"]),
            "max_loss": float(row["max_loss"]),
        }

    def list_closed_for_reports(self) -> list[Trade]:
        return self.list_closed()

    def list_by_asset(
        self, asset_id: int, status: str | None = None
    ) -> list[Trade]:
        """List trades for one asset, optionally filtered by status."""
        params: list = [asset_id]
        where = "t.asset_id = ?"
        if status:
            where += " AND t.status = ?"
            params.append(status)
        rows = self._conn.execute(
            f"""
            {_JOIN_SELECT}
            WHERE {where}
            ORDER BY COALESCE(t.sell_date, t.buy_date) DESC, t.id DESC
            """,
            params,
        ).fetchall()
        return [Trade.from_row(r) for r in rows]
