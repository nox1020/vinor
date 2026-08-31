"""Asset domain model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class Asset:
    """A tradable holding tracked by the portfolio."""

    id: int | None
    name: str
    symbol: str = ""
    quantity: float = 0.0
    avg_buy_price: float = 0.0
    current_price: float = 0.0
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""

    @property
    def total_value(self) -> float:
        return self.quantity * self.current_price

    @property
    def cost_basis(self) -> float:
        return self.quantity * self.avg_buy_price

    @property
    def unrealized_pnl(self) -> float:
        return self.total_value - self.cost_basis

    @property
    def unrealized_pnl_pct(self) -> float:
        if self.cost_basis == 0:
            return 0.0
        return (self.unrealized_pnl / self.cost_basis) * 100.0

    @classmethod
    def from_row(cls, row) -> Asset:
        return cls(
            id=row["id"],
            name=row["name"],
            symbol=row["symbol"] or "",
            quantity=float(row["quantity"]),
            avg_buy_price=float(row["avg_buy_price"]),
            current_price=float(row["current_price"]),
            notes=row["notes"] or "",
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def touch(self) -> None:
        self.updated_at = (
            datetime.now(timezone.utc)
            .replace(tzinfo=None)
            .isoformat(timespec="seconds")
        )
        if not self.created_at:
            self.created_at = self.updated_at
