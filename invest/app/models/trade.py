"""Trade domain model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.config import TRADE_STATUS_CLOSED, TRADE_STATUS_OPEN


@dataclass
class Trade:
    """An open or closed trade position."""

    id: int | None
    asset_id: int
    status: str
    quantity: float
    buy_price: float
    buy_fee: float = 0.0
    buy_date: str = ""
    buy_note: str = ""
    sell_price: float | None = None
    sell_fee: float = 0.0
    sell_date: str | None = None
    sell_note: str = ""
    realized_pnl: float | None = None
    return_pct: float | None = None
    holding_days: int | None = None
    created_at: str = ""
    updated_at: str = ""
    # Joined display fields
    asset_name: str = ""
    asset_symbol: str = ""
    current_price: float = 0.0

    @property
    def is_open(self) -> bool:
        return self.status == TRADE_STATUS_OPEN

    @property
    def is_closed(self) -> bool:
        return self.status == TRADE_STATUS_CLOSED

    @property
    def buy_cost(self) -> float:
        return self.quantity * self.buy_price + self.buy_fee

    @property
    def current_value(self) -> float:
        price = self.current_price if self.is_open else (self.sell_price or 0.0)
        return self.quantity * price

    @classmethod
    def from_row(cls, row) -> Trade:
        keys = row.keys()
        return cls(
            id=row["id"],
            asset_id=row["asset_id"],
            status=row["status"],
            quantity=float(row["quantity"]),
            buy_price=float(row["buy_price"]),
            buy_fee=float(row["buy_fee"] or 0),
            buy_date=row["buy_date"],
            buy_note=row["buy_note"] or "",
            sell_price=None if row["sell_price"] is None else float(row["sell_price"]),
            sell_fee=float(row["sell_fee"] or 0),
            sell_date=row["sell_date"],
            sell_note=row["sell_note"] or "",
            realized_pnl=(
                None if row["realized_pnl"] is None else float(row["realized_pnl"])
            ),
            return_pct=(
                None if row["return_pct"] is None else float(row["return_pct"])
            ),
            holding_days=row["holding_days"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            asset_name=row["asset_name"] if "asset_name" in keys else "",
            asset_symbol=row["asset_symbol"] if "asset_symbol" in keys else "",
            current_price=(
                float(row["current_price"]) if "current_price" in keys else 0.0
            ),
        )

    def touch(self) -> None:
        self.updated_at = (
            datetime.now(timezone.utc)
            .replace(tzinfo=None)
            .isoformat(timespec="seconds")
        )
        if not self.created_at:
            self.created_at = self.updated_at
