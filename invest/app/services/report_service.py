"""Reporting aggregations."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass

from app.config import TRADE_STATUS_CLOSED, TRADE_STATUS_OPEN
from app.repositories.trade_repo import TradeRepository
from app.services.portfolio_service import PortfolioService
from app.utils.dates import period_key


@dataclass
class PeriodPnl:
    key: str
    pnl: float
    count: int


@dataclass
class ReportSummary:
    daily: list[PeriodPnl]
    monthly: list[PeriodPnl]
    yearly: list[PeriodPnl]
    max_profit: float
    max_loss: float
    total_realized: float
    open_count: int
    closed_count: int
    growth: list[tuple[str, float]]


class ReportService:
    """Aggregate closed-trade PnL and portfolio growth for reports."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        portfolio: PortfolioService | None = None,
    ) -> None:
        self.trades = TradeRepository(conn)
        self.portfolio = portfolio or PortfolioService(conn)

    def build(self, calendar: str) -> ReportSummary:
        closed = self.trades.list_closed()
        daily = self._aggregate(closed, "daily", calendar)
        monthly = self._aggregate(closed, "monthly", calendar)
        yearly = self._aggregate(closed, "yearly", calendar)
        stats = self.trades.closed_stats()
        return ReportSummary(
            daily=daily,
            monthly=monthly,
            yearly=yearly,
            max_profit=stats["max_profit"],
            max_loss=stats["max_loss"],
            total_realized=stats["total_pnl"],
            open_count=self.trades.count_by_status(TRADE_STATUS_OPEN),
            closed_count=stats["count"],
            growth=self.portfolio.growth_series(persist=False),
        )

    def _aggregate(self, trades, period: str, calendar: str) -> list[PeriodPnl]:
        buckets: dict[str, list[float]] = defaultdict(list)
        for trade in trades:
            if trade.sell_date is None or trade.realized_pnl is None:
                continue
            key = period_key(trade.sell_date, period, calendar)
            buckets[key].append(trade.realized_pnl)
        result = [
            PeriodPnl(key=k, pnl=sum(v), count=len(v))
            for k, v in sorted(buckets.items())
        ]
        return result
