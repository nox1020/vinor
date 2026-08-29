"""Asset repository."""

from __future__ import annotations

import sqlite3

from app.models.asset import Asset
from app.utils.dates import now_iso


class AssetRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def list_all(self, search: str = "") -> list[Asset]:
        if search.strip():
            like = f"%{search.strip()}%"
            rows = self._conn.execute(
                """
                SELECT * FROM assets
                WHERE name LIKE ? OR symbol LIKE ? OR notes LIKE ?
                ORDER BY name COLLATE NOCASE
                """,
                (like, like, like),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM assets ORDER BY name COLLATE NOCASE"
            ).fetchall()
        return [Asset.from_row(r) for r in rows]

    def get(self, asset_id: int) -> Asset | None:
        row = self._conn.execute(
            "SELECT * FROM assets WHERE id = ?", (asset_id,)
        ).fetchone()
        return Asset.from_row(row) if row else None

    def find_by_name_symbol(self, name: str, symbol: str = "") -> Asset | None:
        row = self._conn.execute(
            "SELECT * FROM assets WHERE name = ? AND symbol = ?",
            (name, symbol),
        ).fetchone()
        return Asset.from_row(row) if row else None

    def create(self, asset: Asset, *, commit: bool = True) -> Asset:
        now = now_iso()
        asset.created_at = now
        asset.updated_at = now
        cur = self._conn.execute(
            """
            INSERT INTO assets
                (name, symbol, quantity, avg_buy_price, current_price, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                asset.name,
                asset.symbol,
                asset.quantity,
                asset.avg_buy_price,
                asset.current_price,
                asset.notes,
                asset.created_at,
                asset.updated_at,
            ),
        )
        asset.id = int(cur.lastrowid)
        if commit:
            self._conn.commit()
        return asset

    def update(self, asset: Asset, *, commit: bool = True) -> Asset:
        asset.updated_at = now_iso()
        self._conn.execute(
            """
            UPDATE assets
            SET name = ?, symbol = ?, quantity = ?, avg_buy_price = ?,
                current_price = ?, notes = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                asset.name,
                asset.symbol,
                asset.quantity,
                asset.avg_buy_price,
                asset.current_price,
                asset.notes,
                asset.updated_at,
                asset.id,
            ),
        )
        if commit:
            self._conn.commit()
        return asset

    def delete(self, asset_id: int) -> None:
        open_count = self._conn.execute(
            "SELECT COUNT(*) AS c FROM trades WHERE asset_id = ? AND status = 'open'",
            (asset_id,),
        ).fetchone()["c"]
        if open_count:
            raise ValueError("نمی‌توان دارایی دارای معامله باز را حذف کرد.")
        try:
            self._conn.execute("DELETE FROM trades WHERE asset_id = ?", (asset_id,))
            self._conn.execute("DELETE FROM assets WHERE id = ?", (asset_id,))
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
